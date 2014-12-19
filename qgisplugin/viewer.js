function getmovie(movieName) {
    if ( navigator.appName == "Netscape" )
    {
        return document.getElementById(movieName)
    }

    var isIE = navigator.appName.indexOf("Microsoft") != -1;
    return (isIE) ? window[movieName] : document[movieName];
}

window.onerror = function(msg, url, line) {
    qgis.onError(msg);
}

window.onload = function(){
    earthmine = getmovie("earthmine");
}

