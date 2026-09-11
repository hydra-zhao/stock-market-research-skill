"""MX/Eastmoney independent-source adapter."""
from .legacy import RunnerProvider, mx_runner


class MxProvider(RunnerProvider):
    def __init__(self):
        super().__init__("mx", "eastmoney_family", mx_runner, key="MX_APIKEY")
