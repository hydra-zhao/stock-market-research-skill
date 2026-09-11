"""review_hooks.py — 复盘收尾钩子骨架（公开演示版）。

生产版此模块编排五个收尾钩子（复盘锚定/状态核验/龙头拍板/趋势扫描/
自选整理），其中钩子内容含私有策略。公开版仅保留两个对交付链
（quick_context）可见的通用函数签名：

- next_trade_date: 仅跳周末的次一交易日启发式（通用日历逻辑，非策略）
- hooks_status:    钩子状态读取骨架（公开版恒返回空状态）

保持函数形状与生产版一致，使 quick_context / quick_delivery 零修改可跑。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def next_trade_date(date: str) -> str:
    """次一交易日（仅跳周末；法定节假日盲区由调用方显式提示）。"""
    dt = datetime.strptime(date, "%Y%m%d") + timedelta(days=1)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt.strftime("%Y%m%d")


def hooks_status(date: str, seats_dir: Path | None = None,
                 log_dir: Path | None = None) -> tuple[list, None]:
    """收尾钩子状态（演示版）：恒返回空钩子列表。

    生产版在此聚合五个钩子的落盘状态；公开版管道把"空钩子"作为合法
    终态渲染（fail-closed 语义与生产一致：缺失=未验证，不硬凑事实）。
    """
    return [], None
