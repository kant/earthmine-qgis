# -*- coding: utf-8 -*-
"""
/***************************************************************************
 EarthMineQGIS
                                 A QGIS plugin
 Viewer for Earthmine
                             -------------------
        begin                : 2014-10-01
        copyright            : (C) 2014 by DMS Australia
        email                : support@mapsolutions.com.au
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load EarthMineQGIS class from file EarthMineQGIS.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .earthmine_qgis import EarthMineQGIS
    return EarthMineQGIS(iface)
