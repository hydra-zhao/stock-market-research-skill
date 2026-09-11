"""Normalize an existing quick snapshot into FINAL-001 canonical facts."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.paths import positions_file
from quick_contract import STAGE_STATUSES, sha256_file, stage
from review_hooks import hooks_status, next_trade_date
from round1_v2 import _quick_eval

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "quick_context.schema.json"
SNAPSHOT_TZ = timezone(timedelta(hours=8))  # 快照文件名时间戳统一按 A 股本地时区解释


def _section(raw: str, label: str) -> str:
    pat = re.compile(
        rf"^--- \[\d+/\d+\] {re.escape(label)} \[[^]]+\] [^-]*---\s*$\n(.*?)(?=^--- \[|\Z)",
        re.M | re.S,
    )
    m = pat.search(raw)
    return m.group(1).strip() if m else ""


def _heading_block(raw: str, heading_fragment: str) -> str:
    pat = re.compile(rf"^##[^\n]*{re.escape(heading_fragment)}[^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)
    m = pat.search(raw)
    return m.group(0).strip() if m else ""


def _local_block(raw: str, marker: str) -> str:
    pat = re.compile(rf"^--- \[local\][^\n]*{re.escape(marker)}[^\n]*---\n(.*?)(?=^## |\Z)", re.M | re.S)
    m = pat.search(raw)
    return m.group(0).strip() if m else ""


def _table_ex(block: str) -> tuple[list[dict], list[dict]]:
    """表格 → ``(rows, malformed)``。

    🆕 审计收口（D）N2b：旧实现 ``if len(values) == len(header)`` 把列数不匹配的
    整行**静默丢弃**——没有旁路、没有计数、调用方无从知晓。后果按调用点不同：
    持仓段丢一行会让 ``actions.existing_longterm.allowed = bool(holdings)`` 由
    True 翻 False（交易权限）；梯队表丢一行会少渲染一行；昨日连板表现丢一行会让
    该股既不进断板名单也不进未验证名单（凭空从统计里消失）；涨停板丢一行会让
    龙头晋级判定漏判。

    现在原始行**原样保留**进 malformed 通道：不猜测列义、不补齐、绝不混入
    权威数据（``context["holdings"]`` 等仍只含完整解析的行）。
    """
    lines = [x.strip() for x in block.splitlines() if x.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    cells = lambda line: [x.strip() for x in line.strip("|").split("|")]
    header = cells(lines[0])
    rows, malformed = [], []
    for line in lines[2:]:
        values = cells(line)
        if len(values) == len(header):
            rows.append(dict(zip(header, values)))
            continue
        malformed.append({
            "raw": line, "cells": len(values), "header_cells": len(header),
            "reason": "column_count_mismatch",
        })
    return rows, malformed


def _table(block: str) -> list[dict]:
    """向后兼容包装：只要完整解析的行（既有调用点零改动）。"""
    return _table_ex(block)[0]


def _first_board_themes(block: str) -> list[dict]:
    """Parse the programmatic shouban Top3 table; never infer theme aliases."""
    rows = _table(block)
    themes = []
    for row in rows[:3]:
        theme = str(row.get("集群", "")).split("⚠️", 1)[0].strip()
        if not theme:
            continue
        first = _int_cell(row.get("首板"))
        ladder_raw = str(row.get("连板", "")).strip()
        ladder = 0 if ladder_raw in {"-", "—"} else _int_cell(ladder_raw)
        themes.append({"theme": theme, "first_board_count": first,
                       "ladder_count": ladder})
    return themes


# 🎭 公开演示版：主线确认（POOL-003）与接力状态的**判定阈值**属私有策略规则，
# 此处以演示常量代替 —— 2/3 复合确认的状态机结构与生产版一致，数值不可信。
SAMPLE_MAINLINE_MIN_LIMITS = 8    # 演示值：题材总涨停家数门槛
SAMPLE_MAINLINE_MIN_PASS = 2      # 演示值：N 项检查的通过数门槛
SAMPLE_BROKEN_LOSS_PCT = -7.0     # 演示值：断板"大面"描述性统计口径（非交易阈值）


def build_mainline_analysis(first_board: str, fund_block: str) -> dict:
    """Apply mainline confirmation (POOL-003 shape) to canonical facts only."""
    fund_rows = _table(fund_block)
    fund_names = {
        str(next((v for k, v in row.items() if "简称" in k), "")).strip()
        for row in fund_rows
    }
    # TOP10 口径：不完整的板块表既不能证明在场也不能证明缺席。
    fund_verified = len(fund_rows) >= 10
    themes = []
    for item in _first_board_themes(first_board):
        first, ladder = item["first_board_count"], item["ladder_count"]
        total = first + ladder if first is not None and ladder is not None else None
        limit_pass = total >= SAMPLE_MAINLINE_MIN_LIMITS if total is not None else None
        height_pass = ladder > 0 if ladder is not None else None
        fund_pass = item["theme"] in fund_names if fund_verified else None
        checks = (limit_pass, height_pass, fund_pass)
        passed = sum(x is True for x in checks)
        failed = sum(x is False for x in checks)
        unknown = sum(x is None for x in checks)
        if passed >= SAMPLE_MAINLINE_MIN_PASS:
            status = "confirmed"
        elif unknown:
            status = "candidate" if passed else "unverified"
        else:
            status = "candidate" if passed == 1 else "unconfirmed"
        reasons = [f"主线确认：{passed}项通过，{failed}项失败，{unknown}项未验证"]
        themes.append({**item, "total_limit_count": total,
                       "has_2plus_board": height_pass, "fund_top10": fund_pass,
                       "pass_count": passed, "required": SAMPLE_MAINLINE_MIN_PASS,
                       "status": status, "reasons": reasons})
    confirmed = next((x["theme"] for x in themes if x["status"] == "confirmed"), None)
    if confirmed:
        summary = f"{confirmed}满足主线确认规则，确认为主线。"
    elif themes:
        strongest = themes[0]
        summary = (f"{strongest['theme']}扩散最强，但确认项不足，目前为"
                   f"{'候选主线' if strongest['status'] == 'candidate' else '未确认'}，不按已确认主线处理。")
    else:
        summary = "首板题材结构未验证，主线不作确认。"
    return {"themes": themes, "confirmed_mainline": confirmed, "summary": summary}


def build_relay_analysis(market: dict, ladder: list[dict], previous: list[dict],
                         broken: list[dict]) -> dict:
    """Deterministic explanatory layer; the broken-board loss cutoff is
    descriptive statistics (演示口径), not a trade gate."""
    threshold = SAMPLE_BROKEN_LOSS_PCT
    current_max = market.get("max_ladder")
    previous_boards = [_int_cell(next((v for k, v in row.items() if "连续涨停" in k), None))
                       for row in previous]
    previous_max = max((x for x in previous_boards if x is not None), default=None)
    top_row = next((row for row in previous
                    if _int_cell(next((v for k, v in row.items() if "连续涨停" in k), None)) == previous_max), None)
    top_change = _change_pct(next((v for k, v in (top_row or {}).items() if "涨跌幅" in k), None))
    previous_top = {
        "code": re.sub(r"\D", "", str(next((v for k, v in (top_row or {}).items() if "代码" in k), "")))[:6] or None,
        "name": next((str(v).strip() for k, v in (top_row or {}).items() if "简称" in k), None),
        "previous_boards": previous_max, "current_change_pct": top_change,
        "status": ("survived" if top_change is not None and top_change >= 9.5
                   else "broken" if top_change is not None else None),
    }
    promo, premium = market.get("promo_rate"), market.get("premium_avg")
    big_loss = sum(x.get("change_pct") is not None and x["change_pct"] <= threshold for x in broken)
    required = (current_max, previous_max, promo, premium)
    reasons = []
    # 🎭 公开演示版：接力状态机（improving/weak_repair/deteriorating 的组合
    # 判定条件属私有市场判断规则）在此折叠为脱敏中性态 —— 事实统计
    # （高度/晋级率/溢价/断板计数）照常产出，状态语义不对外。
    if any(x is None for x in required):
        state, interpretation = "unverified", "接力关键事实不完整，状态未验证。"
    else:
        state, interpretation = "sanitized", "示例版：接力状态判定规则已脱敏（生产版基于高度/晋级率/溢价的状态机）。"
    if state != "unverified":
        reasons = [f"高度 {previous_max}→{current_max}", f"晋级率 {promo:.1f}%",
                   f"昨日涨停溢价 {premium:+.2f}%", f"断板 {len(broken)} 家、大面 {big_loss} 家"]
    survived = sum(_change_pct(next((v for k, v in row.items() if "涨跌幅" in k), None)) is not None
                   and _change_pct(next((v for k, v in row.items() if "涨跌幅" in k), None)) >= 9.5
                   and _int_cell(next((v for k, v in row.items() if "连续涨停" in k), None)) == previous_max
                   for row in previous) if previous_max is not None else None
    return {"max_ladder": current_max, "previous_top": previous_top,
            "advancement_rate": promo, "prior_limit_premium": premium,
            "broken_count": len(broken), "big_loss_count": big_loss,
            "big_loss_threshold_pct": threshold,
            "high_board_survival": {"previous_high_count": sum(x == previous_max for x in previous_boards) if previous_max is not None else None,
                                    "survived_count": survived},
            "state": state, "reasons": reasons, "interpretation": interpretation}


def build_tomorrow_plan(context: dict) -> dict:
    relay, mainline = context["relay_analysis"], context["mainline_analysis"]
    can_trade, stay_out, watch, holding = [], [], [], []
    confirmed = mainline.get("confirmed_mainline")
    if confirmed:
        if context["eco"]["relay_allowed"]:
            can_trade.append(f"{confirmed}已确认且当前生态否决已解除，可按现行规则进入观察/预案阶段。")
        else:
            can_trade.append(f"若更高优先级否决解除，且{confirmed}的主线确认仍成立，可恢复超短观察。")
    else:
        stay_out.append("主线未获确认，不进入超短观察。")
    if not context["eco"]["relay_allowed"]:
        stay_out.append("生态否决仍在生效，超短接力不开新仓。")
    if mainline["themes"]:
        watch.append(f"观察{mainline['themes'][0]['theme']}能否由首板扩散形成并维持高度确认。")
    if relay.get("previous_top", {}).get("name"):
        watch.append(f"观察前一日高标{relay['previous_top']['name']}对应的高度反馈。")
    summary = context["sections"].get("swing_summary") or {}
    eligible = [x for x in summary.get("candidates", []) if x.get("eligible")]
    if eligible:
        watch.append("趋势波段深查名单：" + "、".join(f"{x['name']}（{x['code']}）" for x in eligible) + "。")
    for item in context["holdings"]:
        if item.get("track"):
            holding.append(f"{item['name']}继续按{item['track']}管理；行情叠加仅作当日观察，不改变原轨道规则。")
    return {"can_trade_if": can_trade, "stay_out_if": stay_out,
            "watch_focus": watch, "holding_focus": holding}


def _number(raw: str, pattern: str, cast=float):
    m = re.search(pattern, raw)
    if not m:
        return None
    value = float(m.group(1))
    return int(value) if cast is int else cast(value)


def _iter_table_groups(block: str):
    """连续表格行切成组 → 逐组 yield ``[cells, cells, ...]``（含表头行）。"""
    group: list[list[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            group.append([c.strip() for c in stripped.strip("|").split("|")])
            continue
        if group:
            yield group
            group = []
    if group:
        yield group


def _cell(cells: list[str], header: list[str], name: str) -> str | None:
    """按表头名取单元格：先精确、后退化为子串匹配。"""
    for index, head in enumerate(header):
        if head == name and index < len(cells):
            return cells[index]
    for index, head in enumerate(header):
        if name in head and index < len(cells):
            return cells[index]
    return None


def _int_cell(value) -> int | None:
    """榜单单元格 → 整数；``--``/空/非数字一律 None（不得默认 0）。"""
    if value is None:
        return None
    text = str(value).replace(",", "").replace("*", "").strip()
    if text.startswith("+"):
        text = text[1:]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.0+", text):
        return int(float(text))
    return None


# 期指结构化字段清单（缺一即进 unverified_fields，交付侧必须显式标注）
FUTURES_FACT_FIELDS = (
    "label", "as_of", "citic_net_position", "citic_net_short",
    "citic_long_change", "citic_short_change", "citic_net_change",
    "top15_net_change", "top15_long_change", "top15_short_change",
)


def parse_futures_facts(block: str) -> dict:
    """期指持仓段 → 结构化事实（纯函数，不做任何交易解释）。

    事实来源只有两处，都是快照原文里的稳定字段：
    ① 品种汇总表的**合计**行（中信期货自身四品种合并）；
    ② 「Top 15 合计」汇总行。
    解析不到就是 ``None`` 并记入 ``unverified_fields``——交付侧据此显式
    标注未验证，不得静默省略后让读者误以为数字完整。
    """
    facts: dict = {name: None for name in FUTURES_FACT_FIELDS}
    title = re.search(r"\*\*([^*]*期指持仓变化[^*]*)\*\*", block or "")
    if title:
        facts["label"] = title.group(1).strip()
        date = re.search(r"(\d{4}-\d{2}-\d{2})", facts["label"])
        facts["as_of"] = date.group(1) if date else None
    for group in _iter_table_groups(block or ""):
        header, rows = group[0], group[2:]
        if not any("净多chg" in head for head in header):
            continue
        for cells in rows:
            if len(cells) != len(header) or "合计" not in cells[0]:
                continue
            facts["citic_net_position"] = _int_cell(_cell(cells, header, "净持仓"))
            facts["citic_long_change"] = _int_cell(_cell(cells, header, "多chg"))
            facts["citic_short_change"] = _int_cell(_cell(cells, header, "空chg"))
            facts["citic_net_change"] = _int_cell(_cell(cells, header, "净多chg"))
            break
    if facts["citic_net_position"] is not None:
        # 净空 = 空头 − 多头 = −净持仓（v7.2.18 轨迹段同一口径）
        facts["citic_net_short"] = -facts["citic_net_position"]
    top15 = re.search(r"Top\s*15\s*合计[：:]([^\n]*)", block or "")
    if top15:
        pairs = dict(re.findall(r"(净多chg|多chg|空chg)\s*=\s*([+-]?[\d,]+)", top15.group(1)))
        facts["top15_net_change"] = _int_cell(pairs.get("净多chg"))
        facts["top15_long_change"] = _int_cell(pairs.get("多chg"))
        facts["top15_short_change"] = _int_cell(pairs.get("空chg"))
    facts["unverified_fields"] = [n for n in FUTURES_FACT_FIELDS if facts.get(n) is None]
    return facts


# 既有断板阈值（9.5%）；本次只修缺失值处理，阈值不动
BREAK_THRESHOLD_PCT = 9.5
_UNVERIFIED_CELLS = {"", "--", "-", "—", "/", "null", "none", "nan", "n/a"}


def _change_pct(value) -> float | None:
    """涨跌幅单元格 → 有限浮点；任一异常形态一律 None（fail-closed）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text.lower() in _UNVERIFIED_CELLS:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def classify_broken_boards(rows: list | None) -> tuple[list[dict], list[dict]]:
    """昨日连板表现 → ``(断板名单, 未验证名单)``（纯函数）。

    涨跌幅列缺失 / 空 / ``--`` / 非数字 / 停牌类不可解析 → **既不判断板也不
    默认 0**，一律进未验证名单。旧实现 ``row.get(chg_key, 0)`` 会把无法核验
    的股票算成 ``chg=0.0`` → ``< 9.5`` 成立 → 凭空生成"今日炸板 +0.00%"。
    """
    broken: list[dict] = []
    unverified: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        chg_key = next((k for k in row if "涨跌幅" in k), "")
        record = {
            "code": row.get(next((k for k in row if "代码" in k), ""), ""),
            "name": row.get(next((k for k in row if "简称" in k), ""), ""),
            "previous_boards": row.get(next((k for k in row if "连续涨停" in k), ""), ""),
        }
        change = _change_pct(row.get(chg_key)) if chg_key else None
        if change is None:
            unverified.append({**record, "reason": "change_pct_unverified"})
            continue
        if change < BREAK_THRESHOLD_PCT:
            broken.append({**record, "change_pct": change})
    return broken, unverified


# swing 附录结构化摘要：风险表结论单元格 → 层级词表（与 round1_v2._swing_risk_tiers 同集）
SWING_TIER_LABELS = {
    "clean": "✅ 清洁", "note": "⚪ 标注", "down": "🟠 降档",
    "red": "🔴 一票否决", "unverified": "未验证",
}

_SWING_STRATIFY_RE = re.compile(
    r"^(?P<line>(?:[🟢🟡🔴⚪]\s*)?趋势波段初筛\s*(?P<total>\d+)\s*只[^\n]*"
    r"风险分层：清洁\s*(?P<clean>\d+)\s*/\s*标注\s*(?P<note>\d+)\s*/\s*降档\s*(?P<down>\d+)"
    r"\s*/\s*剔除\s*(?P<out>\d+)\s*/\s*未验证\s*(?P<unverified>\d+)[^\n]*)",
    re.M,
)


def _swing_risk_tier(conclusion_cell: str) -> str:
    """风险扫描结论单元格 → 层级；无任何已知标记 = unverified。"""
    if "🔴" in conclusion_cell:
        return "red"
    if "🟠" in conclusion_cell:
        return "down"
    if "⚪" in conclusion_cell:
        return "note"
    if "✅" in conclusion_cell:
        return "clean"
    return "unverified"


def summarize_swing(text: str | None) -> dict | None:
    """swing 附录原文 → 结构化摘要（纯函数，供 renderer 摘要化渲染）。

    只认三处稳定结构：分层结论行、粗筛候选表（前两列=代码/名称）、风险扫描
    表（代码列+结论列）。任一关键结构缺失返回 None——渲染器按"格式未识别"
    显式降级，绝不把半解析结果冒充完整候选账。候选不在风险表=未验证，
    不得默认清洁。
    """
    text = text or ""
    strat = _SWING_STRATIFY_RE.search(text)
    if not strat:
        return None
    candidates: list[dict] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("###") and "粗筛候选" in stripped:
            in_table = True
            continue
        if in_table and not stripped.startswith("|"):
            if candidates:
                break
            continue
        if not (in_table and stripped.startswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"代码", "---"} or set(cells[0]) <= {"-", ":"}:
            continue
        code = re.sub(r"\D", "", cells[0])[:6]
        if len(code) == 6 and cells[1]:
            candidates.append({"code": code, "name": cells[1]})
    if not candidates:
        return None
    tiers: dict[str, str] = {}
    tier_labels: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        code = re.sub(r"\D", "", cells[0])[:6]
        if len(code) != 6 or not cells[1]:
            continue
        # 只认风险扫描表行：结论列必须带层级标记。候选表（第二列=名称）、
        # 前复权校准表（第二列=ok/unverified 状态词）等无标记行一律跳过——
        # 2026-09-11 实捕：候选行"|300570|太辰光|…"曾被当成风险结论，
        # 渲染出"风险层=太辰光"。
        tier = _swing_risk_tier(cells[1])
        if tier == "unverified":
            continue
        tiers[code] = tier
        tier_labels[code] = cells[1]
    out = []
    for item in candidates:
        tier = tiers.get(item["code"], "unverified")
        out.append({
            "code": item["code"], "name": item["name"], "tier": tier,
            "tier_label": tier_labels.get(item["code"], SWING_TIER_LABELS[tier]),
            "eligible": tier in {"clean", "note"},
        })
    return {
        "stratification_line": strat.group("line").strip(),
        "total": int(strat.group("total")),
        "tiers": {key: int(strat.group(key)) for key in
                 ("clean", "note", "down", "out", "unverified")},
        "candidates": out,
    }


def _finite(value) -> float | None:
    """任意单元格 → 有限浮点；NaN/None/不可解析一律 None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _holding_quotes(holdings: list[dict], data_date: str, now: datetime,
                    frame_fn=None) -> None:
    """台账持仓 → 确定性行情叠加（原地写入 ``holding["quote"]``）。

    数据源=本地完成日 K 底座（market_dump，零配额，收盘后缓存含当日终价则
    自动纳入、盘中自动剔除今日暂定行）。bar 日期 ≠ 数据日 → 该票 unverified：
    宁可未验证，不得把陈旧收盘冒充当日行情。底座整体不可用 → 全部
    unverified；行情叠加是增强层，绝不阻断 FINAL 交付链。
    """
    if not holdings:
        return
    last: dict[str, dict] = {}
    try:
        if frame_fn is None:
            from sources.market_dump import frame as frame_fn
        df = frame_fn(codes=[h["code"] for h in holdings], now=now)
        if df is not None and not df.empty:
            for row in df.sort_values(["code", "date"]).itertuples():
                last[str(row.code)] = {
                    "date": str(row.date), "close": _finite(row.close_price),
                    "prev": _finite(row.prev), "volume": _finite(row.volume),
                    "turnover": _finite(row.turnover),
                }
    except Exception:
        last = {}
    for h in holdings:
        bar = last.get(h["code"])
        quote = {"status": "unverified", "date": None, "close": None,
                 "change_pct": None, "volume": None, "turnover": None,
                 "reason": "local_base_unavailable"}
        if bar is not None:
            quote["date"] = bar["date"]
            if bar["date"] == data_date and bar["close"] and bar["prev"]:
                quote.update({
                    "status": "verified",
                    "close": round(bar["close"], 2),
                    "change_pct": round((bar["close"] / bar["prev"] - 1) * 100, 2),
                    "volume": int(bar["volume"]) if bar["volume"] is not None else None,
                    "turnover": round(bar["turnover"] / 1e8, 2) if bar["turnover"] is not None else None,
                    "reason": None,
                })
            else:
                quote["reason"] = "local_base_stale"
        h["quote"] = quote


def _table_parse_summary(groups: dict) -> dict:
    """``{段名: (解析行数, malformed)}`` → canonical 解析完整性账（纯函数）。

    🆕 审计收口（D）：把"丢了多少行、丢的是哪几行"变成 context 里的**一等字段**，
    正文可渲染、schema 可校验、测试可断言——静默丢行不能再无声发生。
    """
    malformed: list[dict] = []
    for name, (_parsed, bad) in groups.items():
        malformed.extend({"section": name, **item} for item in bad)
    return {
        "parsed": {name: n for name, (n, _bad) in groups.items()},
        "malformed_counts": {name: len(bad) for name, (_n, bad) in groups.items()},
        "malformed": malformed,
    }


def _eco_state(label: str, intraday: bool) -> str:
    if intraday:
        return "intraday"
    for token, state_name in (
        ("主升", "main_rise"), ("分歧", "divergence"), ("指数", "index"),
        ("犹豫", "hesitation"), ("冰点", "ice"), ("退潮", "retreat"),
        ("恐慌", "panic"), ("混沌", "mixed"),
    ):
        if token in label:
            return state_name
    return "unknown"


def _parse_holdings_ex(path: Path) -> tuple[list[dict], list[dict]]:
    """持仓明细 → ``(holdings, malformed)``。

    🆕 审计收口（D）：本函数原有**两个**静默丢弃点——``_table`` 的列数不匹配，
    以及下面 ``len(code) != 6 or not name`` 的 continue（例如代码写错位数、
    名称列空）。第二处同样改为原样进 malformed 通道：解析不出≠没有持仓，
    静默丢会让 ``existing_longterm.allowed`` 从 True 翻 False。
    """
    if not path.exists():
        return [], []
    raw = path.read_text(encoding="utf-8", errors="replace")
    block = _heading_block(raw, "持仓明细")
    rows, malformed = _table_ex(block)
    out = []
    for row in rows:
        code = re.sub(r"\D", "", row.get("代码", ""))[:6]
        name = row.get("名称", "").strip()
        if len(code) != 6 or not name:
            # 原始行按表头顺序还原（列数与表头一致，问题在**取值**不在列数）：
            # 交付物里要能看到是哪一行、写的是什么，而不是"少了一行"。
            malformed.append({
                "raw": "| " + " | ".join(str(v) for v in row.values()) + " |",
                "cells": len(row), "header_cells": len(row),
                "reason": "code_or_name_unparsable",
            })
            continue
        out.append({
            "code": code, "name": name, "track": row.get("轨道", "未验证"),
            "cost": row.get("成本", "未验证"), "status": "持有",
            "source": str(path),
        })
    return out, malformed


def _parse_holdings(path: Path) -> list[dict]:
    """向后兼容包装：只要解析成功的持仓。"""
    return _parse_holdings_ex(path)[0]


def _leaders(data_date: str, root: Path) -> list[dict]:
    store = root / "output" / "daywatch_leaders.json"
    if not store.exists():
        return []
    next_day = next_trade_date(data_date.replace("-", ""))
    payload = json.loads(store.read_text(encoding="utf-8"))
    result = []
    for item in payload.get("days", {}).get(next_day, []):
        result.append({
            "date": next_day, "code": str(item.get("code", "")).zfill(6),
            "name": str(item.get("name", "")), "theme": str(item.get("theme", "")),
            "boards": int(item.get("boards") or 0), "source": str(item.get("source", "unknown")),
            "boards_as_of": None, "current_status": "观察名单", "current_change_pct": None,
        })
    return result


def _seat_status(data_date: str, root: Path) -> tuple[str, str | None]:
    """seat sidecar → ``(status, checked_at)``。

    N4：seat_profile 是 seat 状态的事实源，这里**原样透传**其状态词表，
    绝不折叠成 unverified——折叠会让 FINAL-001 与 seat_profile 对同一天
    给出两种风险语义。未知状态同样原样透传，由交付策略 fail-closed 兜底。
    """
    p = root / "output" / "seats" / f"{data_date.replace('-', '')}.status"
    if not p.exists():
        return "unverified", None
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        return str(meta.get("status", "unverified")), meta.get("checked_at")
    except Exception:
        return "failed", None


def _appendix(snapshot: Path, raw: str, fragment: str, root: Path, data_date: str) -> dict:
    """附录段 → ``{"text","status","source_time","error","source_path","source_sha256"}``。

    N8：``reused`` 必须带上"复用自哪份文件"（路径 + sha256），否则无法证明
    正文引用的确实是那份成功结果；交付闸门据此复核。
    """
    direct = _heading_block(raw, fragment)
    failure_text = direct
    if fragment == "美股指数ETF" and not failure_text:
        m = re.search(r"^⚠️ (?:月度/)?美股ETF观察附录失败[^\n]*", raw, re.M)
        failure_text = m.group(0) if m else ""
    failed = bool(failure_text and any(x in failure_text for x in ("扫描失败", "附录失败", "未验证（不是无候选）")))
    error = None
    if failed:
        match = re.search(r"([A-Za-z]+Error|OSError):\s*([^\n]+)", failure_text)
        trace = re.search(r"traceback=([^\n]+)", failure_text)
        error = {"type": match.group(1) if match else "StageError",
                 "message": match.group(2).split("| traceback=", 1)[0].strip() if match else failure_text.strip()[:500],
                 "traceback_path": trace.group(1).strip() if trace else None}

    def result(text, status, source, err=None):
        path = source.resolve()
        return {"text": text, "status": status, "source_time": _snapshot_time(source),
                "error": err, "source_path": str(path), "source_sha256": sha256_file(path)}

    if direct and not failed:
        return result(direct, "complete", snapshot)
    # R1 时间因果：reused 只能来自「同数据日、严格早于当前快照、且成功」的快照，
    # 取其中离当前最近的一份。禁止复用未来快照（历史重放/审计时的数据穿越），
    # 也禁止用文件名字符串排序代替时间先后。
    current = _snapshot_datetime(snapshot)
    candidates: list[tuple[datetime, Path]] = []
    if current is not None:
        for path in (root / "output" / "reviews").glob(
                f"quick-snapshot-{data_date.replace('-', '')}-*.md"):
            moment = _snapshot_datetime(path)
            if moment is None or moment >= current:
                continue  # 自身 / 同一时刻 / 未来快照一律不得作为来源
            candidates.append((moment, path))
    for _, older in sorted(candidates, key=lambda item: item[0], reverse=True):
        # H21（2026-09-10 审计）：glob→read 之间文件可能被并发删除（另一会话/清理
        # 脚本删快照），旧实现让 FileNotFoundError 冒泡炸掉整条 FINAL 交付链。
        # 候选读不到就跳过它继续找下一份，最终仍按既有语义返回 failed/unverified。
        try:
            older_text = older.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = _heading_block(older_text, fragment)
        if block and not any(x in block for x in ("扫描失败", "附录失败", "未验证（不是无候选）")):
            return result(block, "reused", older, error)
    return result(direct, "failed" if failed else "unverified", snapshot, error)


def _snapshot_datetime(path: Path) -> datetime | None:
    """快照文件名 → timezone-aware datetime（同一交易日内的因果序依据）。

    R1：复用判定必须基于时间先后，而不是文件名字符串排序；无法解析的名字
    一律返回 None（调用方按 fail-closed 处理，不做"猜一个时间"的兜底）。
    """
    m = re.search(r"(\d{8})-(\d{6})", Path(path).name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=SNAPSHOT_TZ)
    except ValueError:
        return None


def _snapshot_time(path: Path) -> str | None:
    moment = _snapshot_datetime(path)
    return moment.isoformat() if moment else None


def _hook_stages(data_date: str, root: Path, now: datetime, seat_stage: dict) -> dict:
    result = {"seat": seat_stage}
    lines, _ = hooks_status(data_date.replace("-", ""))
    for name in ("case", "leaders", "trendscan", "wave"):
        line = next((item for item in lines if re.search(rf"(?:✅|💥|⚠️)\s*{name}\b", item)), "")
        status = "complete" if line.startswith("✅") else "failed" if line.startswith("💥") else "unverified"
        result[name] = stage(name, status, now, data_date=data_date)
    return result


def validate_context(context: dict) -> list[str]:
    """Validate against the committed schema, then apply semantic contracts."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = _schema_errors(context, schema, schema)
    if errors:
        return errors
    allowed_statuses = STAGE_STATUSES  # 词表唯一事实源在 quick_contract（N4）
    for name, item in {**context["stages"], **{f"hook.{k}": v for k, v in context["hooks"].items()}}.items():
        if item.get("stage_id") != name or not isinstance(item.get("temporal_valid"), bool):
            if not (name.startswith("hook.") and item.get("stage_id") == name[5:] and isinstance(item.get("temporal_valid"), bool)):
                errors.append(f"stage {name} invalid")
        if item.get("status") not in allowed_statuses:
            errors.append(f"stage {name} status invalid")
        if item.get("status") == "reused" and not item.get("source_time"):
            errors.append(f"stage {name} reused without source_time")
    for name, item in context["actions"].items():
        allowed, maximum = item.get("allowed"), item.get("max_new_position_pct")
        if allowed is False and maximum not in (0, 0.0, None):
            errors.append(f"action {name} disallowed but max_new_position_pct={maximum}")
    # 🆕 审计收口（D）：解析完整性账必须自洽——丢行数要对得上明细，
    # malformed 必须带得出的原始行（无原始行=无从复核，等于又一次静默丢弃）。
    tp = context["sections"].get("table_parse") or {}
    counts, rows = tp.get("malformed_counts") or {}, tp.get("malformed") or []
    for name, count in counts.items():
        actual = sum(1 for item in rows if item.get("section") == name)
        if actual != count:
            errors.append(f"table_parse {name} count {count} != listed {actual}")
    for item in rows:
        if not item.get("raw") or not item.get("section"):
            errors.append("table_parse malformed row without raw/section")
    return errors


def _schema_errors(value, rule: dict, root: dict, path: str = "context") -> list[str]:
    """Small dependency-free JSON Schema subset used by quick_context.schema.json."""
    if "$ref" in rule:
        target = root
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _schema_errors(value, target, root, path)
    errors = []
    if "const" in rule and value != rule["const"]:
        errors.append(f"{path}: expected const {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: not in enum")
    expected = rule.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        type_ok = any(_type_matches(value, choice) for choice in choices)
        if not type_ok:
            return errors + [f"{path}: expected type {choices}"]
    if isinstance(value, dict):
        required = rule.get("required", [])
        errors += [f"{path}: missing {key}" for key in required if key not in value]
        properties = rule.get("properties", {})
        additional = rule.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                errors += _schema_errors(item, properties[key], root, f"{path}.{key}")
            elif additional is False:
                errors.append(f"{path}: unexpected {key}")
            elif isinstance(additional, dict):
                errors += _schema_errors(item, additional, root, f"{path}.{key}")
    if isinstance(value, list) and isinstance(rule.get("items"), dict):
        for index, item in enumerate(value):
            errors += _schema_errors(item, rule["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{path}: too short")
        if rule.get("pattern") and not re.search(rule["pattern"], value):
            errors.append(f"{path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in rule and value > rule["maximum"]:
            errors.append(f"{path}: above maximum")
    return errors


def _type_matches(value, expected: str) -> bool:
    mapping = {
        "object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "null": lambda x: x is None,
    }
    return mapping.get(expected, lambda _x: False)(value)


def build_context(snapshot_path: Path, *, now: datetime | None = None, positions_path: Path | None = None, root: Path = ROOT) -> dict:
    now = now or datetime.now().astimezone()
    snapshot_path = Path(snapshot_path)
    raw = snapshot_path.read_text(encoding="utf-8", errors="replace")
    verdict = _quick_eval(raw, now=now.replace(tzinfo=None))
    data_date = verdict["data_date"]
    swing = _appendix(snapshot_path, raw, "趋势波段候选", root, data_date)
    us_etf = _appendix(snapshot_path, raw, "美股指数ETF", root, data_date)
    swing_text, swing_status, us_text, us_status = swing["text"], swing["status"], us_etf["text"], us_etf["status"]
    seat_status, seat_time = _seat_status(data_date, root)
    seat_stage = stage("seat", seat_status, now, data_date=data_date, source_time=seat_time)
    first_board = _local_block(raw, "首板题材归类")
    ladder, ladder_bad = _table_ex(_section(raw, "连板天梯"))
    previous, previous_bad = _table_ex(_section(raw, "昨日连板表现"))
    broken, broken_unverified = classify_broken_boards(previous)
    futures_facts = parse_futures_facts(_section(raw, "期指持仓"))
    eco_state = _eco_state(verdict["eco"], verdict["intraday"])
    relay_allowed = not verdict["eco"].startswith("🔴") and eco_state not in {"unknown", "intraday"}
    eligible_swing = swing_status in {"complete", "reused"} and any(x in swing_text for x in ("清洁", "标注"))
    holdings, holdings_bad = _parse_holdings_ex(Path(positions_path or positions_file()))
    _holding_quotes(holdings, data_date, now)
    leaders = _leaders(data_date, root)
    up_rows, up_bad = _table_ex(_section(raw, "涨停板"))
    current_up = {
        re.sub(r"\D", "", str(next((v for k, v in row.items() if "代码" in k), "")))[:6]
        for row in up_rows
    }
    table_parse = _table_parse_summary({
        "ladder": (len(ladder), ladder_bad),
        "previous": (len(previous), previous_bad),
        "current_up": (len(up_rows), up_bad),
        "holdings": (len(holdings), holdings_bad),
    })
    previous_date = None
    previous_head = _section(raw, "昨日连板表现").splitlines()[:1]
    if previous_head:
        date_match = re.search(r"连续涨停天数\[(\d{8})\]", previous_head[0])
        previous_date = date_match.group(1) if date_match else None
    broken_by_code = {re.sub(r"\D", "", str(x["code"]))[:6]: x for x in broken}
    for leader in leaders:
        broken_row = broken_by_code.get(leader["code"])
        if leader["code"] in current_up:
            leader["boards_as_of"] = data_date.replace("-", "")
            leader["current_status"] = "今日涨停/晋级"
        elif broken_row:
            leader["boards_as_of"] = previous_date
            leader["current_status"] = "今日炸板/未晋级"
            leader["current_change_pct"] = broken_row["change_pct"]
        else:
            leader["boards_as_of"] = None
            leader["current_status"] = "观察名单；当日状态未独立核验"
    context = {
        "schema_version": "1.0", "artifact_type": "quick_context",
        "generated_at": now.isoformat(timespec="seconds"), "data_date": data_date,
        "source_snapshot": {"path": str(snapshot_path.resolve()), "sha256": sha256_file(snapshot_path), "deliverable": False},
        "market": {
            "limit_up": int(verdict["limit_up"]), "limit_down": int(verdict["limit_down"]),
            "bomb": int(verdict["bomb"]), "max_ladder": int(verdict["max_ladder"]),
            "breadth_up": _number(raw, r"上涨家数\[\d+\]\*\*: ([\d.]+)", int),
            "breadth_down": _number(raw, r"下跌家数\[\d+\]\*\*: ([\d.]+)", int),
            "turnover": _number(_section(raw, "历史成交额"), rf"\| {re.escape(data_date)} \| ([\d.]+) \|"),
            "index_close": verdict.get("sh_close"), "index_change_pct": verdict.get("sh_chg"),
            # 🆕 v7.3.5 派生指标（判定早已使用，此处仅登记进 canonical 事实层供渲染；
            # 全部来自 _quick_eval 确定性输出，缺失=None → 渲染"未验证"）
            "zt_ratio": verdict.get("zt_ratio"), "dt_ratio": verdict.get("dt_ratio"),
            "vol_ratio": verdict.get("vol_ratio"), "bomb_rate": verdict.get("bomb_rate"),
            "seal_rate": (round(100 - verdict["bomb_rate"], 1)
                          if (int(verdict["limit_up"]) + int(verdict["bomb"])) > 0 else None),
            "seal10": verdict.get("seal10"), "seal20": verdict.get("seal20"),
            "premium_avg": verdict.get("premium_avg"), "promo_rate": verdict.get("promo_rate"),
            "dod_pct": verdict.get("dod_pct"), "vol_price": verdict.get("vol_price") or None,
            "ma360": verdict.get("ma360"), "ma250": verdict.get("ma250"),
            "bull_bear": verdict.get("bull_bear"), "index_status": verdict.get("index_status"),
            "zt_mean": verdict.get("zt_mean"), "dt_mean": verdict.get("dt_mean"),
            "amt_mean": verdict.get("amt_mean"),
        },
        "eco": {
            "state": eco_state, "label": verdict["eco"], "relay_allowed": relay_allowed,
            "verdicts": {"tuishen": verdict["tui"], "niepan": verdict["nie"], "yangjia": verdict["yang"], "jianguqiyi": verdict["jian"]},
        },
        "holdings": holdings,
        "leaders": leaders,
        "actions": {
            "ultra_relay": {"allowed": relay_allowed, "max_new_position_pct": None if relay_allowed else 0, "note": verdict["action"] if relay_allowed else "超短接力不开新仓"},
            "swing": {"allowed": bool(relay_allowed and eligible_swing), "max_new_position_pct": None if relay_allowed and eligible_swing else 0, "note": "仅清洁/标注候选且生态允许时进入深查"},
            "existing_longterm": {"allowed": bool(holdings), "max_new_position_pct": 0, "note": "仅表达已有长线持仓可按原轨道管理，不产生新开仓权限"},
        },
        "stages": {
            "collect": stage("collect", "complete" if "18/18" in raw and " ERR " not in raw else "degraded", now, data_date=data_date, source_time=_snapshot_time(snapshot_path)),
            "swing": stage("swing", swing_status, now, data_date=data_date, source_time=swing["source_time"],
                           error=swing["error"], source_path=swing["source_path"], source_sha256=swing["source_sha256"]),
            "us_etf": stage("us_etf", us_status, now, data_date=data_date, source_time=us_etf["source_time"],
                            error=us_etf["error"], source_path=us_etf["source_path"], source_sha256=us_etf["source_sha256"]),
            "national_etf": stage("national_etf", "complete" if _section(raw, "国家队ETF") else "unverified", now, data_date=data_date, source_time=_snapshot_time(snapshot_path)),
            "seat": seat_stage,
        },
        "hooks": {},
        "sections": {
            "futures": _section(raw, "期指持仓"),
            "futures_facts": futures_facts,
            "national_etf": _section(raw, "国家队ETF"),
            "ladder": ladder, "broken_boards": broken,
            "broken_boards_unverified": broken_unverified, "first_board": first_board,
            "swing": swing_text, "swing_summary": summarize_swing(swing_text),
            "us_etf": us_text, "table_parse": table_parse,
        },
    }
    context["relay_analysis"] = build_relay_analysis(
        context["market"], ladder, previous, broken)
    context["mainline_analysis"] = build_mainline_analysis(
        first_board, _section(raw, "板块资金"))
    context["tomorrow_plan"] = build_tomorrow_plan(context)
    context["hooks"] = _hook_stages(data_date, root, now, seat_stage)
    return context
