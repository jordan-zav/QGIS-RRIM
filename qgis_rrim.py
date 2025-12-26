from qgis.core import QgsApplication
from .rrim_provider import RRIMProvider


class QGISRRIM:
    """
    QGIS-RRIM Plugin Entry Point
    """

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        self.provider = RRIMProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
