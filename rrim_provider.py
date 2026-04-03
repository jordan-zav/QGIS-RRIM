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
