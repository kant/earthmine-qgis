import flash.events.*;
import mx.events.*;
import flash.geom.Point;
import flash.display.Shape;

import com.earthmine.controls.*;
import com.earthmine.overlays.*;
import com.earthmine.viewer.*;

import com.earthmine.erc.view.papervision.*;

import mx.controls.Alert;
import mx.effects.Move;

import flashx.textLayout.formats.Float;

public var example_viewer:Viewer;
private var taglookup:Dictionary = new Dictionary();
private var selection:Dictionary = new Dictionary();
private var layeroverlays:Dictionary = new Dictionary();
private var line:Shape;
private var point1:Point;
private var color:Number = 0x00ff00;
private var capturing:Boolean = false;
private var drawing:Boolean = false;
private var currentAction:Object;
private var currentCaptureArray:Array = new Array();
private var currentCaptureLine:Polyline;

[Embed("viewermarker.svg")]
public var markericon:Class;

public function onComplete():void
{
    Security.allowDomain("*");
    try {
        ExternalInterface.addCallback("startViewer", startViewer);
    }
    catch (error:Error) {
        Alert.show(error.message);
    }
    line = new Shape();
    point1 = new Point();

    example_viewer = new Viewer(new ViewerOptions({cursorDisabled:true}));
    viewer_container.addChild(example_viewer);
    viewer_container.addChild(line);

    this.qgis("ready");
}

private function uncaughtErrorHandler(event:UncaughtErrorEvent):void
{
    event.preventDefault();
    var message:String;

    if (event.error is Error)
    {
     message = Error(event.error).message;
    }
    else if (event.error is ErrorEvent)
    {
     message = ErrorEvent(event.error).text;
    }
    else
    {
     message = event.error.toString();
    }
    this.raiseError(event.error);
}

private function startViewer(settings:Object):void
{
    example_viewer.addEventListener(ViewerEvent.VIEWER_READY, onViewerReady);

    example_viewer.serviceUrl = settings.serviceUrl;
    example_viewer.tileUrl = settings.baseDataUrl;
    example_viewer.apiKey = settings.apiKey;
    example_viewer.secretKey = settings.secretKey;

    //Add an event listener that is called when the viewer has initialized
    example_viewer.addEventListener(ViewerEvent.START_PANORAMA_LOADING, onLocationReady);
    example_viewer.addEventListener(ViewerMoveEvent.MOVE_STEP, onViewMoveEnd);
    example_viewer.addEventListener(ViewerMoveEvent.MOVE_START, onViewMoveStart);
    example_viewer.addEventListener(ViewerMouseEvent.CLICK, onViewerClick);
    example_viewer.addEventListener(ViewerMouseEvent.DOUBLE_CLICK, onViewerDoubleClick);
    example_viewer.addEventListener(ViewerZoomEvent.ZOOM_CHANGED, onViewerZoomChanged);

    viewer_container.addEventListener(ResizeEvent.RESIZE, onControlResize)
    viewer_container.addEventListener(MouseEvent.MOUSE_MOVE, mouseUpdate);
    viewer_container.addEventListener(MouseEvent.CLICK, placePoint);

    loaderInfo.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, uncaughtErrorHandler);
}

private function qgis(...args):*
{
    try {
        args[0] = "qgis." + args[0];
        switch (args[0]){
            case "qgis.drawLine":
                args[1] = JSON.stringify(args[1])
                args[3] = JSON.stringify(args[3])
                break;
            case "qgis.addPoint":
                var location:Location = args[1]
                args[1] = location.lat;
                args[2] = location.lng;
                args[3] = location.alt;
        }
        ExternalInterface.call.apply(ExternalInterface.call, args);
    }
    catch (error:Error) {
        this.raiseError(error)
    }
}

private function raiseError(error:Error):void
{
    this.qgis("onError", error.message, error.getStackTrace());
}

private function mouseUpdate(evt:MouseEvent):void
{
    try
    {
        if (drawing){

            if ( currentAction != null ) {
                color = currentAction.color;
            }

            line.graphics.clear();
            line.graphics.lineStyle(10, color, .50);
            line.graphics.moveTo(point1.x, point1.y);
            line.graphics.lineTo(viewer_container.mouseX, viewer_container.mouseY);
        }
        evt.updateAfterEvent();
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function placePoint(evt:MouseEvent):void
{
    try
    {
        point1.x = evt.stageX;
        point1.y = evt.stageY;
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function onControlResize(event:ResizeEvent):void
{
    var size:Point = new Point(viewer_container.width, viewer_container.height);
    example_viewer.setSize(size);
}

private function isActionEditTool():Boolean
{
    if ( currentAction == null ) {
        return false;
    }
    var actiontype:String = currentAction.action;
    switch (actiontype.toLowerCase()) {
        case "info":
        case "select":
        case "move":
            return false;
        default:
            return true;
    }
}

private function hasAction():Boolean
{
    return currentAction != null;
}

private function validLocation(location:Location):Boolean
{
    return location != null;
}

private function onViewerDoubleClick(event:ViewerMouseEvent):void
{
    var location:Location = event.viewLocation;
    if (!this.validLocation(location)) {
        return
    };

    try
    {
        if (!this.isActionEditTool()) {
            example_viewer.setSubjectLocation(location);
            return;
        }

        var actiontype:String = currentAction.action;
        var actiondata:Object = currentAction.actiondata;
        if (currentCaptureLine != null) {
            var stats:Object = polylineStats(this.currentCaptureArray, actiondata.mode);
            var isadd:Boolean = actiontype.toLowerCase() == "add";
            this.qgis("drawLine", this.currentCaptureArray, isadd, stats);
            if (!isadd) {
                this.qgis("measuringStatus", false)
            }
            this.clearLine(!isadd);
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }

}

private function createCaptureLine(location:Location, color:Number=0x00ff00):Array
{
    try
    {
        // Clear the old temp line
        if (!this.drawing) {
            this.clearLine();
        }

        if (currentCaptureLine == null){
            var currentCaptureLineOptions:PolylineOptions = new PolylineOptions({ weight: 10.0, color: color, allowOccluded: true});
            currentCaptureArray = new Array();
            currentCaptureLine = new Polyline(new Array(), currentCaptureLineOptions);
            example_viewer.addOverlay(currentCaptureLine);
        }

        var actiondata:Object = this.currentAction.actiondata;
        switch (actiondata.mode) {
            case "Horizontal":
                // Adjust to have no height
                location = new Location(location.lat, location.lng);
                break;
            case "Vertical":
                // The last point is really the first point with a adjusted height value only
                if (this.currentCaptureArray.length != 1 ){
                    break;
                }

                var start:Location = this.currentCaptureArray[0];
                var height:Number = location.alt - start.alt;
                var newheight:Number = start.alt + height;
                location = new Location(start.lat, start.lng, newheight);
                break;
            }

        currentCaptureArray.push(location);
        currentCaptureLine.addVertex(location);
        this.drawing = true;
    }
    catch (error:Error) {
        this.raiseError(error);
    }
    return this.currentCaptureArray;
}

private function clearLine(keepline:Boolean = false):void
{
    if (currentCaptureLine != null && !keepline) {
        example_viewer.removeOverlay(currentCaptureLine);
        this.currentCaptureArray = new Array();
        this.currentCaptureLine = null;
    }
    this.line.graphics.clear();
    this.drawing = false;
    this.capturing = false;
}

private function editFeature(layerid:String, featureid:String, nodes:Array):void
{
    // Editing a point layer
    if (nodes.length == 1){
        var point:Object = nodes[0];
        var location:Location = new Location(point.lat, point.lng);
        // Get the tag for this feature
        var tags:Array = this.layeroverlays[layerid];
        for each (var tag:Tag in tags){
            var feature:Object = this.taglookup[tag];
            if (feature.id == featureid){
                tag.setLocation(location);
                return;
            }
        }
    }
}

private function polylineStats(points:Array, mode:String):Object
{
    var stats:Object = new Object();
    stats['2D-Total'] = 0;
    stats['3D-Total'] = 0;
    stats['height'] = 0;
    stats['2D'] = 0;
    stats['3D'] = 0;
    try
    {
        if (points.length < 2 ) {
            return stats;
        }

        for (var i:int = 0; i<points.length; i++) {
            var p1:Location = points[i];
            var p2:Location = points[i+1]
            if (p2 == null) {
                break;
            }
            var height:Number = p1.alt - p2.alt;
            var length:Number = GeoMath.distance(p1, p2);
            stats['height'] = height
            stats['2D'] = GeoMath.vincentyDistance(p1, p2);
            stats['3D'] = length
            stats['2D-Total'] += stats['2D']
            stats['3D-Total'] += stats['3D']
        }
        return stats
    }
    catch (error:Error) {
        this.raiseError(error);
    }
    return stats;
}

private function onViewerClick(event:ViewerMouseEvent):void
{
    try
    {
        var location:Location = event.viewLocation;
        if (location == null){
            // Might happen if you click in the sky
            return;
        }
        var points:Array;

        if ( currentAction == null ) {
            return
        }
        var actiontype:String = currentAction.action;
        var actiondata:Object = currentAction.actiondata;

        var stats:Object;
        if ( actiontype.toLowerCase() == "measure") {
            points = createCaptureLine(location, currentAction.color);
            stats = polylineStats(points, actiondata.mode);
            if ( actiondata.mode == "Vertical" && points.length == 2) {
                this.qgis("drawLine", points, true, stats);
                this.drawing = false;
                line.graphics.clear();
                return;
            }
            this.qgis("drawLine", points, false, stats);
            return
        }

        if ( actiontype.toLowerCase() == "add") {
            var geomtype:String = currentAction.geom;
            switch (geomtype) {
                case "Point":
                    this.qgis("addPoint", location);
                    break;
                case "Line":
                    points = createCaptureLine(location);
                    stats = polylineStats(points, actiondata.mode);
                    this.qgis("drawLine", points, false, stats);
                    this.drawing = true;
                    break;
                }
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function clearSelection(layerid:String):void
{
    for (var overlay:Object in selection) {
        var feature:Object = selection[overlay];
        if (feature.layerid == layerid ){
            this.updateOverlayColor(feature, overlay, feature.color);
            delete selection[overlay];
        }
    }
}

private function updateOverlayColor(feature:Object, overlay:Object, color:Number):void
{
        switch (feature.geomtype) {
            case "Point":
                var icon:DisplayObject = overlay.options.icon;
                var colorinfo:ColorTransform = icon.transform.colorTransform;
                colorinfo.color = color;
                icon.transform.colorTransform = colorinfo;
                selection[overlay] = feature;
                break;
            case "Line":
                var options:Object = overlay.options;
                options.color = color;
                overlay.setOptions(options);
                selection[overlay] = feature;
                break;
        }
}

private function setSelection(layerid:String, features:Object, clearlast:Boolean):void
{
    try
    {
        var overlays:Array = layeroverlays[layerid];
        log(overlays.length);
        var featureids:Array = features as Array;

        if (clearlast) {
            this.clearSelection(layerid);
        }

        for each (var overlay:Object in overlays) {
            var feature:Object = taglookup[overlay];
            if ( featureids.indexOf(feature.id) > -1 ){
                this.updateOverlayColor(feature, overlay, 0xffff00);
            }
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function onTagDrag(event:TagEvent):void
{
    try
    {
        var x:Number = viewer_container.mouseX;
        var y:Number = viewer_container.mouseY;
        var location:Location = example_viewer.getSubjectLocationFromPlaneData(x, y);
        var tag:Tag = event.tag;
        var feature:Object = taglookup[tag];
        this.qgis("featureMoved", feature.layerid, feature.id, location.lat, location.lng, false);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function onTagDragEnd(event:TagEvent):void
{
    try
    {
        var tag:Tag = event.tag;
        var location:Location = tag.location;
        var feature:Object = taglookup[tag];
        this.qgis("featureMoved", feature.layerid, feature.id, location.lat, location.lng, true);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function onTagClick(event:TagEvent):void
{
    try
    {
        var tag:Tag = event.tag;
        var feature:Object = taglookup[tag];
        this.qgis("getInfo", feature.layerid, feature.id);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function onPolylineClick(event:PolylineEvent):void
{
    try
    {
        var polyline:Polyline = event.polyline;
        var feature:Object = taglookup[polyline];
        this.qgis("getInfo", feature.layerid, feature.id);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function viewAngle():Number
{
    try {
        var camera:Object = example_viewer.getCamera3D();
        return camera.fov;
    }
    catch (error:Error) {
        this.raiseError(error);
    }
    return 0;
}

private function onViewerZoomChanged(event:ViewerZoomEvent):void
{
    this.qgis("viewChanged", "MOVE_END", example_viewer.getViewDirection().yaw, this.viewAngle());
}

private function onViewMoveEnd(event:ViewerMoveEvent):void
{
    this.qgis("viewChanged", "MOVE_END", event.viewDirection.yaw, this.viewAngle());
}

private function onViewMoveStart(event:ViewerMoveEvent):void
{
}

private function onLocationReady(event:ViewerEvent):void
{
    var location:Location = event.viewLocation;
    var direction:ViewDirection = example_viewer.getViewDirection();
    this.qgis("locationChanged", location.lat, location.lng, direction.yaw, this.viewAngle());
    drawCurrentCapture();
}

private function onViewerReady(event:ViewerEvent):void
{
    //Add the compass control
    var compass:CompassControl = new CompassControl();
    example_viewer.addControl(compass);

    var zoom:ZoomControl = new ZoomControl();
    example_viewer.addControl(zoom);

    try {
        ExternalInterface.addCallback("setLocation", setLocation);
        ExternalInterface.addCallback("loadFeatures", loadFeatures);
        ExternalInterface.addCallback("clearFeatures", clearFeatures);
        ExternalInterface.addCallback("updateAction", updateAction);
        ExternalInterface.addCallback("clearLayerObjects", clearLayerObjects);
        ExternalInterface.addCallback("layerLoaded", layerLoaded);
        ExternalInterface.addCallback("removeFeature", removeFeature);
        ExternalInterface.addCallback("clearLine", clearLine);
        ExternalInterface.addCallback("setSelection", setSelection);
        ExternalInterface.addCallback("clearSelection", clearSelection);
        ExternalInterface.addCallback("editFeature", editFeature);
    }
    catch (error:Error) {
        this.raiseError(error);
    }

    taglookup = new Dictionary();
    this.qgis("viewerReady");
}

private function setLayerMoveable(layerid:String, movable:Boolean = true):void
{
    try {
        layerloop: for (var layer:String in layeroverlays)
        {
            var overlays:Array = layeroverlays[layer]
            var enabled:Boolean = layer == layerid && movable;
            for each (var overlay:Object in overlays){
                if (getQualifiedClassName(overlay) != 'com.earthmine.overlays::Tag') {
                    continue layerloop;
                }

                var options:TagOptions = overlay.options;
                options.draggable = enabled;
                overlay.setOptions(options);
            }
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function updateAction(action:Object):void
{
    try {
        currentAction = action;
        var actiontype:String = currentAction.action;
        var options:ViewerOptions = new ViewerOptions({cursorDisabled:true});
        capturing = false
        if (actiontype.toLowerCase() == "add" || actiontype.toLowerCase() == "measure") {
            options.cursorDisabled = false;
            capturing = true
        }
        example_viewer.setOptions(options);

        if (actiontype.toLowerCase() == "move") {
            this.setLayerMoveable(currentAction.layer)
        }
        else {
            this.setLayerMoveable(currentAction.layer, false);
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function setLocationCallback(event:ViewerEvent):void {
    this.qgis("onError", "No coverage data found for this location", "");
}

private function setLocation(long:Number, lat:Number):void
{
    try {
        var location:Location = new Location(lat, long);
        example_viewer.setSubjectLocation(location, null, this.setLocationCallback);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function drawCurrentCapture():void
{
    if (currentCaptureLine != null){
        example_viewer.addOverlay(currentCaptureLine);
    }
}

private function clearFeatures():void
{
    example_viewer.clearOverlays()
    this.taglookup = new Dictionary();
    this.layeroverlays = new Dictionary();
    this.selection = new Dictionary();
    this.drawCurrentCapture();
}

private function layerLoaded(layerid:String):Boolean
{
    var tags:Array = layeroverlays[layerid];

    if (tags == null) {
        return false;
    }
    if (tags.length == 0) {
        return false;
    }
    return true;
}

private function log(message:Object):void
{
    ExternalInterface.call("console.log", message);
}
 private function removeFeature(layerid:String, featureid:Number):void
{
    try {
        var tags:Array = layeroverlays[layerid];
        if ( tags == null || tags.length == 0 ) {
            log("No tags found for " + layerid);
            return;
        }

        var len:int = tags.length - 1;
        for (var i:int = len; i >= 0; i--) {
            var tag:IOverlay = tags[i];
            var feature:Object = taglookup[tag];
            if (feature.id == featureid) {
                delete taglookup[tag];
                tags.splice(i, 1);
                delete selection[tag];
                example_viewer.removeOverlay(tag);
                layeroverlays[layerid] = tags;
                return;
            }
        }
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function clearLayerObjects(layerid:String):void
{
    try {
        var tags:Array = layeroverlays[layerid];
        if ( tags == null || tags.length == 0 ) {
            log("No tags found for " + layerid);
            return;
        }

        for (var i:int = 0; i<tags.length; i++) {
            var tag:IOverlay = tags[i]
            example_viewer.removeOverlay(tag);
        }
        layeroverlays[layerid] = new Array();
        log("Cleared layer" + layerid);
        log("New array created" + layerid);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}

private function loadFeatures(layer:Object, data:Object):void
{
    try {
        var layerid:String = layer.id;

        var features:Array = data as Array;
        var overlays:Array = new Array();
        var tags:Array = layeroverlays[layerid];

        if (tags == null) {
            log("Creating new tag entry for " + layerid)
            tags = new Array();
            layeroverlays[layerid] = tags;
        }

        var location:Location;
        var node:Object;
        var geomtype:String = layer.geomtype;
        for (var i:int = 0; i<features.length; i++) {
            var feature:Object = features[i];
            var nodes:Array = feature.nodes as Array;
            switch (geomtype) {
                case "Point":
                    // Point type
                    node = nodes[0];
                    if (node.z == 0){
                        location = new Location(node.lat, node.lng);
                    }
                    else {
                        location = new Location(node.lat, node.lng, node.z);
                    }
                    var icon:Sprite = new markericon();
                    var colorinfo:ColorTransform = icon.transform.colorTransform;
                    colorinfo.color = feature.color;
                    icon.transform.colorTransform = colorinfo;
                    var options:TagOptions = new TagOptions({icon: icon,
                                                             iconAnchor: new Point(-icon.width / 2, -icon.height),
                                                             scalable: true, clickable: true, allowOccluded: true});
                    var tag:Tag = new Tag(location, options);
                    tag.addEventListener(TagEvent.TAG_CLICK, onTagClick);
                    tag.addEventListener(TagEvent.TAG_DRAG, onTagDrag);
                    tag.addEventListener(TagEvent.TAG_DRAG_END, onTagDragEnd);
                    overlays.push(tag);
                    taglookup[tag] = feature;
                    tags.push(tag)
                    break;
                case "Line":
                    // Line string
                    var vertices:Array = new Array();
                    for (var n:int = 0; n<nodes.length; n++) {
                        node = nodes[n];
                        location = new Location(node.lat, node.lng);
                        vertices.push(location);
                    }
                    var poptions:PolylineOptions = new PolylineOptions({ weight: 4.0, color: feature.color, allowOccluded: true});
                    var polyline:Polyline = new Polyline(vertices, poptions);
                    polyline.addEventListener(PolylineEvent.POLYLINE_CLICK, onPolylineClick);
                    overlays.push(polyline);
                    taglookup[polyline] = feature;
                    tags.push(polyline)
                    break;
            }
        }
        example_viewer.addOverlays(overlays);
    }
    catch (error:Error) {
        this.raiseError(error);
    }
}
