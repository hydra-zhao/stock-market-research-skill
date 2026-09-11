#!/usr/bin/env python3
"""ths_fundflow.py — 同花顺板块资金流降级源（akshare hexin-v 路，v7.0.9）

背景：quick/market 的「板块资金」路走问财 hithink-sector-selector，配额耗尽日
（401）主力流向榜断供——板块方向行（TL;DR 领涨板块）与主线确认③（板块资金
净流入TOP10）开天窗。实测 akshare 同花顺资金流接口（q.10jqka.com.cn，
hexin-v cookie 由 akshare 内置 py_mini_racer 生成，本机已验证 90 行返回）：
- stock_fund_flow_industry()   行业资金流（今日）：序号/行业/行业指数/行业-涨跌幅/
                               流入资金/流出资金/净额(亿)/公司家数/领涨股
- stock_fund_flow_concept()    概念资金流（同构）

降级链定位：板块资金路是唯一无 MX/AK 兜底的问财路——本模块补齐（iw 失败
→ THS 资金流）。口径差标注：问财=概念/板块指数口径，THS 行业=申万类行业
口径；主力净买入额 vs 流入-流出净额（亿）数值口径不同，只作方向榜用。
"""

import time

# 段落标签与问财路同名——round1_v2 的 top_sectors 解析（parts[2]=名称列）零改动消费
LABEL = "板块资金"

_NAME_KEYS = ("行业", "概念名称", "板块名称")
_NET_KEYS = ("净额", "主力净流入", "净流入")


def _pick(df, keys):
    for k in keys:
        for c in df.columns:
            if k in c:
                return c
    return None


def render(df) -> str:
    """资金流 DataFrame → 板块资金 markdown 表（净额降序 TOP10）。空/缺列 → None"""
    if df is None or df.empty:
        return None
    name_c, net_c = _pick(df, _NAME_KEYS), _pick(df, _NET_KEYS)
    if name_c is None or net_c is None:
        return None
    chg_c = _pick(df, ("涨跌幅",))
    in_c = _pick(df, ("流入资金", "流入"))
    out_c = _pick(df, ("流出资金", "流出"))
    lead_c = _pick(df, ("领涨股",))
    import pandas as pd  # 🆕 v7.2.13 模块无顶层 pandas（df 作参数传入）；本地引入
    try:
        df2 = df.copy()
        # 🆕 v7.2.13 coerce+dropna：旧 astype(float) 单个坏单元格（"--"）抛
        # ValueError → 整条板块资金降级路 return None
        df2["_net"] = pd.to_numeric(df2[net_c], errors="coerce")
    except (TypeError, ValueError):
        return None
    df2 = df2.dropna(subset=["_net"]).sort_values("_net", ascending=False).head(10)

    header = ["序号", "板块名称"]
    if chg_c:
        header.append("涨跌幅%")
    header += ["主力净额(亿)"]
    if in_c:
        header.append("流入(亿)")
    if out_c:
        header.append("流出(亿)")
    if lead_c:
        header.append("领涨股")
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for i, (_, r) in enumerate(df2.iterrows()):
        cells = [i + 1, r[name_c]]
        if chg_c:
            cells.append(r[chg_c])
        cells.append(r[net_c])
        if in_c:
            cells.append(r[in_c])
        if out_c:
            cells.append(r[out_c])
        if lead_c:
            cells.append(r[lead_c])
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return ("\n".join(lines) + f"\n\n_ths: {len(df2)}/{len(df2)} rows, 0.0s | "
            "同花顺板块资金流（akshare·hexin-v）· 净额口径=流入-流出(亿)_")


def run_ths_fundflow(which: str = "industry", ak=None, today: str = None) -> tuple:
    """dispatch 入口：which ∈ industry|concept。返回 (label, body, ok, elapsed, 'ths')。"""
    t0 = time.time()
    try:
        if ak is None:
            import akshare as ak
        fn = ak.stock_fund_flow_industry if which == "industry" else ak.stock_fund_flow_concept
        body = render(fn())
        ok = body is not None
        if not ok:
            body = "同花顺资金流返回为空/缺净额列"
    except Exception as e:
        ok, body = False, f"THS资金流降级异常: {e}"
    elapsed = time.time() - t0
    if not ok:
        body = f"[ths ERR] {body}"
    return (LABEL, body, ok, elapsed, "ths")
