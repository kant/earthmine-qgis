from PyQt4.QtGui import QPixmap
from PyQt4.QtCore import QSettings
from PyQt4 import uic

import resources_rc

import utils

FORM_CLASS, FORM_BASE = uic.loadUiType(utils.resolve('settingsdialog.ui'))

class SettingsDialog(FORM_BASE, FORM_CLASS):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setupUi(self)
        self.settings = QSettings()

    def value(self, key, type=str):
        try:
            return self.settings.value(key, type=type)
        except TypeError:
            return None

    def showEvent(self, event):
        serviceUrl = self.value("plugins/Earthmine/serviceUrl")
        baseDataUrl = self.value("plugins/Earthmine/baseDataUrl", type=str)
        apiKey = self.value("plugins/Earthmine/apiKey", type=str)
        secretKey = self.value("plugins/Earthmine/secretKey", type=str)
        viewerUrl = self.value("plugins/Earthmine/viewerUrl", type=str)
        if not viewerUrl:
            viewerUrl = 'http://qgis.mapsolutions.com.au/qgis/earthmine/view.html'

        self.serviceUrlLineEdit.setText(serviceUrl)
        self.baseDataURLLineEdit.setText(baseDataUrl)
        self.apiKeyLineEdit.setText(apiKey)
        self.secretKeyLineEdit.setText(secretKey)
        self.viewerUrlEdit.setText(viewerUrl)

    def accept(self):
        self.settings.setValue("plugins/Earthmine/serviceUrl", self.serviceUrlLineEdit.text())
        self.settings.setValue("plugins/Earthmine/baseDataUrl", self.baseDataURLLineEdit.text())
        self.settings.setValue("plugins/Earthmine/apiKey", self.apiKeyLineEdit.text())
        self.settings.setValue("plugins/Earthmine/secretKey", self.secretKeyLineEdit.text())
        self.settings.setValue("plugins/Earthmine/viewerUrl", self.viewerUrlEdit.text())
        super(SettingsDialog, self).accept()

