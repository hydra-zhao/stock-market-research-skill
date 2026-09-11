#!/usr/bin/env python3
"""round1_v2.py — 数据采集编排 CLI 入口（公开演示版）。

生产版：问财/妙想/同花顺/AKShare 多源并行采集编排器（quick/market/stock/
kline/pattern/tailscan/trend/swing/cycle 等子命令，约 2000 行，含生态判定
 `_quick_eval` 的完整规则实现 —— 私有，不在公开版提供）。

公开版保留两个东西：

1. `_quick_eval(raw, now)` 兼容函数 —— quick_context.build_context 依赖它
   把快照文本转成 canonical 判定事实。公开版委托给
   strategy.example_strategy.quick_eval_compat（示例实现，演示阈值）。
2. `python data/round1_v2.py demo` —— 生成合成市场快照并驱动
   FINAL-001 交付链（context → render → lint → manifest → verify），
   全程离线零网络，证明管道端到端可运行。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from strategy import example_strategy


def _quick_eval(raw: str, now: datetime | None = None) -> dict:
    """快照文本 → canonical 判定事实（公开版=示例实现委托）。"""
    return example_strategy.quick_eval_compat(raw, now=now)


def demo(out_dir: Path | None = None) -> int:
    """离线端到端演示：合成快照 → FINAL-001 交付链（进程内调用）。"""
    root = Path(__file__).resolve().parent.parent
    out_dir = out_dir or (root / "output" / "demo")
    out_dir.mkdir(parents=True, exist_ok=True)
    demo_dir = root / "demo"
    if not (demo_dir / "run_demo.py").exists():
        print("demo/run_demo.py 缺失", file=sys.stderr)
        return 2
    sys.path.insert(0, str(demo_dir))
    try:
        import run_demo
        return int(run_demo.main(["--out", str(out_dir)]))
    finally:
        sys.path.pop(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="round1_v2 (public edition)",
        description="公开演示版：真实采集子命令需配置数据源与生产仓库；"
                    "离线演示请用 `demo` 子命令。")
    parser.add_argument("command", nargs="?", default="demo",
                        choices=["demo"], help="demo=离线端到端演示")
    parser.add_argument("--out", default=None, help="demo 输出目录")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.command == "demo":
        return demo(Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
