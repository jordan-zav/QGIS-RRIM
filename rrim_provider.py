# Copyright (c) 2026 Jordan Zavaleta
# This file is part of QGIS-RRIM.
# QGIS-RRIM is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
import os

from .rrim_algorithm import RRIMGenerator
from .rrim_rgb_composer import RRIMRGBComposer


class RRIMProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(RRIMGenerator())
        self.addAlgorithm(RRIMRGBComposer())

    def id(self):
        return "qgis_rrim"

    def name(self):
        return "QGIS-RRIM"

    def longName(self):
        return "QGIS-RRIM"

    def icon(self):
        return QIcon(
            os.path.join(
                os.path.dirname(__file__),
                "icon.png"
            )
        )
