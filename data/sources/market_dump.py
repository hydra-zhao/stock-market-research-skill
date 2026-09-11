"""market_dump.py — 全市场日K底座（公开演示版 stub）。

生产版：fuyao 全市场日K整包（约180MB parquet）落盘 data/cache/，
为持仓行情叠加、形态匹配、前向收益回填提供零配额本地底座。该实现
与其缓存格式属于生产环境配置，不在公开版提供。

公开版契约：`frame()` 恒返回 None —— 调用方（quick_context._holding_quotes）
按"底座不可用 → 全部 unverified"的原生降级路径处理，绝不阻断交付链。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class DumpUnavailable(RuntimeError):
    """日K底座不可用（公开版恒抛此语义：无本地底座）。"""


def ensure(*, force: bool = False, now=None):
    """生产版负责整包下载/节流；公开版直接抛 DumpUnavailable。"""
    raise DumpUnavailable("public edition: 全市场日K底座不随公开仓库分发")


def frame(codes=None, *, now=None, **_):
    """返回 None = 底座不可用，调用方走原生 unverified 降级。"""
    return None
