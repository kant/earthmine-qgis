# -*- coding: utf-8 -*-
import os
import json
import functools

from PyQt4.QtWebKit import QWebView, QWebSettings
from PyQt4.QtCore import QUrl, Qt, QObject, pyqtSlot, pyqtSignal
from PyQt4.QtGui import QToolBar, QIcon, QWidget, QLabel, QSizePolicy, QActionGroup, QComboBox, QCheckBox
from PyQt4 import uic

from qgis.gui import QgsMapLayerComboBox, QgsMapLayerProxyModel
from qgis.core import QgsMapLayer, QGis, QgsGeometry, QgsDistanceArea

import resources_rc

import utils

ViewerClass, ViewerBase = uic.loadUiType(utils.resolve('viewer.ui'))
MeasureClas, MeasureBase = uic.loadUiType(utils.resolve('measure.ui'))


class EarthmineAPI(object):
    """
    Convenience class to allows calling JS methods as Python attributes.
    """
    def __init__(self, frame):
        """
        frame -- The QWebFrame to evel the JS in
        """
        self.frame = frame

    def __getattr__(self, item):
        return functools.partial(self._jscall, item)

    def _jscall(self, method, *args):
        def formatargs():
            for arg in args:
                if isinstance(arg, dict) or isinstance(arg, list):
                    arg = json.dumps(arg)
                elif isinstance(arg, basestring):
                    arg = '"{}"'.format(arg)
                elif isinstance(arg, bool):
                    arg = 'true' if arg else 'false'
                yield str(arg)

        argsformated = ",".join(formatargs()).lstrip(',')
        call = "earthmine.{method}({args});".format(method=method, args=argsformated)
        return self.frame.evaluateJavaScript(call)


class MeasureDialog(MeasureBase, MeasureClas):
    def __init__(self, parent=None):
        super(MeasureDialog, self).__init__(parent, Qt.Tool)
        self.setupUi(self)
        self.geom = None

        self.unitsCombo.currentIndexChanged.connect(self.update_geom_labels)
        self.modeCombo.currentIndexChanged.connect(self.update_geom_labels)

    @property
    def mode(self):
        return self.modeCombo.currentText()

    def update_geom_labels(self, *args):
        """
        Update the labels in the dialog based on the set geometry
        :param args:
        :return:
        """
        if self.geom:
            units = self.unitsCombo.currentIndex()
            mode = self.mode
            total, segment, slope = self.geom.stats(units, mode)
            self.total_label.setText(total)
            self.segment_label.setText(segment)
            if mode == "3D":
                self.slope_label.setText(slope)
            else:
                self.slope_label.setText('')


class Viewer(ViewerBase, ViewerClass):
    trackingChanged = pyqtSignal(bool)
    setLocationTriggered = pyqtSignal()
    updateFeatures = pyqtSignal(bool)
    layerChanged = pyqtSignal(QgsMapLayer)
    clearLine = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, callbackobject, parent=None):
        """Constructor."""
        super(Viewer, self).__init__(parent)
        self.setupUi(self)
        self.callbackobject = callbackobject
        self.frame = self.webview.page().mainFrame()
        self.actiongroup = QActionGroup(self)
        self.actiongroup.setExclusive(True)
        self.actiongroup.triggered.connect(self.action_triggered)

        self.measuredialog = MeasureDialog(self)

        self.toolbar = QToolBar()
        self.qgisTrackButton = self.toolbar.addAction("QGIS Track")
        self.qgisTrackButton.setIcon(QIcon(":/icons/track"))
        self.qgisTrackButton.setCheckable(True)
        self.qgisTrackButton.setChecked(True)
        self.qgisTrackButton.toggled.connect(self.trackingChanged.emit)

        self.setlocationaction = self.toolbar.addAction("Set location")
        self.setlocationaction.setIcon(QIcon(":/icons/location"))
        self.setlocationaction.triggered.connect(self.setLocationTriggered.emit)
        self.setlocationaction.setCheckable(True)

        self.viewfeatures = self.toolbar.addAction("Load QGIS Features")
        self.viewfeatures.setIcon(QIcon(":/icons/features"))
        self.viewfeatures.setCheckable(True)
        self.viewfeatures.setChecked(True)
        self.viewfeatures.toggled.connect(self.updateFeatures.emit)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.addWidget(spacer)

        self.measureaction = self.toolbar.addAction("measure")
        self.measureaction.setObjectName("Measure")
        self.measureaction.setIcon(QIcon(":/icons/measure"))
        self.measureaction.setCheckable(True)

        self.infoaction = self.toolbar.addAction("Info")
        self.infoaction.setObjectName("Info")
        self.infoaction.setIcon(QIcon(":/icons/info"))
        self.infoaction.setCheckable(True)

        self.selectaction = self.toolbar.addAction("Select")
        self.selectaction.setObjectName("Select")
        self.selectaction.setIcon(QIcon(":/icons/select"))
        self.selectaction.setCheckable(True)

        self.toolbar.addSeparator()

        self.deleteaction = self.toolbar.addAction("Delete")
        self.deleteaction.setIcon(QIcon(":/icons/delete"))
        self.deleteaction.triggered.connect(self.delete_selected)
        self.deleteaction.setEnabled(False)

        self.addaction = self.toolbar.addAction("Add")
        self.addaction.setObjectName("Add")
        self.addaction.setIcon(QIcon(":/icons/add"))
        self.addaction.setCheckable(True)

        self.moveaction = self.toolbar.addAction("Move")
        self.moveaction.setObjectName("Move")
        self.moveaction.setIcon(QIcon(":/icons/move"))
        self.moveaction.setCheckable(True)

        self.actiongroup.addAction(self.moveaction)
        self.actiongroup.addAction(self.addaction)
        self.actiongroup.addAction(self.infoaction)
        self.actiongroup.addAction(self.measureaction)
        self.actiongroup.addAction(self.selectaction)

        self.activelayercombo = QgsMapLayerComboBox()
        self.activelayercombo.layerChanged.connect(self.layer_changed)
        self.activelayeraction = self.toolbar.addWidget(self.activelayercombo)
        self.activelayercombo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.activelayercombo.currentIndexChanged.connect(self.index_changed)

        self.zvaluecheck = QCheckBox()
        self.zvaluecheck.setChecked(True)
        self.zvaluecheck.setText("Copy Z value")
        self.zvaluecheck.setToolTip("Copy Z value from viewer to new features in QGIS. Must have a field named Z to enable")
        self.zvalueaction = self.toolbar.addWidget(self.zvaluecheck)

        self.dockWidgetContents.layout().insertWidget(0, self.toolbar)

        self.webview.settings().setAttribute(QWebSettings.PluginsEnabled, True)
        self.webview.settings().setAttribute(QWebSettings.JavascriptEnabled, True)
        self.webview.settings().setAttribute(QWebSettings.DeveloperExtrasEnabled, True)
        self.frame.setScrollBarPolicy(Qt.Horizontal, Qt.ScrollBarAlwaysOff)
        self.frame.setScrollBarPolicy(Qt.Vertical, Qt.ScrollBarAlwaysOff)
        self.frame.javaScriptWindowObjectCleared.connect(self.addcallbackobject)
        self.measuredialog.modeCombo.currentIndexChanged.connect(self.action_triggered)
        self.measuredialog.clearButton.clicked.connect(self.clear_line)

        self.earthmine = EarthmineAPI(self.frame)

    def closeEvent(self, event):
        self.closed.emit()
        super(Viewer, self).closeEvent(event)

    def index_changed(self, index):
        if index == -1:
            self.set_button_states(False, False, False, False)

    def clear_line(self):
        self.clearLine.emit()
        self.earthmine.clearLine()

    @property
    def copyZvalue(self):
        layer = self.active_layer
        if not layer:
            return False

        if layer.type() == QgsMapLayer.VectorLayer and layer.geometryType() == QGis.Point:
            return self.zvaluecheck.isChecked()
        else:
            return False

    @property
    def geom(self):
        return self.measuredialog.geom

    @geom.setter
    def geom(self, value):
        self.measuredialog.geom = value
        self.measuredialog.update_geom_labels()

    @property
    def tracking(self):
        return self.qgisTrackButton.isChecked()

    @property
    def mode(self):
        return self.measuredialog.mode

    @property
    def active_layer(self):
        return self.activelayercombo.currentLayer()

    def layer_changed(self, layer):
        if not layer:
            self.set_button_states(False, False, False, False)
            return

        if layer.type() == QgsMapLayer.VectorLayer:
            enabledselecttools = layer.geometryType() in [QGis.Line, QGis.Point]
            enableedittools = layer.isEditable()
            enabledelete = layer.isEditable() and layer.selectedFeatureCount()
            enablemove = layer.geometryType() == QGis.Point and layer.isEditable()
        else:
            enabledselecttools = False
            enableedittools = False
            enabledelete = False
            enablemove = False

        self.set_button_states(enabledselecttools, enableedittools, enabledelete, enablemove)
        self.action_triggered()
        self.layerChanged.emit(layer)

    def selection_changed(self, layer):
        if layer == self.active_layer:
            enabledelete = layer.isEditable() and layer.selectedFeatureCount()
            self.deleteaction.setEnabled(enabledelete)

    def set_button_states(self, selecttools, edittools, deleteenabled, moveenabled):
        actions = [self.selectaction, self.infoaction]

        for action in actions:
            action.setEnabled(selecttools)

        editactions = [self.deleteaction, self.moveaction, self.addaction]

        for action in editactions:
            action.setEnabled(edittools)

        if edittools:
            self.deleteaction.setEnabled(deleteenabled)
            self.moveaction.setEnabled(moveenabled)

        for action in editactions:
            if action is self.actiongroup.checkedAction() and not action.isEnabled():
                self.infoaction.toggle()
                break

        layer = self.active_layer
        if not layer:
            enablez = False
        else:
            enablez = layer.type() == QgsMapLayer.VectorLayer and layer.geometryType() == QGis.Point
        self.zvalueaction.setEnabled(enablez)

    @property
    def current_action_color(self):
        action = self.actiongroup.checkedAction()
        color = int("0x00ff00", 16)
        if action == self.measureaction:
            if self.mode == "Vertical":
                color = int("0x0000ff", 16)

        return color

    def action_triggered(self, *args):
        action = self.actiongroup.checkedAction()
        layer = self.activelayercombo.currentLayer()

        self.clear_line()
        if not action:
            return

        if not action == self.measureaction and (not layer or not layer.type() == QgsMapLayer.VectorLayer):
            return

        color = self.current_action_color
        actiondata = {}

        if action == self.measureaction:
            self.measuredialog.show()
            actiondata['mode'] = self.mode
            geomtype = None
            layerid = None
        else:
            self.measuredialog.hide()
            geomtype = QGis.vectorGeometryType(layer.geometryType())
            layerid = layer.id()

        data = dict(action=action.objectName(),
                    layer=layerid,
                    geom=geomtype,
                    actiondata=actiondata,
                    color=color)

        self.earthmine.updateAction(data)

    def active_tool(self):
        action = self.actiongroup.checkedAction()
        if not action:
            return None
        return action.objectName()

    def update_current_layer(self, layer):
        self.activelayercombo.setLayer(layer)

    def addcallbackobject(self):
        self.frame.addToJavaScriptWindowObject("qgis", self.callbackobject)

    def loadviewer(self, url):
        self.webview.load(url)
        self.frame.addToJavaScriptWindowObject("qgis", self.callbackobject)

    def startViewer(self, settings):
        self.earthmine.startViewer(settings)

    def set_location(self, point):
        # # NOTE Set location takes WGS84 make sure you have transformed it first before sending
        self.earthmine.setLocation(point.x(), point.y())

    def clear_features(self):
        self.earthmine.clearFeatures()

    def clear_layer_features(self, layerid):
        self.earthmine.clearLayerObjects(layerid)

    def remove_feature(self, layerid, featureid):
        """
        :param features: A dict of layerid, id, lat, lng
        :return:
        """
        self.earthmine.removeFeature(layerid, featureid)

    def load_features(self, layerdata, features):
        """
        :param features: A dict of layerid, id, lat, lng
        :return:
        """
        self.earthmine.loadFeatures(layerdata, features)

    def layer_loaded(self, layerid):
        return self.earthmine.layerLoaded(layerid)

    def clear_selection(self, layerid):
        self.earthmine.clearSelection(layerid)

    def set_selection(self, layerid, featureids, clearlast=True):
        self.earthmine.setSelection(layerid, featureids, clearlast)

    def edit_feature(self, layerid, featureid, nodes):
        self.earthmine.editFeature(layerid, featureid, nodes)

    def delete_selected(self):
        layer = self.active_layer
        layer.deleteSelectedFeatures()

