"""AKShare Eastmoney-family fallback adapter."""
from .legacy import RunnerProvider, ak_runner


class AkProvider(RunnerProvider):
    def __init__(self):
        super().__init__("akshare_eastmoney", "eastmoney_family", ak_runner)
