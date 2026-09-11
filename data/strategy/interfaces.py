"""决策层接口（Protocol）—— 生产策略实现的形状契约。

数据管道（采集 → 归一化 → 渲染 → 交付）与策略判定在这里解耦：
管道代码只依赖本文件定义的接口，策略可以整体替换而不触碰管道。
生产仓库中的实现（私有）与本仓库中的示例实现（example_strategy）
都满足同一组 Protocol。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RegimeVerdict:
    """市场生态判定结果（对齐 quick_context 的 canonical 事实字段）。"""

    data_date: str                      # 数据归属日 YYYY-MM-DD
    eco: str                            # 生态文案（含状态词，如 "混沌/主升/退潮…"）
    intraday: bool                      # 是否盘中时段判定
    limit_up: int | None = None         # 涨停家数
    limit_down: int | None = None       # 跌停家数
    bomb: int | None = None             # 炸板家数
    bomb_rate: float | None = None      # 炸板率 %
    max_ladder: int | None = None       # 最高连板高度
    sh_close: float | None = None       # 上证收盘
    sh_chg: float | None = None         # 上证涨跌幅 %
    action: str = "观望"                 # 判定动作文案
    can_trade_if: str = ""              # 附加条件说明
    # 四位裁决者输出（生产版为四套独立体系；示例版为占位）
    judges: dict[str, dict] = field(default_factory=dict)


@dataclass
class StockScore:
    """个股评分结果。"""

    code: str
    name: str
    score: float
    tier: str                            # A / B / C / 观察
    reasons: list[str] = field(default_factory=list)


@dataclass
class RiskVerdict:
    """风险闸结论：🟢 通过 / 🟠 需核实降档 / 🔴 一票否决。"""

    code: str
    level: str                           # "green" | "amber" | "red"
    flags: list[str] = field(default_factory=list)


@runtime_checkable
class MarketRegimeJudge(Protocol):
    """市场生态判定：从归一化的市场事实输出判定结论。"""

    def evaluate(self, facts: dict, now=None) -> RegimeVerdict: ...


@runtime_checkable
class StockScorer(Protocol):
    """个股打分：从个股行情/技术事实输出分层评分。"""

    def score(self, code: str, name: str, facts: dict) -> StockScore: ...


@runtime_checkable
class RiskGate(Protocol):
    """风险闸：fail-closed，数据缺失按不通过处理。"""

    def check(self, code: str, facts: dict) -> RiskVerdict: ...
