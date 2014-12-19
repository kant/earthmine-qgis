@ECHO OFF
SET BASE=%~dp0
pushd %~dp0qgisplugin
SET PATH=%PATH%;C:\OSGeo4W\bin
SET JAVA_HOME=C:\Program Files (x86)\Java\jre7
SET PATH=%BASE%flashsdk\bin;%PATH%
mkdir viewer
mxmlc -debug=true -library-path+=%BASE%flash_sdk_1.8.4\flash_sdk.swc -static-link-runtime-shared-libraries=true viewer.mxml -output viewer\viewer.swf
cp view.html viewer\view.html
cp viewer.js viewer\viewer.js
pyrcc4 -o earthmine\resources_rc.py earthmine\resources.qrc
pause
popd
