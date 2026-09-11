#!/usr/bin/env python3
"""run_demo.py — 离线端到端演示（公开版）。

流程与生产完全同构，唯一区别是输入是**合成数据**（固定种子随机游走 +
虚构股票名），不需要任何 API key、私人数据或网络：

    合成市场事实 → 快照 markdown（生产同款分段格式）
      → quick_context.build_context   （canonical 事实归一化）
      → quick_renderer.render         （确定性渲染）
      → lint_review.lint_delivery     （结构 + 一致性 lint）
      → manifest（publishable 判定 + sha256）
      → verify_delivery               （交付前哈希复核）

用法：python demo/run_demo.py [--out 目录]
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))

DATA_DATE = "2026-09-11"          # 示例数据日（周五）
NOW = datetime(2026, 9, 11, 20, 5, 0, tzinfo=timezone(timedelta(hours=8)))


def _rng_name(rng: random.Random, i: int) -> str:
    return f"示例标的{i:02d}"


def build_snapshot() -> str:
    """合成一份与生产快照同构的 markdown（虚构代码/名称/数字）。"""
    # 固定种子=刻意为之：demo 输出必须逐字节可复现（非加密用途）
    rng = random.Random(20260911)
    limit_up = rng.randint(55, 95)
    bomb = rng.randint(8, 20)
    ladder = [
        (f"60{i:04d}", _rng_name(rng, i), boards)
        for i, boards in enumerate((6, 5, 4, 4, 3, 3, 3, 2, 2, 2, 2, 2), start=1)
    ]
    prev_ladder = [
        ("600001", "示例机械", 5, 10.02),
        ("600002", "示例软件", 4, -8.10),
        ("300003", "示例芯片", 3, 2.88),
        ("300004", "示例电力", 2, 6.15),
        ("600005", "示例重工", 2, -2.30),
    ]
    first_boards = [
        ("示例算力", 14, 5), ("示例新能源", 9, 2), ("示例医药", 6, 1), ("示例消费", 3, 0),
    ]
    fund_rows = [(f"示例板块{i}", round(rng.uniform(-8, 15), 2)) for i in range(1, 11)]
    swing_cands = [("600310", "示例电网"), ("600311", "示例轨交"), ("300312", "示例通信"),
                   ("600313", "示例化工"), ("300314", "示例电子")]
    swing_risk = [("600310", "🟢清洁"), ("600311", "🟢清洁"), ("300312", "🟡标注"),
                  ("600313", "🟠降档"), ("300314", "🟢清洁")]

    lines: list[str] = [
        "# A股快速复盘数据快照（公开版 DEMO · 全部为合成数据）",
        f"数据日期: {DATA_DATE}",
        "任务完成: 18/18",
        "",
        "--- [1/15] 涨停板 [demo] 合成样本 ---",
        f"涨停家数: {limit_up}",
        "",
        "| 代码 | 名称 | 涨停原因 |",
        "|---|---|---|",
    ]
    for i in range(1, 9):
        lines.append(f"| 30{i:04d} | {_rng_name(rng, i)} | 示例题材{i % 3} |")
    lines += ["", "--- [2/15] 跌停板 [demo] 合成样本 ---", "跌停家数: 3", ""]
    lines += [
        "--- [3/15] 炸板股 [demo] 合成样本 ---",
        f"炸板家数: {bomb}",
        "",
        "--- [4/15] 连板天梯 [demo] 合成样本 ---",
        "",
        "| 代码 | 名称 | 连板 |",
        "|---|---|---|",
    ]
    lines += [f"| {c} | {n} | {b} |" for c, n, b in ladder]
    lines += [
        "",
        "--- [5/15] 昨日涨停表现 [demo] 合成样本 ---",
        "",
        "| 代码 | 名称 | 涨跌幅[20260911] |",
        "|---|---|---|",
        "| 300021 | 示例标的21 | 4.10 |",
        "| 300022 | 示例标的22 | -1.20 |",
        "",
        "--- [6/15] 昨日连板表现 [demo] 合成样本 ---",
        "",
        "| 代码 | 名称 | 连续涨停天数[20260910] | 涨跌幅[20260911] |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c} | {n} | {b} | {chg:.2f} |" for c, n, b, chg in prev_ladder]
    lines += [
        "",
        "--- [7/15] 指数行情 [demo] 合成样本 ---",
        "上证指数 3821.44 涨跌幅: 0.82",
        f"上涨家数[20260911]**: {rng.randint(3600, 4600)}",
        f"下跌家数[20260911]**: {rng.randint(900, 1600)}",
        "",
        "--- [8/15] 历史成交额 [demo] 合成样本 ---",
        "",
        "| 2026-09-09 | 18234.5 |",
        "| 2026-09-10 | 19420.1 |",
        f"| {DATA_DATE} | 21503.8 |",
        "",
        "--- [9/15] 期指持仓 [demo] 合成样本 ---",
        "",
        f"**{DATA_DATE} 期指持仓变化（合成样本）**",
        "",
        "| 品种 | 净持仓 | 多chg | 空chg | 净多chg |",
        "|---|---|---|---|---|",
        "| IF合计 | 8210 | 120 | -80 | 200 |",
        "| IC合计 | -5600 | -40 | 210 | -250 |",
        "| 四品种合计 | -3120 | 90 | 300 | -210 |",
        "",
        "--- [10/15] 国家队ETF [demo] 合成样本 ---",
        "",
        "| 代码 | 份额变化(亿份) | 最新净值 |",
        "|---|---|---|",
        "| 510300 | +1.20 | 4.012 |",
        "| 510050 | -0.35 | 2.874 |",
        "",
        "--- [11/15] 板块资金 [demo] 合成样本 ---",
        "",
        "| 简称 | 主力净流入(亿) |",
        "|---|---|",
    ]
    lines += [f"| {name} | {v} |" for name, v in fund_rows]
    lines += [
        "",
        "--- [12/15] 首板题材归类 [demo] 合成样本 ---",
        "",
        "| 集群 | 首板 | 连板 |",
        "|---|---|---|",
    ]
    lines += [f"| {t} | {f} | {l} |" for t, f, l in first_boards]
    lines += [
        "",
        "## 趋势波段候选",
        "",
        "🟢 趋势波段初筛 5 只完成风险分层：清洁 3 / 标注 1 / 降档 1 / 剔除 0 / 未验证 0",
        "",
        "### 粗筛候选",
        "",
        "| 代码 | 名称 |",
        "|---|---|",
    ]
    lines += [f"| {c} | {n} |" for c, n in swing_cands]
    lines += [
        "",
        "### 风险扫描",
        "",
        "| 代码 | 结论 |",
        "|---|---|",
    ]
    lines += [f"| {c} | {r} |" for c, r in swing_risk]
    lines += [
        "",
        "## 美股指数ETF",
        "",
        "| 代码 | 最新价 | 涨跌幅 |",
        "|---|---|---|",
        "| QQQ | 512.30 | +0.6% |",
        "| SPY | 680.10 | +0.4% |",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="离线端到端演示（合成数据，零网络零密钥）")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "demo")
    args = ap.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    snapshot = out / f"quick-snapshot-{DATA_DATE.replace('-', '')}-201500.md"
    snapshot.write_text(build_snapshot(), encoding="utf-8")
    print(f"[1/4] 合成快照 → {snapshot.name}")

    from quick_delivery import build_delivery, verify_delivery
    context_path, review_path, manifest_path, manifest = build_delivery(
        snapshot, output_dir=out, now=NOW)
    print(f"[2/4] canonical context → {context_path.name}")
    print(f"[3/4] 确定性渲染 → {review_path.name}")
    print(f"      manifest.publishable = {str(manifest['publishable']).lower()}")
    if manifest["errors"]:
        for err in manifest["errors"]:
            print(f"      error: {err}")

    errors = verify_delivery(manifest_path, now=NOW)
    print(f"[4/4] 交付前哈希复核：{'通过' if not errors else '失败: ' + '; '.join(errors)}")
    if not errors:
        body = review_path.read_text(encoding="utf-8")
        head = "\n".join(body.splitlines()[:12])
        print("\n----- 交付正文预览（前 12 行）-----")
        print(head)
        print("...")
    return 0 if (manifest["publishable"] and not errors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
