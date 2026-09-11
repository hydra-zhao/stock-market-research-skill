"""THS DataAPI same-family compatibility adapter."""
from .legacy import RunnerProvider, ths_runner


class ThsProvider(RunnerProvider):
    def __init__(self):
        super().__init__("ths_dataapi", "ths_family", ths_runner)
