#!/usr/bin/env python3
"""common/calendar.py — 交易日工具函数

🆕 v6.9.44 审计根治：接入 A股交易日历（AKShare 新浪源 + 本地缓存，惰性加载）——
此前全库 trading_day/is_intraday/prev_trading_day 只跳周末不感知法定节假日，
实测后果：backfill_quick 断跑守卫在每个 ≥3 天长假后把节前最后交易日的合法回填
永久拒绝且不标 missed（静默丢样本）；节假日复盘中 trading_day 落在无数据日上。
日历不可用（拉取失败且无缓存）时自动降级为仅跳周末=旧行为（方向保守，stderr 注记）。
"""

import json
import re
import sys
from datetime import date as dt_date, datetime as dt_dt, timedelta
from pathlib import Path

_cal_cache_file = Path(__file__).resolve().parent.parent / "cache" / "trade_calendar.json"
_cal_set = None          # set[YYYYMMDD] 或 None
_cal_max = ""            # 日历覆盖的最晚交易日（超出=未知区间，回退周一口径）
_cal_loaded = False


def _fetch_calendar():
    """AKShare 新浪交易日历 → set{'YYYYMMDD'}；失败返回 None（惰性 import，重依赖不进模块级）"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        return {str(d).replace("-", "") for d in df["trade_date"]}
    except Exception:
        return None


def _get_calendar():
    """交易日历（set[YYYYMMDD]）或 None。磁盘缓存优先（覆盖今日且留 30 天余量，
    年末自动刷新）；缓存不覆盖时拉一次并落盘；拉取失败但有旧缓存仍可用（判过去
    日期有效）；全空返回 None 由调用方降级。"""
    global _cal_set, _cal_max, _cal_loaded
    if _cal_loaded:
        return _cal_set
    _cal_loaded = True
    today = dt_date.today()
    today_s = today.strftime("%Y%m%d")
    cached = set()
    try:
        if _cal_cache_file.exists():
            obj = json.loads(_cal_cache_file.read_text(encoding="utf-8"))
            cached = set(obj.get("dates", []))
            horizon = obj.get("max", "")
            # 🆕 v7.2.13 新鲜度改判 horizon（未来30天覆盖即可答询）：旧条件
            # today_s in cached 在周末/节假日恒假=每进程必走真网重拉
            if cached and horizon >= (today + timedelta(30)).strftime("%Y%m%d"):
                _cal_set, _cal_max = cached, horizon
                return _cal_set
    except Exception:
        cached = set()
    fetched = _fetch_calendar()
    if fetched:
        try:
            _cal_cache_file.parent.mkdir(parents=True, exist_ok=True)
            _cal_max = max(fetched)
            _cal_cache_file.write_text(
                json.dumps({"dates": sorted(fetched), "max": _cal_max}, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
        _cal_set, _cal_max = fetched, max(fetched)
    elif cached:
        # 拉取失败但旧缓存可用（可能不含未来日）——判过去日期仍有效，交由调用方
        _cal_set, _cal_max = cached, max(cached)
    else:
        print("[calendar] 交易日历不可用（AKShare 拉取失败且无缓存），降级为仅跳周末（节假日不感知）",
              file=sys.stderr)
        _cal_set = None
    return _cal_set


def is_trading_day(d) -> bool:
    """d: date/datetime/'YYYYMMDD'。日历可用按日历判定；不可用降级周一~五=交易日。
    ⚠️ 超出日历覆盖范围（新浪源通常只到当年年末）的日期：不在集合≠节假日，
    回退周一~五口径——否则未来日期会被整体误判为非交易日、回退跨月过长。"""
    if isinstance(d, dt_dt):
        d = d.date()
    if isinstance(d, dt_date):
        d = d.strftime("%Y%m%d")
    cal = _get_calendar()
    if cal is not None:
        if d in cal:
            return True
        if d > _cal_max:
            try:
                return dt_dt.strptime(d, "%Y%m%d").weekday() < 5
            except ValueError:
                return False
        return False
    try:
        return dt_dt.strptime(str(d), "%Y%m%d").weekday() < 5
    except ValueError:
        return False


def trading_day(now: dt_dt | None = None) -> str:
    """返回应查询的交易日 YYYYMMDD。
    09:15(集合竞价=当日数据开始产生)前→前一交易日 | 交易日09:15后→当日 | 周末/节假日→上一交易日

    🆕 v6.9.26: 边界 08:00→09:15，与 is_intraday 起点对齐——盘前(08:00-09:15)
    当日数据尚不存在(一笔成交都没有)，"盘中数据不全"是错标签；正确口径=
    上一交易日完整收盘数据。盘前复盘因此合法：数据层自动拿上一交易日，
    隔夜增量(美股收盘/ETF T+1早8点出炉/NQ00Y实时/金十盘前)自动为最新。
    now 可注入(测试用)，缺省取当前时间。
    🆕 v6.9.44: 日历可用时连法定节假日一起回退（旧实现只跳周末——节假日复盘中
    本函数会落在无数据的节假日上）；日历不可用=仅跳周末（旧行为，保守方向）。
    """
    n = now or dt_dt.now()
    d = n.date() if isinstance(n, dt_dt) else n
    if isinstance(n, dt_dt) and (n.hour, n.minute) < (9, 15):
        d = d - timedelta(1)
    if _get_calendar() is not None:
        while not is_trading_day(d):
            d -= timedelta(1)
        return d.strftime("%Y%m%d")
    wd = d.weekday()
    if wd == 5:
        d = d - timedelta(1)   # Sat → Fri
    elif wd == 6:
        d = d - timedelta(2)   # Sun → Fri
    return d.strftime("%Y%m%d")


def replace_today(text: str) -> str:
    """将查询中作为独立词的'今日'替换为最近交易日日期，避免替换'无今日'等子串"""
    td = trading_day()
    # 只替换前面是空白、标点或字符串开始的"今日"
    # v6.9.44 审计修复：旧模式 (?:...)? 前缀组可选致任何位置"今日"都被替换
    # （实测 '无今日'→'无20260821'，防御失效）；去掉 '?' 后前缀必匹配，词中"今日"不动
    return re.sub(r'(^|[\s,，;；|])今日', lambda m: m.group(0).replace("今日", td), text)


def prev_trading_day(now: dt_dt | None = None) -> str:
    """trading_day() 的前一交易日 YYYYMMDD（日历可用时跳周末+节假日；不可用仅跳周末）"""
    t = dt_dt.strptime(trading_day(now), "%Y%m%d").date()
    d = t - timedelta(1)
    while not is_trading_day(d):
        d -= timedelta(1)
    return d.strftime("%Y%m%d")


def completed_day(now: dt_dt | None = None) -> str:
    """已完成数据日 YYYY-MM-DD（🆕 v7.2.13e S02：回填类入口默认 as-of 单一事实源）。

    边界与 sources/market_dump._last_completed 同口径（15:05 后当日行转正）：
    交易日 15:05 后=当日，此前=上一交易日；周末/节假日回退上一交易日。
    日历不可用降级为仅跳周末（is_trading_day 同款保守方向）。
    显式传入 as-of 的历史回放不受影响（调用方 today 参数优先）；缺省禁止用
    datetime.now().date() 代替——盘中跑回填会把当日未定型 bar 计入前向收益
    （复审 R14 实证：冻结 10:00 时钟把 9/4 盘中 bar 记成 ret_t1）。
    注意与 trading_day()（查询交易日，09:15 边界）职责不同：本函数是"哪一天
    的数据已经走完"，不是"今天该查哪天"。now 可注入（测试用）。"""
    n = now or dt_dt.now()
    day = n.date()
    if (n.hour * 60 + n.minute) < 15 * 60 + 5:
        day -= timedelta(days=1)
    for _ in range(12):
        if is_trading_day(day.strftime("%Y%m%d")):
            return day.strftime("%Y-%m-%d")
        day -= timedelta(days=1)
    # 12 天兜底（日历大面积过期等异常）：仅跳周末口径，不抛错阻断回填
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def is_intraday(now=None) -> bool:
    """盘中判定（交易日 09:15-15:00；09:15=集合竞价开始=当日情绪数据开始累计）。

    🆕 v6.9.21：quick TL;DR 盘中自动降级用——盘中涨跌停计数是半成品
    （竞价/开盘30分钟涨停≈全日1/3~1/2），动态比率必然假性偏低，生态定性禁用。
    15:00 起进入收盘复盘窗口=非盘中；09:15 前数据基本为空，由双源失败守卫兜底。
    🆕 v6.9.44：日历可用时节假日不算盘中（节假日 10:00 旧判 True 与"该日无数据"
    事实相悖，且使 EOD 缓存 TTL 误走盘中短 TTL 分支）；日历不可用保持旧口径。
    """
    n = now or dt_dt.now()
    if n.weekday() >= 5:
        return False
    if _get_calendar() is not None and not is_trading_day(n):
        return False
    return (n.hour, n.minute) >= (9, 15) and n.hour < 15
