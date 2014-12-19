# -*- coding: utf-8 -*-

import copy
import json
import math
from functools import partial

from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, pyqtSignal, QObject, pyqtSlot, Qt, QUrl, \
    QRectF, SIGNAL, QPointF, QLineF
from PyQt4.QtGui import QAction, QIcon, QPainter, QPen, QBrush, QColor, QPixmap, QCursor, QPolygon
from PyQt4.QtSvg import QSvgRenderer
# Initialize Qt resources from file resources.py
from qgis._core import QgsMapLayerRegistry
import resources_rc
# Import the code for the dialog
from viewer import Viewer
from settingsdialog import SettingsDialog
import os.path
import contextlib

from qgis.core import QgsMessageLog, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsPoint, QgsRectangle, \
    QgsMapLayerRegistry, QGis, QgsGeometry, QgsFeatureRequest, QgsFeature, QgsDistanceArea, QgsRenderContext, QgsMapLayer
from qgis.gui import QgsMapCanvasItem, QgsMapToolEmitPoint, QgsMessageBar, QgsAttributeDialog, QgsRubberBand


class EarthmineSettingsError(Exception):
    pass


@contextlib.contextmanager
def settinggroup(settings, name):
    settings.beginGroup(name)
    yield settings
    settings.endGroup()


def maplayers():
    return QgsMapLayerRegistry.instance().mapLayers().values()


def layer_by_name(name):
    return QgsMapLayerRegistry.instance().mapLayersByName(name)[0]


def layer_by_id(layerid):
    return QgsMapLayerRegistry.instance().mapLayer(layerid)


def feature_by_id(layer, featureid):
    rq = QgsFeatureRequest(int(featureid))
    feature = layer.getFeatures(rq).next()
    return feature


def get_color(render, feature):
    symbol = render.symbolForFeature(feature)
    # name() returns the hex value for the colour
    if not symbol:
        return "0x00ff00"

    name = symbol.color().name()
    value = int("0x" + name[1:], 16)
    return value


def search_area(units, distancearea, point):
    distancearea.sourceCrs()
    distance = 100
    distance = distancearea.convertMeasurement(distance, QGis.Meters, units, False)
    QgsMessageLog.logMessage(str(distance), "Earthmine")
    QgsMessageLog.logMessage(str(units), "Earthmine")
    geom = QgsGeometry.fromPoint(point)
    rect = geom.buffer(distance[0], 10).boundingBox()
    return rect


class EarthminePoint():
    def __init__(self, qgispoint, pointdata):
        for k, v in pointdata.items():
            setattr(self, k, v)

        self.qgispoint = QgsGeometry.fromPoint(qgispoint)

    def distance(self, point):
        return self.qgispoint.distance(point.qgispoint)


def height_diff(p1, p2):
    if not p1.alt or not p2.alt:
        return 0

    try:
        y = p1.alt - p2.alt
        return y
    except IndexError:
        return 0


def safe_disconnect(signal, method):
    try:
        signal.disconnect(method)
    except TypeError:
        pass


class EarthmineLine():
    def __init__(self, points, stats):
        self.points = points
        self._stats = stats
        self.dist = QgsDistanceArea()
        self.convert = self.dist.convertMeasurement

    @property
    def slope(self):
        run = self.total_length_unadjusted
        QgsMessageLog.logMessage(str(run), "Earthmine")
        height = self._stats['height']
        QgsMessageLog.logMessage(str(height), "Earthmine")
        if not height:
            return 0

        try:
            return height / run * 100
        except ZeroDivisionError:
            return 0

    @property
    def total_length(self):
        return self._stats['3D-Total']

    @property
    def total_length_unadjusted(self):
        return self._stats['2D-Total']

    @property
    def total_height(self):
        height = self._stats['height']
        if not height:
            return 0
        return abs(height)

    @property
    def slope_display(self):
        return str(self.slope) + "%"

    def stats(self, units, mode):
        return self.total_length_display(units, mode), \
               self.segment_length_display(units, mode), \
               self.slope_display

    def total_length_display(self, units, mode):
        if mode == "3D":
            return self.convert_to(self.total_length, units)
        elif mode == "Horizontal":
            return self.convert_to(self.total_length_unadjusted, units)
        elif mode == "Vertical":
            return self.convert_to(abs(self.total_height), units)
        else:
            return ""

    def segment_length_display(self, units, mode):
        if mode == "3D":
            return self.convert_to(self._stats['3D'], units)
        if mode == "Horizontal":
            return self.convert_to(self._stats['2D'], units)
        elif mode == "Vertical":
            return self.convert_to(abs(self.total_height), units)
        else:
            return ""

    def segments(self):
        it = zip(self.points, self.points[1:])
        for start, end in it:
            yield self.segment(start, end)

    def segment(self, start, end):
        startlength = start.distance(end)
        height = height_diff(end, start)
        length = math.sqrt(startlength ** 2 + height ** 2)
        return dict(length=startlength, adjusted=length, height=height)

    def convert_to(self, length, units):
        length, _ = self.convert(length, 0, units, False)
        length = QgsDistanceArea.textUnit(length, 3, units, False, True)
        return length


def to_feature_data(layerid, feature, renderer, transform):
    """
    Transform the feature into the data for the viewer to use.
    :param feature: QgsFeature
    :param renderer:
    :param transform:
    :return:
    """
    def polylinenodes(polyline):
        nodes = []
        for point in polyline:
            point = transform.transform(point, QgsCoordinateTransform.ReverseTransform)
            location = dict(lat=point.y(), lng=point.x())
            nodes.append(location)
        return nodes

    geom = feature.geometry()
    geomtype = geom.type()
    featuredata = []
    data = dict(id=feature.id(),
                layerid=layerid,
                color=get_color(renderer, feature),
                geomtype=QGis.vectorGeometryType(geomtype))
    if geomtype == QGis.Point:
        geom = geom.asPoint()
        point = transform.transform(geom, QgsCoordinateTransform.ReverseTransform)
        try:
            z = feature['Z']
            if not z:
                z = 0
        except KeyError:
            z = 0
        location = dict(lat=point.y(), lng=point.x(), z=z)
        data['nodes'] = [location]
        featuredata.append(data)
    elif geomtype == QGis.Line:
        if geom.isMultipart():
            # Copy the data for each polyline
            for polyline in geom.asMultiPolyline():
                newdata = copy.copy(data)
                newdata['nodes'] = polylinenodes(polyline)
                featuredata.append(newdata)
        else:
            data['nodes'] = polylinenodes(geom.asPolyline())
            featuredata.append(data)
    return featuredata


def get_features_in_area(layer, area, transform, mapsettings):
    """
    Return all the features for the given layer in the search area
    :param layer: Search layer
    :param area: Search area
    :param transform:
    :return: yields a dict for each feature found in the area
    """
    renderer = layer.rendererV2()
    layerid = layer.id()
    context = QgsRenderContext.fromMapSettings(mapsettings)
    renderer.startRender(context, layer.pendingFields())
    for feature in layer.getFeatures(QgsFeatureRequest(area)):
        featuredata = to_feature_data(layerid, feature, renderer, transform)
        for data in featuredata:
            yield data
    renderer.stopRender(context)


def get_feature_form(layer, feature, isadd=False):
    dlg = QgsAttributeDialog(layer, feature, False, None)
    dlg.setIsAddDialog(isadd)
    return dlg


class EarthMineQGIS(QObject):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        super(EarthMineQGIS, self).__init__()
        self.movingfeature = None
        self.iface = iface
        self.viewer = None
        self.canvas = self.iface.mapCanvas()
        self.settings = QSettings()
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'EarthMineQGIS_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        self.pointtool = QgsMapToolEmitPoint(self.canvas)
        self.pointtool.canvasClicked.connect(self.set_viewer_location)

        self.settingsdialog = SettingsDialog(self.iface.mainWindow())

        self.actions = []
        self.menu = self.tr(u'&Earthmine')

        self.toolbar = self.iface.addToolBar(u'EarthMineQGIS')
        self.toolbar.setObjectName(u'EarthMineQGIS')

        self.legend = self.iface.legendInterface()

        emcolor = QColor(1, 150, 51)
        self.tempband = QgsRubberBand(self.canvas, QGis.Line)
        self.tempband.setWidth(5)
        self.tempband.setColor(emcolor)

        self.tempbandpoints = QgsRubberBand(self.canvas, QGis.Point)
        self.tempbandpoints.setWidth(7)
        self.tempbandpoints.setColor(emcolor)

        self.movingband = QgsRubberBand(self.canvas, QGis.Point)
        self.movingband.setWidth(5)
        self.movingband.setColor(emcolor)

        self.layersignals = []
        self.marker = None

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/icons/settings'
        self.add_action(
            icon_path,
            text=self.tr(u'Show Settings'),
            callback=self.show_settings,
            parent=self.iface.mainWindow())
        icon_path = ':/icons/viewer'
        self.add_action(
            icon_path,
            text=self.tr(u'Earthmine Viewer'),
            callback=self.open_viewer,
            parent=self.iface.mainWindow())

        self.marker = PostionMarker(self.canvas)
        self.marker.hide()

        self.viewer = Viewer(callbackobject=self)
        self.viewer.trackingChanged.connect(self.marker.setTracking)
        self.viewer.setLocationTriggered.connect(partial(self.canvas.setMapTool, self.pointtool))
        self.viewer.updateFeatures.connect(self.update_earthmine_features)
        self.viewer.layerChanged.connect(self.iface.setActiveLayer)
        self.viewer.clearLine.connect(self.clear_bands)
        self.viewer.closed.connect(self.remove_items)
        self.iface.currentLayerChanged.connect(self.viewer.update_current_layer)

        cursor = QCursor(QPixmap(":/icons/location"))
        self.pointtool.setCursor(cursor)
        self.pointtool.setAction(self.viewer.setlocationaction)

    def remove_items(self):
        self.marker.setTracking(False)
        self.disconnect_projectsignals()
        self.iface.actionPan().trigger()

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        self.canvas.scene().removeItem(self.marker)
        del self.marker

        self.disconnect_projectsignals()

        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Earthmine'),
                action)
            self.iface.removeToolBarIcon(action)

        del self.toolbar

        self.iface.removeDockWidget(self.viewer)
        self.viewer.deleteLater()

    def disconnect_projectsignals(self):
        safe_disconnect(QgsMapLayerRegistry.instance().layerWasAdded, self.connect_layer_signals)
        safe_disconnect(QgsMapLayerRegistry.instance().layersRemoved, self.layers_removed)
        safe_disconnect(self.canvas.layersChanged, self.layers_changed)
        safe_disconnect(self.iface.projectRead, self.connect_signals)
        safe_disconnect(self.canvas.selectionChanged, self.selection_changed)
        safe_disconnect(self.canvas.selectionChanged, self.viewer.selection_changed)

    def clear_bands(self):
        self.tempband.reset(QGis.Line)
        self.tempbandpoints.reset(QGis.Point)

    def visible_layers(self):
        """
        Return the visible layers shown in the map canvas
        :return:
        """
        return (layer for layer, visible in self.layers_with_states() if visible)

    def layers_with_states(self):
        for layer in maplayers():
            if not layer.type() == QgsMapLayer.VectorLayer:
                continue

            if not layer.geometryType() in [QGis.Point, QGis.Line]:
                continue

            yield layer, self.legend.isLayerVisible(layer)

    def _layer_feature_added(self, featureid):
        layer = self.sender()
        if not layer:
            return

        self.layer_feature_added(layer, featureid)

    def layer_feature_added(self, layer, featureid):
        if not self.viewer:
            return

        feature = layer.getFeatures(QgsFeatureRequest(featureid)).next()
        renderer = layer.rendererV2()
        transform = self.coordinatetransform(layer)
        featuredata = to_feature_data(layer.id(), feature, renderer, transform)
        geomtype = layer.geometryType()
        layerdata = dict(id=layer.id(),
                         geomtype=QGis.vectorGeometryType(geomtype))
        self.viewer.load_features(layerdata, featuredata)

    def _layer_feature_delete(self, featureid):
        layer = self.sender()
        if not layer:
            return
        self.layer_feature_delete(layer, featureid)

    def layer_feature_delete(self, layer, featureid):
        if not self.viewer:
            return

        self.viewer.remove_feature(layer.id(), featureid)

    def _layer_geometry_changed(self, featureid, geometry):
        layer = self.sender()
        if not layer:
            return
        self.layer_geometry_changed(layer, featureid, geometry)

    def layer_geometry_changed(self, layer, featureid, geometry):
        if not self.viewer:
            return

        geomtype = layer.geometryType()
        if geomtype == QGis.Point:
            geom = geometry.asPoint()
            transform = self.coordinatetransform(layer)
            point = transform.transform(geom, QgsCoordinateTransform.ReverseTransform)
            location = dict(lat=point.y(), lng=point.x())
            self.viewer.edit_feature(layer.id(), featureid, [location])
        elif geomtype == QGis.Line:
            self.layer_feature_delete(layer, featureid)
            self.layer_feature_added(layer, featureid)

    def connect_layer_signals(self, layer):
        if not layer.type() == QgsMapLayer.VectorLayer:
            return

        layer.featureAdded.connect(self._layer_feature_added)
        layer.featureDeleted.connect(self._layer_feature_delete)
        layer.editingStarted.connect(self.layer_editstate_changed)
        layer.editingStopped.connect(self.layer_editstate_changed)
        # HACK The new style doesn't work here
        # http://hub.qgis.org/issues/6573
        signal = SIGNAL("geometryChanged(QgsFeatureId, QgsGeometry&)")
        self.connect(layer, signal, self._layer_geometry_changed)
        self.load_layer_features(layers=[layer])

    def layer_editstate_changed(self):
        layer = self.sender()
        if layer == self.iface.activeLayer():
            self.viewer.layer_changed(layer)

    def disconnect_signals(self):
        self.disconnect_projectsignals()

        for layer in maplayers():
            if not layer.type() == QgsMapLayer.VectorLayer:
                return

            safe_disconnect(layer.featureAdded, self._layer_feature_added)
            safe_disconnect(layer.featureDeleted, self._layer_feature_delete)
            safe_disconnect(layer.editingStarted, self.layer_editstate_changed)
            safe_disconnect(layer.editingStopped, self.layer_editstate_changed)
            # HACK The new style doesn't work here
            # http://hub.qgis.org/issues/6573
            signal = SIGNAL("geometryChanged(QgsFeatureId, QgsGeometry&)")
            self.disconnect(layer, signal, self._layer_geometry_changed)

    def connect_signals(self):
        for layer in maplayers():
            self.connect_layer_signals(layer)

        self.center_on_canvas()

    def set_viewer_location(self, point, mousebutton):
        transform = self.coordinatetransform()
        point = transform.transform(point, QgsCoordinateTransform.ReverseTransform)
        self.viewer.set_location(point)

    def distancearea(self):
        area = QgsDistanceArea()
        dest = self.canvas.mapRenderer().destinationCrs()
        area.setSourceCrs(dest)
        return area, dest.mapUnits()

    def coordinatetransform(self, layer=None):
        """
        Return the transform for WGS84 -> QGIS projection.
        """
        source = QgsCoordinateReferenceSystem()
        source.createFromWkt(
            'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')
        if not layer:
            dest = self.canvas.mapRenderer().destinationCrs()
        else:
            dest = layer.crs()
        transform = QgsCoordinateTransform(source, dest)
        return transform

    def earthmine_settings(self):
        settings = {}
        with settinggroup(self.settings, "plugins/Earthmine"):
            for key in ['serviceUrl', 'baseDataUrl', "apiKey", 'secretKey', 'viewerUrl']:
                if not self.settings.contains(key):
                    raise EarthmineSettingsError("{} not set".format(key))

                value = self.settings.value(key, type=str)
                if value is None:
                    raise EarthmineSettingsError("{} not set".format(key))

                settings[key] = value

        return settings

    @pyqtSlot()
    def ready(self):
        """
        Called when the viewer is ready to be started.  At this point the viewer hasn't been loaded
        so no other methods apart from startViewer will be handled.
        """
        settings = self.earthmine_settings()
        self.viewer.startViewer(settings)

    @pyqtSlot()
    def viewerReady(self):
        """
        Called once the viewer is loaded and ready to get location events.
        """
        self.disconnect_signals()
        self.connect_signals()
        self.iface.projectRead.connect(self.connect_signals)
        self.canvas.layersChanged.connect(self.layers_changed)
        self.canvas.selectionChanged.connect(self.selection_changed)
        self.canvas.selectionChanged.connect(self.viewer.selection_changed)
        QgsMapLayerRegistry.instance().layersRemoved.connect(self.layers_removed)
        QgsMapLayerRegistry.instance().layerWasAdded.connect(self.connect_layer_signals)
        self.center_on_canvas()
        self.viewer.activelayercombo.setLayer(self.iface.activeLayer())

    def center_on_canvas(self):
        point = self.canvas.extent().center()
        transform = self.coordinatetransform()
        point = transform.transform(point, QgsCoordinateTransform.ReverseTransform)
        self.viewer.set_location(point)
        self.viewer.infoaction.toggle()

    def selection_changed(self, layer):
        ids = [feature.id() for feature in layer.selectedFeatures()]
        if not ids:
            self.viewer.clear_selection(layer.id())
        else:
            self.viewer.set_selection(layer.id(), ids)

    def layers_changed(self):
        layerstates = self.layers_with_states()
        for layer, visible in layerstates:
            layerid = layer.id()
            viewerloaded = self.viewer.layer_loaded(layerid)
            QgsMessageLog.instance().logMessage(layerid, "Earthmine")
            QgsMessageLog.instance().logMessage("Viewer State:" + str(viewerloaded), "Earthmine")
            QgsMessageLog.instance().logMessage("QGIS State:" + str(visible), "Earthmine")
            if (viewerloaded and visible) or (not viewerloaded and not visible):
                QgsMessageLog.instance().logMessage("Ignoring as states match", "Earthmine")
                continue

            if viewerloaded and not visible:
                QgsMessageLog.instance().logMessage("Clearing layer because viewer loaded and disabled in QGIS",
                                                    "Earthmine")
                self.viewer.clear_layer_features(layerid)
                continue

            if not viewerloaded and visible:
                QgsMessageLog.instance().logMessage("Loading layer", "Earthmine")
                self.load_layer_features(layers=[layer])
                continue

    def layers_removed(self, layers):
        for layerid in layers:
            self.viewer.clear_layer_features(layerid)

    @pyqtSlot(str, float, float)
    def viewChanged(self, event, yaw, angle):
        self.marker.setAngle(angle)
        self.marker.setYaw(yaw)

    @pyqtSlot(str, str)
    def getInfo(self, layerid, featureid):
        featureid = int(featureid)
        activelayer = self.iface.activeLayer()
        if not activelayer:
            return

        activetool = self.viewer.active_tool()
        if not activetool in ["Info", "Select"]:
            return

        # Only show information for the active layer
        if not layerid == activelayer.id():
            return

        layer = layer_by_id(layerid)
        if activetool == "Select":
            layer.setSelectedFeatures([featureid])
        elif activetool == "Info":
            rq = QgsFeatureRequest(featureid)
            feature = layer.getFeatures(rq).next()
            dlg = get_feature_form(layer, feature)
            if dlg.dialog().exec_():
                self.canvas.refresh()

    @pyqtSlot(str, str, float, float, bool)
    def featureMoved(self, layerid, featureid, lat, lng, end):
        layer = layer_by_id(layerid)
        transform = self.coordinatetransform(layer)
        point = transform.transform(lng, lat)
        if not end:
            self.movingband.show()
            self.movingband.setToGeometry(QgsGeometry.fromPoint(point), layer)
            self.movingband.updatePosition()
            self.movingband.update()
        else:
            self.movingband.hide()
            feature = feature_by_id(layer, featureid)
            startpoint = feature.geometry().asPoint()
            dx = point.x() - startpoint.x()
            dy = point.y() - startpoint.y()
            layer.beginEditCommand("Feature Moved")
            # Block signals for this move as the geometry changed signal will re add the geometry on use.
            layer.blockSignals(True)
            layer.translateFeature(feature.id(), dx, dy)
            layer.blockSignals(False)
            self.canvas.refresh()
            layer.endEditCommand()

    @pyqtSlot(str, str)
    def onError(self, message, stacktrace=None):
        self.iface.messageBar().pushMessage("Earthmine", message, QgsMessageBar.WARNING)
        QgsMessageLog.logMessage(stacktrace, "Earthmine")

    @pyqtSlot(float, float, float)
    def addPoint(self, lat, lng, z):
        layer = self.viewer.active_layer
        if not layer.isEditable():
            self.iface.messageBar().pushMessage("Earthmine",
                                                "Selected layer isn't editable. Please enable edit mode to add features",
                                                duration=3, level=QgsMessageBar.WARNING)
            return

        transform = self.coordinatetransform(layer)
        point = transform.transform(lng, lat)
        geom = QgsGeometry.fromPoint(point)
        self.add_feature(layer, geom, z)

    def add_feature(self, layer, geom, z=None):
        feature = QgsFeature(layer.pendingFields())
        if z and self.viewer.copyZvalue:
            try:
                feature['Z'] = z
            except KeyError:
                QgsMessageLog.log("No Z found on layer {}".format(layer.name()))
                pass

        feature.setGeometry(geom)
        dlg = get_feature_form(layer, feature, isadd=True)
        if dlg.dialog().exec_():
            self.canvas.refresh()


    @pyqtSlot(str, bool, str)
    def drawLine(self, points, end, stats):
        points = json.loads(points)
        stats = json.loads(stats)
        QgsMessageLog.logMessage(str(stats), "Earthmine")
        self.tempband.reset(QGis.Line)
        self.tempbandpoints.reset(QGis.Point)
        color = QColor(self.viewer.current_action_color)
        self.tempband.setColor(color)
        self.tempbandpoints.setColor(color)

        layer = self.viewer.active_layer
        transform = self.coordinatetransform(layer)
        earthminepoints = []
        for point in points:
            newpoint = transform.transform(point['lng'], point['lat'])
            self.tempband.addPoint(newpoint)
            self.tempbandpoints.addPoint(newpoint)
            empoint = EarthminePoint(newpoint, point)
            earthminepoints.append(empoint)

        if end and not self.viewer.mode == "Vertical":
            geom = self.tempband.asGeometry()
            self.add_feature(layer, geom)
            self.clear_bands()

        self.viewer.geom = EarthmineLine(earthminepoints, stats)

        self.tempband.show()
        self.tempbandpoints.show()

    @pyqtSlot(str, str, str, float)
    def locationChanged(self, lat, lng, yaw, angle):
        transform = self.coordinatetransform()
        point = transform.transform(float(lng), float(lat))
        self.marker.setCenter(point)
        yaw = float(yaw)
        self.marker.setAngle(angle)
        self.marker.setYaw(yaw)
        self.marker.setTracking(self.viewer.tracking)

        if self.marker.tracking:
            rect = QgsRectangle(point, point)
            extentlimt = QgsRectangle(self.canvas.extent())
            extentlimt.scale(0.95)

            if not extentlimt.contains(point):
                self.canvas.setExtent(rect)
                self.canvas.refresh()

        # Clear old features
        self.viewer.clear_features()
        self.load_layer_features(point)

    def update_earthmine_features(self, viewfeatures):
        self.viewer.clear_features()

        if viewfeatures:
            self.load_layer_features()

    def load_layer_features(self, point=None, layers=None):

        # TODO Move this logic into the viewer and let it track it's position
        if point is None and self.marker.map_pos is None:
            return

        if point is None:
            point = self.marker.map_pos

        area, units = self.distancearea()
        rect = search_area(units, area, point)

        if layers is None:
            layers = self.visible_layers()

        for layer in layers:
            transform = self.coordinatetransform(layer)
            # Transform the rect
            source = self.canvas.mapRenderer().destinationCrs()
            dest = layer.crs()
            recttransform = QgsCoordinateTransform(source, dest)
            rect = recttransform.transformBoundingBox(rect)
            features = list(get_features_in_area(layer, rect, transform, self.canvas.mapSettings()))
            geomtype = layer.geometryType()
            layerdata = dict(id=layer.id(),
                             geomtype=QGis.vectorGeometryType(geomtype))
            self.viewer.load_features(layerdata, features)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('EarthMineQGIS', message)

    def add_action(
            self,
            icon_path,
            text,
            callback,
            enabled_flag=True,
            add_to_menu=True,
            add_to_toolbar=True,
            status_tip=None,
            whats_this=None,
            parent=None):
        """Add a toolbar icon to the InaSAFE toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to s, "Earhtmine"how in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def open_viewer(self):
        """Run method that performs all the real work"""
        try:
            settings = self.earthmine_settings()
        except EarthmineSettingsError as ex:
            self.onError(ex.message)
            self.show_settings()
            return

        url = settings["viewerUrl"]
        if not url.startswith("http"):
            url = url.replace("\\\\", "\\")
            url = QUrl.fromLocalFile(url)
        else:
            url = QUrl(url)

        if not self.viewer.isVisible():
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.viewer)

        self.viewer.loadviewer(url)

    def show_settings(self):
        self.settingsdialog.show()


class PostionMarker(QgsMapCanvasItem):
    """
    Position marker for the current location in the viewer.
    """

    def __init__(self, canvas):
        self._yaw = 0
        self._angle = 0
        self.size = 8
        self.halfsize = self.size / 2.0
        super(PostionMarker, self).__init__(canvas)

        self.canvas = canvas
        colorvalue = "#019633"
        colour = QColor(colorvalue)
        colour.setAlpha(50)
        self.conebrush = QBrush(colour)
        pencolour = QColor(colorvalue)
        self.pointpen = QPen(pencolour, 1)
        self.solidbrush = QBrush(pencolour)
        self.map_pos = QgsPoint()
        self.tracking = False

    def setAngle(self, angle):
        self._angle = angle
        self.update()

    def setSize(self, size):
        self.size = size
        self.halfsize = self.size / 2.0
        self.update()

    def setYaw(self, yaw):
        self._yaw = yaw
        self.update()

    def paint(self, painter, xxx, xxx2):
        if not self.tracking:
            return

        halfanlge = self._angle / 2

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.solidbrush)
        painter.setPen(self.pointpen)
        painter.rotate(-90 + self._yaw)
        painter.drawEllipse(QPointF(0, 0), self.size, self.size)
        painter.setBrush(self.conebrush)
        painter.drawPie(self.boundingRect(), halfanlge * 16, -self._angle * 16)
        # painter.drawRect(self.boundingRect())
        painter.restore()

    def distancearea(self):
        area = QgsDistanceArea()
        dest = self.canvas.mapRenderer().destinationCrs()
        area.setSourceCrs(dest)
        return area, dest.mapUnits()

    def boundingRect(self):
        distance = 15
        area, units = self.distancearea()
        distance = area.convertMeasurement(distance, QGis.Meters, units, False)
        s = self.toCanvasCoordinates(QgsPoint(0, 0))
        e = self.toCanvasCoordinates(QgsPoint(0, distance[0]))
        length = s.y() - e.y()
        half = length / 2
        bounding = QRectF(-half * 2.0, -half * 2.0, 2.0 * length, 2.0 * length)
        return bounding

    def setCenter(self, map_pos):
        self.map_pos = map_pos
        self.setPos(self.toCanvasCoordinates(map_pos))

    def updatePosition(self):
        self.setCenter(self.map_pos)
        self.setVisible(self.tracking)

    def setTracking(self, tracking):
        self.tracking = tracking
        self.setVisible(tracking)
