#!/usr/bin/env python3
"""
iwencai_api.py — 问财 OpenAPI 统一调用模块
============================================
所有 hithink-* skill 共用同一端点 /v1/query2data，仅 skill_id 不同。
本模块提供统一接口，供 round1_v2.py 并行调用。

用法:
    from iwencai_api import query_iwencai
    result = query_iwencai("hithink-market-query", "贵州茅台 最新价 涨跌幅")
"""

import os, json, time, secrets, hashlib
import re
import urllib.request, urllib.error
from pathlib import Path

from common.netguard import http_fetch

BASE_URL = "https://openapi.iwencai.com"
ENDPOINT = "/v1/query2data"
DEFAULT_TIMEOUT = 25

# ── 磁盘缓存层（跨进程）─────────────────────────────────
# 背景：dispatch._RESULT_CACHE 仅进程内有效，CLI 每次调用都是新进程；
# 同一时段内 stock→kline→pattern 连续诊断会重复拉取相同问财数据。
# TTL 15 分钟：覆盖一轮分析会话，又不会像"当日缓存"那样把盘中行情
# 钉死（13:30 拉的行情 15:10 重新诊断时会重新拉取）。
# 🆕 v6.9.38 时间感知 TTL：非盘中写入的条目=该数据日完整收盘，锚定至下一
# 交易日 09:15（周末自动跨日，上限5天防长假堆积）——收盘复盘/盘前/周末
# 多次重跑同数据日不再重复消耗配额；盘中写入保持 15 分钟短 TTL。
_CACHE_DIR = Path(__file__).resolve().parent / "cache"
_CACHE_TTL = 900          # 15 分钟（盘中写入 / 兜底）
_PRUNE_AGE = 7 * 86400    # 🆕 v6.9.38 1天→7天：EOD 锚定条目需活过周末
# 🆕 v6.9.45 审计修复：pruner 文件名白名单——trade_calendar.json（common/calendar
# 交易日历缓存）与本缓存同目录且新鲜路径不重写文件，mtime 超 7 天会被误删，
# 节假日感知能力随之静默退化（calendar 降级仅跳周末）。
# 🆕 v7.2.13e F05：黑名单不断补其他模块文件名不可持续（market_dump_names.json、
# fuyao_daily_k.meta.json 同目录实删前科）——改为**本模块自有命名空间白名单**：
# 只清理 q2d_/search_ 前缀+32位md5 形态的自有文件，未知 JSON 一律不碰。
_PRUNE_SKIP = {"trade_calendar.json"}
_PRUNE_OWN_RE = re.compile(r"^(?:q2d|search)_[0-9a-f]{32}\.json$")
_last_prune = 0.0


def _cache_path(kind: str, key_parts: str) -> Path:
    h = hashlib.md5(f"{kind}|{key_parts}".encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{kind}_{h}.json"


def _cache_entry_valid(mtime_epoch: float, now=None) -> bool:
    """🆕 v6.9.38 时间感知有效性判定（可注入 now 供测试）。

    规则：①mtime 距今 ≤15min → 一律有效；②写入时点为盘中（09:15-15:00 交易日）
    → 数据半成品，超15分钟即失效；③写入时点为收盘后/盘前/周末 → 该数据日完整收盘，
    只要 trading_day 未推进且当前不在盘中即持续有效。
    v6.9.44 起节假日感知（common/calendar 已接 A股交易日历）；日历不可用时
    降级仅跳周末，假日盘中误判走保守短TTL方向，无害。
    """
    from datetime import datetime as _dtmod
    now = now or _dtmod.now()
    if now.timestamp() - mtime_epoch <= _CACHE_TTL:
        return True
    mt = _dtmod.fromtimestamp(mtime_epoch)
    try:
        from common.calendar import is_intraday, trading_day
        if is_intraday(mt):
            return False                      # 盘中写入=半成品数据
        if (mt.weekday() >= 5 or mt.hour >= 15
                or (mt.hour, mt.minute) < (9, 15)):
            # 收盘后/周末/盘前写入 = 完整收盘定格
            if is_intraday(now):
                return False                  # 当前已进入盘中 → 旧数据失效
            return trading_day(mt) == trading_day(now)
        return False                          # 其余（如假日盘中误判）走保守失效
    except Exception:
        return False                          # calendar 不可用→退回旧行为


def _disk_cache_get(kind: str, key_parts: str):
    try:
        p = _cache_path(kind, key_parts)
        if not p.exists():
            return None
        mtime = p.stat().st_mtime
        if not _cache_entry_valid(mtime):
            return None
        payload = json.loads(p.read_text(encoding="utf-8"))
        payload["cached"] = True
        return payload
    except Exception:
        return None


def _disk_cache_set(kind: str, key_parts: str, result: dict):
    global _last_prune
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "cached"}
        # 🆕 v6.9.45：tmp+os.replace 原子写（同 signal_log.rewrite_signals）——
        # 直接 write_text 写一半崩溃会留半截 JSON，读端静默当 miss 之外还可能
        # 把坏文件留给后续 mtime 判定。
        target = _cache_path(kind, key_parts)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        now = time.time()
        if now - _last_prune > 3600:
            _last_prune = now
            for f in _CACHE_DIR.glob("*.json"):
                try:
                    # v7.2.13e F05：只清自有命名空间（q2d_/search_+md5），其他模块
                    # 的 metadata/名称表/日历/未知 JSON 一律不删
                    if not _PRUNE_OWN_RE.fullmatch(f.name):
                        continue
                    if now - f.stat().st_mtime > _PRUNE_AGE:
                        f.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _is_transient_error(err: str) -> bool:
    """瞬时错误判定：认证类(403)重试无意义；HTTP 401 多为并发限流伪装成配额文案
    （2026-08-19 实测：同一次15路并行中3路401"次数已用完"、12路正常，单独重查即恢复），
    放行重试一次；其余（超时/5xx/服务端抖动）默认重试。"""
    if not err:
        return True
    e = err.lower()
    if "401" in e:
        return True  # 并发限流误报配额，退避重试可自愈；真配额耗尽=重试再失败一次，成本可接受
    if "次数已用完" in err or "额度" in err or "未设置" in err:
        return False
    if any(h in e for h in ("403", "unauthorized")):
        return False
    return True


def _retry_sleep(err: str) -> float:
    """重试前等待秒数：401并发限流给3秒让限流窗口过去，其余瞬时错误1.5秒。"""
    return 3.0 if "401" in (err or "").lower() else 1.5

# ── 核心函数 ──────────────────────────────────────────

def query_iwencai(skill_id: str, query: str, skill_ver: str = "1.0.0",
                  limit: int = 5, timeout: int = DEFAULT_TIMEOUT,
                  use_cache: bool = True, retries: int = 1) -> dict:
    """
    调用问财 OpenAPI 查询数据（带磁盘缓存 + 瞬时错误自动重试）。

    Args:
        skill_id:   skill 标识，如 "hithink-market-query"
        query:      自然语言查询语句
        skill_ver:  skill 版本，默认 1.0.0
        limit:      返回条数，默认 5
        timeout:    超时秒数
        use_cache:  是否启用磁盘缓存（pattern 降级重试时传 False 绕过）
        retries:    瞬时错误自动重试次数（仅网络/5xx/服务端抖动，配额/认证不重试）

    Returns:
        {"success": True/False, "datas": [...], "code_count": N, "elapsed": 秒,
         "skill_id": ..., "query": ..., "error": ...,
         "cached": True(命中磁盘缓存), "retried": True(重试后成功)}
    """
    key_parts = f"{skill_id}|{query}|{limit}"
    if use_cache:
        hit = _disk_cache_get("q2d", key_parts)
        if hit is not None:
            return hit

    r = _query_iwencai_once(skill_id, query, skill_ver, limit, timeout)
    for _ in range(retries):
        if r.get("success") or not _is_transient_error(r.get("error", "")):
            break
        time.sleep(_retry_sleep(r.get("error", "")))
        r = _query_iwencai_once(skill_id, query, skill_ver, limit, timeout)
        if r.get("success"):
            r["retried"] = True

    if r.get("success") and use_cache:
        _disk_cache_set("q2d", key_parts, r)
    return r


def _query_iwencai_once(skill_id: str, query: str, skill_ver: str,
                        limit: int, timeout: int) -> dict:
    """单次问财 /v1/query2data 请求（无缓存无重试）。"""
    api_key = os.environ.get("IWENCAI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "IWENCAI_API_KEY 未设置", "elapsed": 0}

    url = f"{BASE_URL}{ENDPOINT}"
    trace_id = secrets.token_hex(32)

    payload = json.dumps({
        "query": query,
        "page": "1",
        "limit": str(limit),
        "is_cache": "1",
        "expand_index": "true"
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": skill_id,
        "X-Claw-Skill-Version": skill_ver,
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": trace_id,
    }

    t0 = time.time()
    try:
        with http_fetch(url, timeout=timeout, data=payload,
                        headers=headers, method="POST") as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            elapsed = time.time() - t0

            datas = data.get("datas", [])
            code_count = data.get("code_count", 0)

            return {
                "success": True,
                "datas": datas,
                "code_count": code_count,
                "elapsed": elapsed,
                "skill_id": skill_id,
                "query": query,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
        return {"success": False, "error": f"HTTP {e.code}: {body}", "elapsed": elapsed}
    except Exception as e:
        elapsed = time.time() - t0
        return {"success": False, "error": str(e), "elapsed": elapsed}



def query_iwencai_search(query: str, channel: str = "news", timeout: int = 25,
                         use_cache: bool = True, retries: int = 1) -> dict:
    """问财 /v1/comprehensive/search（资讯/公告/研报），带磁盘缓存+瞬时重试。"""
    key_parts = f"{channel}|{query}"
    if use_cache:
        hit = _disk_cache_get("search", key_parts)
        if hit is not None:
            return hit

    r = _query_iwencai_search_once(query, channel, timeout)
    for _ in range(retries):
        if r.get("success") or not _is_transient_error(r.get("error", "")):
            break
        time.sleep(_retry_sleep(r.get("error", "")))
        r = _query_iwencai_search_once(query, channel, timeout)
        if r.get("success"):
            r["retried"] = True

    if r.get("success") and use_cache:
        _disk_cache_set("search", key_parts, r)
    return r


def _query_iwencai_search_once(query: str, channel: str, timeout: int) -> dict:
    """单次问财 /v1/comprehensive/search 请求（无缓存无重试）。"""
    api_key = os.environ.get("IWENCAI_API_KEY", "")
    if not api_key: return {"success": False, "error": "IWENCAI_API_KEY not set", "elapsed": 0}
    url = f"{BASE_URL}/v1/comprehensive/search"
    payload = json.dumps({"channels": [channel], "app_id": "AIME_SKILL", "query": query}).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal", "X-Claw-Skill-Id": f"{channel}-search",
        "X-Claw-Skill-Version": "1.0.0", "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none", "X-Claw-Trace-Id": secrets.token_hex(32)}
    t0 = time.time()
    try:
        with http_fetch(url, timeout=timeout, data=payload,
                        headers=headers, method="POST") as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw); elapsed = time.time() - t0
            items = data.get("data", [])
            return {"success": True, "datas": items, "code_count": len(items), "elapsed": elapsed, "channel": channel}
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed": time.time() - t0}

def fmt_search(datas: list) -> str:
    """搜索返回 {title,summary,url,publish_date} 转 Markdown。"""
    if not datas: return "_(no results)_\n"
    lines = []
    for i, item in enumerate(datas[:5]):
        lines.append(f"{i+1}. **{item.get('title','')}**")
        lines.append(f"   {item.get('summary','')[:120]}")
        lines.append(f"   _{item.get('publish_date','')}_")
    return "\n".join(lines) + "\n"
def fmt_table(datas: list, max_rows: int = 8, max_cols: int = 20) -> str:
    """将问财返回的 datas 转为 Markdown 表格文本。

    宏观/期货类查询会返回逐日时间序列（一日一列，可达 200+ 列），
    故除限制行数外，同时限制列数（问财时间序列最新日期在前，截断即保留近端）。
    """
    if not datas:
        return "_(无数据)_\n"

    # 取前 max_rows 行
    rows = datas[:max_rows]
    more = len(datas) - max_rows if len(datas) > max_rows else 0

    # 收集所有 key，并限制列数（防止时间序列 200+ 列撑爆输出）
    keys = list(rows[0].keys())
    more_cols = len(keys) - max_cols if len(keys) > max_cols else 0
    if more_cols:
        keys = keys[:max_cols]

    # 表头
    header = "| " + " | ".join(keys) + " |"
    sep = "|" + "|".join([" --- " for _ in keys]) + "|"

    # 数据行 (值截断到 40 字符)
    lines = [header, sep]
    for row in rows:
        vals = [str(row.get(k, ""))[:40] for k in keys]
        lines.append("| " + " | ".join(vals) + " |")

    if more_cols:
        lines.append(f"\n_... 还有 {more_cols} 列已省略（时间序列仅保留近端 {max_cols} 列）_")
    if more:
        lines.append(f"\n_... 还有 {more} 条数据_\n")

    return "\n".join(lines) + "\n"


def fmt_kv(datas: list) -> str:
    """将第一条数据的字段转为键值对展示。"""
    if not datas:
        return "_(无数据)_\n"

    row = datas[0]
    lines = []
    for k, v in row.items():
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines) + "\n"


def filter_fields(datas: list, keep_fields: list) -> list:
    """按字段白名单裁剪问财返回数据。

    keep_fields 支持基础字段名，自动匹配带日期后缀的变体如 收盘价[20260728]。
    始终保留股票代码、简称等元数据字段。
    """
    import re
    if not datas:
        return datas

    meta_fields = {"股票代码", "股票简称", "股票名称", "代码", "名称"}
    keep_set = set(keep_fields) | meta_fields

    filtered = []
    for row in datas:
        new_row = {}
        for key, val in row.items():
            base = re.sub(r'\[\d{8}\]$', '', key)
            if base in keep_set or key in keep_set:
                new_row[key] = val
        filtered.append(new_row)
    return filtered


# ── 预定义查询模板 ────────────────────────────────────

# 这些模板供 round1_v2 直接使用，避免在 round1_v2 中硬编码 skill_id

# (label, skill_id, query, limit) — limit 用于控制返回条数，1=只要计数
MARKET_IWENCAI = [
    # 情绪层
    ("涨停板", "hithink-astock-selector", "今日涨停家数 非ST A股", 1),
    ("跌停板", "hithink-astock-selector", "今日跌停家数 非ST A股", 1),
    ("炸板股", "hithink-astock-selector", "今日曾涨停但未封板 A股", 15),
    ("连板天梯", "hithink-astock-selector", "连续涨停天数>=2 A股 今日", 20),
    # 资金层（v6.9.41 改名：净流出榜原 label"板块资金"与 quick 的净流入榜同名双义，
    # 完整复盘模式易被误读成流入榜——与 core 的"板块资金流出"命名统一）
    ("板块资金流出", "hithink-sector-selector", "概念板块 今日主力资金净流出排名 跌幅", 10),
    # 期货
    ("期指行情", "hithink-futures-query", "IF主力 IC主力 IH主力 IM主力 最新价 涨跌幅 持仓量 成交额 基差", 5),
    # v5.7: 期指持仓替换为AKShare中金所路（问财仅返回IC缺失IF/IH/IM），见 round1_v2.py run_akshare_cffex()
    # ("期指持仓", "hithink-futures-query", "IF主力合约 IC主力合约 IH主力合约 IM主力合约 中信期货 会员多头持仓 会员空头持仓 净持仓", 8),
    ("国债收益率", "hithink-macro-query", "10年期国债收益率 2年期国债收益率 10年减2年期限利差 中美利差 近10日", 5),
    ("期货异动", "hithink-futures-selector", "今日 主力合约 持仓量变化最大 涨跌幅异常", 5),
    # 宏观
    ("宏观价格", "hithink-macro-query", "最新 CPI同比 PPI同比 社零增速 PMI", 3),
    ("宏观货币", "hithink-macro-query", "M2同比增速 社会融资规模 LPR利率", 3),
    # 资金流（北向2024.8起盘中不披露，此处拉盘后/累计值 + 杠杆资金）
    ("外资杠杆", "hithink-market-query", "北向资金 累计净流入 沪股通净流入 深股通净流入 融资余额 融资买入额", 5),
    # 大宗现价（周期股传导数据源）
    ("大宗商品", "hithink-futures-query", "WTI原油 黄金 伦铜 螺纹钢 铁矿石 动力煤 最新价 涨跌幅", 8),
    # 监管
    ("监管扫描", "search:news", "A股 严重异常波动 停牌核查 监管函 批量异动公告 最新", 10),
    # 牛熊分界线（上证指数 360日均线 = 年线，MA360之上=牛市背景，之下=熊市背景）
    ("牛熊分界线", "hithink-market-query", "上证指数 最新价 360日均线 ma360 250日均线", 3),
    # 国家队ETF（申赎份额 T+1 披露：能拉到的最新份额=前一交易日快照，输出时必须标注实际数据日期）
    ("国家队ETF", "hithink-market-query", "510300 510050 510500 512100 588000 588080 159915 159919 510330 563300 基金份额变化 最新净值", 10),
    # 🆕 v6.1 融合 deep：外围定价锚（美债/美元/VIX/A50）→ 放入聪明资金监测
    ("外围定价锚", "hithink-macro-query", "10年期美债收益率 2年期美债收益率 美元指数 VIX恐慌指数 富时A50期货 中美利差 最新", 5),
    # 🆕 v6.1 融合 deep：行业轮动 → 放入板块资金
    ("行业轮动", "hithink-industry-query", "申万一级行业 景气度评分 动量排名 估值分位 资金流向", 10),
]

STOCK_IWENCAI = [
    ("个股行情", "hithink-market-query", "{symbols} 最新价 涨跌幅 实际换手率 自由流通值 主力资金净流入 主动大单买入额 主动大单卖出额 5日均线 10日均线 20日均线 60日均线 量比"),
    ("周线技术", "hithink-market-query", "{symbols} 周K线 周线MA5 周线MA10 周线MA20 20周均线方向"),
    ("财务速览", "hithink-finance-query", "{symbols} 营业收入 归母净利润 经营现金流净额 ROE 毛利率 资产负债率 营收同比 净利润同比 PE PB 历史分位"),
    ("基本资料", "hithink-basicinfo-query", "{symbols} 主营业务 实控人 上市日期 所属行业 总股本"),
    ("经营数据", "hithink-business-query", "{symbols} 主营构成 主营产品收入占比 在建工程 固定资产 主要客户 市场占有率"),
    ("事件提醒", "hithink-event-query", "{symbols} 近期业绩预告 分红 机构调研 监管函"),
    ("解禁减持", "hithink-event-query", "{symbols} 限售股解禁 解禁日期 解禁数量 占流通盘比 股东减持计划 减持比例"),
    ("股东股本", "hithink-management-query", "{symbols} 前十大股东 股东户数 股权质押 实控人"),
    ("龙虎榜", "hithink-market-query", "{symbols} 今日龙虎榜 买入席位 卖出席位 机构净买入 净买入额"),
    ("可转债", "hithink-cb-selector", "{symbols} 可转债 转股溢价率 正股 剩余期限", 3),
    ("个股资讯", "search:news", "{symbols} 最新新闻 研报"),
    ("公告原文", "search:announcement", "{symbols} 最新公告"),
    # 板块新闻联动：同步查该股所属行业/概念的政策动态
    ("板块新闻", "search:news", "{symbols} 所属行业 所属概念 政策 新闻 最新", 5),
    # 🆕 v6.1 融合 deep：机构评级
    ("机构评级", "hithink-insresearch-query", "{symbols} 近一个月 券商 买入评级 目标价 盈利预测", 5),
]

# ETF 通用模板（适用所有行业/宽基ETF，不硬编码任何单一行业）
STOCK_ETF_IWENCAI = [
    ("ETF行情", "hithink-market-query",
     "{symbols} 最新收盘价 涨跌幅 换手率 市值 主力净买入额 ma5 ma10 ma20 量比 场内流通份额", 5),
    ("申购赎回", "hithink-event-query",
     "{symbols} 申购份额 赎回份额 净申购", 3),
    ("ETF资料", "hithink-basicinfo-query",
     "{symbols} etf类型 跟踪指数 基金经理 规模 成立日期", 3),
    ("ETF资讯", "search:news", "{symbols} 最新", 5),
    ("ETF公告", "search:announcement", "{symbols} 最新公告", 3),
]

# DEEP_IWENCAI 已删除（v6.1 起外围定价锚/行业轮动融入 market，机构评级融入 stock，其余删除）
DEEP_IWENCAI = []


