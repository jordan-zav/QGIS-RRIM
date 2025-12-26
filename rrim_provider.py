from qgis.core import QgsProcessingProvider
from .rrim_algorithm import RRIMAlgorithm
from qgis.PyQt.QtGui import QIcon
import os


class RRIMProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(RRIMAlgorithm())

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
