#!/usr/bin/env python3
"""tech/kline.py — K线数据格式化与技术指标计算"""

import re


def fmt_kline(datas):
    """K线数据专用格式化 — 解析问财横向展开格式 → 行式表格 + 技术摘要"""
    if not datas:
        return "_(无K线数据)_"

    row = datas[0]

    dates = set()
    for key in row:
        m = re.search(r'\[(\d{8})\]', key)
        if m:
            dates.add(m.group(1))
    dates = sorted(dates)

    if not dates:
        return "_(未能解析日期)_"

    def v(key, date):
        val = row.get(f"{key}[{date}]", row.get(key, ""))
        if val is None:
            return ""
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    lines = ["| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量(手) | 换手率% |",
             "|------|------|------|------|------|------|------|"]

    # 全量数组：技术指标与关键位计算用，不受展示截断（30行）影响。
    # 原实现指标只在展示窗口内计算，60日K线下 MA60/MACD 会失真或缺失。
    all_dates, closes, highs, lows, vols = [], [], [], [], []
    for d in dates:
        try:
            c = float(v("收盘价", d))
        except (ValueError, TypeError):
            continue
        all_dates.append(d)
        closes.append(c)
        for arr, key in ((highs, "最高价"), (lows, "最低价"), (vols, "成交量")):
            try:
                arr.append(float(v(key, d)))
            except (ValueError, TypeError):
                arr.append(c if key != "成交量" else 0.0)

    show = dates if len(dates) <= 30 else dates[-30:]

    for d in show:
        o = v("开盘价", d)
        h = v("最高价", d)
        l = v("最低价", d)
        c = v("收盘价", d)
        vol = v("成交量", d)
        tr = v("换手率", d)
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        lines.append(f"| {date_str} | {o} | {h} | {l} | {c} | {vol} | {tr} |")

    extra = f"\n_共 {len(dates)} 个交易日，显示最近 {len(show)} 日_\n"

    if len(closes) < 2:
        return "\n".join(lines) + extra

    cur, prev = closes[-1], closes[-2]
    chg = (cur - prev) / prev * 100
    label = "🟢阳线" if chg > 0 else "🔴阴线" if chg < 0 else "➖平盘"

    extra += f"\n**📈 均线系统**:\n"
    mas = {}
    for n, name in [(5, "MA5"), (10, "MA10"), (20, "MA20"), (60, "MA60")]:
        if len(closes) >= n:
            ma = sum(closes[-n:]) / n
            mas[name] = ma
            pos = "✅站上" if cur > ma else "❌跌破"
            extra += f"- {name}={ma:.2f} {pos}\n"
    extra += f"- 最新: {label} {chg:+.2f}% | 收{cur}\n"

    if len(closes) >= 26:
        def ema(series, n):
            k = 2.0 / (n + 1)
            result = [series[0]]
            for x in series[1:]:
                result.append(x * k + result[-1] * (1 - k))
            return result

        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
        dea = ema(dif, 9)
        macd_bar = [2 * (d - e) for d, e in zip(dif, dea)]
        cur_dif, cur_dea, cur_bar = dif[-1], dea[-1], macd_bar[-1]
        prev_bar = macd_bar[-2] if len(macd_bar) >= 2 else 0

        extra += f"\n**📊 MACD (12,26,9)**:\n"
        extra += f"- DIF={cur_dif:.3f} | DEA={cur_dea:.3f} | 柱={cur_bar:.3f}\n"
        macd_signal = "🟢金叉" if cur_dif > cur_dea else "🔴死叉"
        bar_dir = "放大" if abs(cur_bar) > abs(prev_bar) else "缩小" if abs(cur_bar) < abs(prev_bar) else "持平"
        extra += f"- 状态: {macd_signal} | 柱{bar_dir} | "
        extra += "🟢多头" if cur_bar > 0 else "🔴空头"
        extra += "\n"

    if len(closes) >= 9:
        n_kdj = 9
        k_vals, d_vals, j_vals = [], [], []
        prev_k, prev_d = 50.0, 50.0
        for i in range(len(closes)):
            if i < n_kdj - 1:
                k_vals.append(0)
                d_vals.append(0)
                j_vals.append(0)
                continue
            hh = max(highs[i - n_kdj + 1:i + 1])
            ll = min(lows[i - n_kdj + 1:i + 1])
            rsv = (closes[i] - ll) / (hh - ll) * 100 if hh != ll else 50
            k_val = 2 / 3 * prev_k + 1 / 3 * rsv
            d_val = 2 / 3 * prev_d + 1 / 3 * k_val
            j_val = 3 * k_val - 2 * d_val
            k_vals.append(k_val)
            d_vals.append(d_val)
            j_vals.append(j_val)
            prev_k, prev_d = k_val, d_val

        cur_k, cur_d, cur_j = k_vals[-1], d_vals[-1], j_vals[-1]

        def kdj_zone(val):
            if val > 80:
                return "🔴超买"
            if val < 20:
                return "🟢超卖"
            return "⚪中性"

        extra += f"\n**📊 KDJ (9,3,3)**:\n"
        extra += f"- K={cur_k:.1f} | D={cur_d:.1f} | J={cur_j:.1f}\n"
        extra += f"- K:{kdj_zone(cur_k)} | D:{kdj_zone(cur_d)} | J:{kdj_zone(cur_j)}\n"
        extra += f"- 信号: {'🟢金叉' if cur_k > cur_d else '🔴死叉'}"
        extra += " | " + ("🟢底部拐头" if cur_j < 20 and cur_j > j_vals[-2] else
                           "🔴顶部拐头" if cur_j > 80 and cur_j < j_vals[-2] else "→ 延续")
        extra += "\n"

    extra += f"\n**📊 量价与波动**:\n"
    extra += f"- 近5日涨跌: {closes[-1] - closes[-5]:+.2f} ({((closes[-1] / closes[-5]) - 1) * 100:+.1f}%)\n"
    if len(closes) >= 20:
        high_20, low_20 = max(closes[-20:]), min(closes[-20:])
        extra += f"- 20日区间: {low_20:.2f} ~ {high_20:.2f} (当前{((cur - low_20) / (high_20 - low_20) * 100):.0f}%分位)\n"
    if len(show) >= 3:
        extra += f"- 近3日换手: {v('换手率', show[-1])}% / {v('换手率', show[-2])}% / {v('换手率', show[-3])}%\n"
    if len(vols) >= 5:
        avg_vol_5 = sum(vols[-5:]) / 5
        avg_vol_20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else avg_vol_5
        vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
        extra += f"- 5日均量/20日均量: {vol_ratio:.2f}x "
        extra += "🟢放量" if vol_ratio > 1.3 else "🔴缩量" if vol_ratio < 0.7 else "→ 持平"
        extra += "\n"

    # 🆕 量价异常自动检测（方案 C）
    anomaly_report = _detect_volume_price_anomaly(show, v, closes, highs, lows, vols)
    if anomaly_report:
        extra += f"\n**🚨 量价异常检测**:\n{anomaly_report}"

    # 🆕 关键位阶梯（近60日摆动高低点聚类+均线，全量数组计算）
    levels = calc_key_levels(highs, lows, closes, all_dates)
    if levels:
        extra += fmt_key_levels(levels)

    return "\n".join(lines) + extra


def calc_key_levels(highs, lows, closes, dates, lookback=60, window=3,
                    cluster_pct=0.015, max_levels=4):
    """支撑/压力阶梯：近N日摆动高低点聚类（触碰次数）+ 均线位。

    摆动点定义：window 半径内的局部极值。聚类：价格差 ≤1.5% 归并为一档，
    聚类内点数=触碰次数（触碰越多该位越有效）。均线作为天然关键位并入。

    返回 {"resistance": [(price, touches, last_date, src)], "support": [...],
          "cur": 最新收盘}；数据不足返回 None。
    """
    n = len(closes)
    if n < 25:
        return None
    start = max(0, n - lookback)
    hs, ls, cs = highs[start:], lows[start:], closes[start:]
    ds = dates[start:] if dates and len(dates) == n else [""] * (n - start)
    m = len(cs)

    swing_highs, swing_lows = [], []
    for i in range(window, m - window):
        if hs[i] >= max(hs[i - window:i + window + 1]):
            swing_highs.append((hs[i], ds[i]))
        if ls[i] <= min(ls[i - window:i + window + 1]):
            swing_lows.append((ls[i], ds[i]))

    def cluster(points):
        points = sorted(points, key=lambda x: x[0])
        clusters = []  # (价格合计, 触碰数, 最近日期)
        for price, d in points:
            if clusters:
                s, c, _last = clusters[-1]
                mean = s / c
                if abs(price - mean) / mean <= cluster_pct:
                    clusters[-1] = (s + price, c + 1, max(_last, d))
                    continue
            clusters.append((price, 1, d))
        return [(s / c, c, last) for s, c, last in clusters]

    cur = cs[-1]
    hi_levels = [(p, c, d, "摆动高") for p, c, d in cluster(swing_highs) if p > cur * 1.002]
    lo_levels = [(p, c, d, "摆动低") for p, c, d in cluster(swing_lows) if p < cur * 0.998]

    for k, name in ((5, "MA5"), (10, "MA10"), (20, "MA20"), (60, "MA60")):
        if n >= k:
            mv = sum(closes[-k:]) / k
            if mv > cur * 1.002:
                hi_levels.append((mv, 0, "", name))
            elif mv < cur * 0.998:
                lo_levels.append((mv, 0, "", name))

    hi_levels.sort(key=lambda x: x[0])
    lo_levels.sort(key=lambda x: -x[0])
    return {"resistance": hi_levels[:max_levels],
            "support": lo_levels[:max_levels], "cur": cur}


def fmt_key_levels(lv) -> str:
    """关键位阶梯 → markdown 文本"""
    def side(rows, emoji):
        out = []
        for p, c, d, src in rows:
            touch = f"·{c}次触碰" if c >= 2 else ""
            dt = f"·{d[4:6]}-{d[6:8]}" if d else ""
            out.append(f"{emoji}{p:.2f}({src}{touch}{dt})")
        return " / ".join(out)

    lines = ["\n**🧭 关键位阶梯**（近60日摆动点聚类+均线）:"]
    lines.append("- 压力: " + (side(lv["resistance"], "🔴") if lv["resistance"] else "上方无近端压力"))
    lines.append("- 支撑: " + (side(lv["support"], "🟢") if lv["support"] else "下方无近端支撑"))
    return "\n".join(lines) + "\n"


def _detect_volume_price_anomaly(show, v, closes, highs, lows, vols):
    """量价异常自动检测 — 返回格式化预警文本"""
    if len(closes) < 5:
        return ""

    warnings = []
    n = len(closes)
    cur_close = closes[-1]
    prev_close = closes[-2]

    # 基础数据
    latest_vol = vols[-1] if vols else 0
    avg_vol_5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else latest_vol
    avg_vol_20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else avg_vol_5
    vol_ratio = latest_vol / avg_vol_5 if avg_vol_5 > 0 else 1
    vol_ratio_20 = latest_vol / avg_vol_20 if avg_vol_20 > 0 else 1
    max_vol_20 = max(vols[-20:]) if len(vols) >= 20 else max(vols)
    vol_vs_max = latest_vol / max_vol_20 if max_vol_20 > 0 else 1

    # 当日K线结构
    o = float(v("开盘价", show[-1]) or cur_close)
    h = float(v("最高价", show[-1]) or cur_close)
    l = float(v("最低价", show[-1]) or cur_close)
    c = cur_close
    body = abs(c - o)
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    chg_pct = (c - prev_close) / prev_close * 100

    # 20日位置
    high_20 = max(closes[-20:]) if n >= 20 else max(closes)
    low_20 = min(closes[-20:]) if n >= 20 else min(closes)
    pos_pct = (cur_close - low_20) / (high_20 - low_20) * 100 if high_20 != low_20 else 50

    # ① 天量下跌（满足任一：当日量比>1.8且跌幅>2.5% / 近5日跌幅>15%且当日量超20日均量1.3倍 / 当日量创20日新高且收阴）
    recent_5d_chg = (closes[-1] / closes[-6] - 1) * 100 if n >= 6 else chg_pct
    is_huge_vol = vol_ratio > 1.8 or vol_ratio_20 > 1.5 or vol_vs_max > 0.9
    if (is_huge_vol and chg_pct < -2.5) or (recent_5d_chg < -15 and vol_ratio_20 > 1.3):
        warnings.append(f"🔴 **天量下跌**：量比{vol_ratio:.1f}x/20日比{vol_ratio_20:.1f}x + 当日跌幅{chg_pct:.1f}% / 近5日{recent_5d_chg:.1f}%，资金出逃信号")

    # ② 高位长上影
    if upper_shadow > body * 2 and upper_shadow > (h - l) * 0.5 and pos_pct > 70:
        warnings.append(f"🔴 **高位长上影**：上影{upper_shadow:.2f} > 实体2倍，20日{pos_pct:.0f}%分位，出货风险")

    # ③ 低位长下影（止跌信号，非红线但提示）
    if lower_shadow > body * 2 and lower_shadow > (h - l) * 0.5 and pos_pct < 30:
        warnings.append(f"🟢 **低位长下影**：下影{lower_shadow:.2f}，20日{pos_pct:.0f}%分位，疑似护盘/抄底")

    # ④ 连续缩量滞涨
    if len(vols) >= 3 and all(vols[-i] < avg_vol_20 * 0.7 for i in range(1, 4)) and abs(chg_pct) < 1.5:
        warnings.append(f"🟡 **连续缩量滞涨**：近3日量均低于20日均量70%，动能衰竭，警惕变盘")

    # ⑤ 放量滞涨（高位放量但不涨）
    if vol_ratio > 1.5 and abs(chg_pct) < 1.0 and pos_pct > 60:
        warnings.append(f"🟡 **放量滞涨**：量比{vol_ratio:.1f}x但涨幅仅{chg_pct:.1f}%，高位放量不涨=分歧加大")

    # ⑥ 缩量新高（背离）
    if cur_close >= max(closes[-10:-1]) and vol_ratio < 0.8 and pos_pct > 80:
        warnings.append(f"🟡 **缩量新高**：价格创10日新高但量比{vol_ratio:.1f}x，量价背离，持续性存疑")

    # v6.9.44 审计修复：涨跌停阈值按板块自适应（旧 ±9.5 写死对 20cm/北交所
    # 误报"跌停/缩量涨停"）。fmt_kline 无 code 参数，改由数据自证：
    # 历史序列 max|日涨跌幅|≥25 → 30cm（北交所）；≥15 或当日|涨跌幅|>11
    # （10cm 板当日不可能超 ~11）→ 20cm；否则 9.5（10cm 主板）
    _dchg = [abs((closes[i] / closes[i - 1] - 1) * 100)
             for i in range(1, len(closes)) if closes[i - 1]]
    _smax = max(_dchg) if _dchg else 0.0
    if _smax >= 25 or abs(chg_pct) >= 28:
        _lim_th = 28.0
    elif _smax >= 15 or abs(chg_pct) > 11:
        _lim_th = 19.5
    else:
        _lim_th = 9.5

    # ⑦ 跌停/接近跌停
    if chg_pct <= -_lim_th:
        warnings.append(f"🔴 **跌停/接近跌停**：跌幅{chg_pct:.1f}%，检查是否破位或利空")

    # ⑧ 涨停但缩量（一字板/秒板，次日接力风险）
    if chg_pct >= _lim_th and vol_ratio < 0.5:
        warnings.append(f"🟡 **缩量涨停**：涨幅{chg_pct:.1f}%但量比{vol_ratio:.1f}x，一字/秒板，次日溢价不确定")

    # ⑨ 暴跌后缩量反弹（下跌中继风险）
    if n >= 10 and recent_5d_chg < -10 and chg_pct > 2 and vol_ratio < 0.7:
        warnings.append(f"🟡 **暴跌后缩量反弹**：近5日{recent_5d_chg:.1f}%后缩量涨{chg_pct:.1f}%，可能是下跌中继，非反转")

    # ⑩ 连续放量下跌（恐慌蔓延）
    if n >= 3 and all((closes[-i] / closes[-i-1] - 1) * 100 < -2 for i in range(1, 3)) and vol_ratio > 1.2:
        warnings.append(f"🔴 **连续放量下跌**：近2日连续大跌+量比{vol_ratio:.1f}x，恐慌盘涌出，勿抄底")

    # ⑪ 低位放量阴线（下跌中继/新低的信号）
    if pos_pct < 20 and chg_pct < -2 and vol_ratio > 1.2:
        warnings.append(f"🔴 **低位放量阴线**：20日{pos_pct:.0f}%分位 + 跌幅{chg_pct:.1f}% + 量比{vol_ratio:.1f}x，下跌动能未衰竭，勿抄底")

    if not warnings:
        return "✅ 未检出显著量价异常"

    return "\n".join(f"- {w}" for w in warnings)
