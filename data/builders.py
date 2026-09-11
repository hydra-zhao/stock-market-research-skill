#!/usr/bin/env python3
"""builders.py — 构造 round1_v2 各类查询任务"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.calendar import replace_today, trading_day, prev_trading_day
from iwencai_api import MARKET_IWENCAI, STOCK_IWENCAI, STOCK_ETF_IWENCAI


def build_market():
    """大盘复盘任务列表（🆕 v6.1 融合 deep 外围定价锚+行业轮动）"""
    tasks = [(label, f"iw:{sid}", replace_today(q), lim)
             for label, sid, q, lim in MARKET_IWENCAI
             if label != "期指持仓"]
    tasks += [
        ("美股期货NQ00Y", "mx", "NQ00Y 小型纳指当月连续 最新价 涨跌幅 最高价 最低价 昨收价", 5),
        ("历史涨跌停", "mx", "今年以来 A股每日跌停股票数量 涨停股票数量", 30),
        # 🆕 v6.2 量能比基准（近30日成交额均值，配合第三章情绪量化的量能比判定）
        ("历史成交额", "mx", "近30日 A股每日成交额", 30),
    ]
    tasks.append(("期指持仓", "ak", trading_day(), 0))
    return tasks


# 🆕 v6.7 减法测试影子模式核心路：情绪四路 + 牛熊线 + 板块资金 + 国家队ETF + 期指持仓
# 🆕 A2修复（2026-08-22 审计）：旧实现经 MARKET_IWENCAI 对同名 label 二次定义，
# 查询串/limit 与 quick 均不同 → 磁盘缓存 key 永不相等、quick/core 零缓存共享，
# core 每日多烧 5-7 路全价配额（v6.7.1"重叠6路缓存命中"声明在旧代码下为假），
# 且同名"板块资金"两路口径分叉（quick=净流入榜 / core=净流出榜）。
# 与 quick 共享的任务标签：元组与 build_market_quick() 逐字节一致（缓存 key 相同才可命中）
CORE_SHARED_QUICK_LABELS = {"涨停板", "跌停板", "炸板股", "连板天梯", "牛熊分界线", "板块资金"}
# v6.9.44 审计清理：删除 CORE_MARKET_LABELS（生产零引用——build_market_core 实际用
# CORE_SHARED_QUICK_LABELS 构造，旧清单仅被 test_signal 单向断言引用，改实现不改它测试仍绿）


def build_market_core():
    """🆕 v6.7 market core 影子模式：核心 9 路（A2修复后与 quick 共享缓存）。

    - 共享 6 路：直接复用 build_market_quick() 的任务元组（同 key → 磁盘缓存命中，
      quick+core 连跑时仅 ETF/期指/流出榜消耗新配额）
    - 板块资金流出榜：沿用原 MARKET_IWENCAI 的净流出查询，改名消除同名歧义
    - 国家队ETF / 期指持仓：维持原有专路不变
    """
    tasks = [t for t in build_market_quick() if t[0] in CORE_SHARED_QUICK_LABELS]
    # v6.9.41：MARKET_IWENCAI 净流出榜已改名"板块资金流出"，无需再改名单独构造
    tasks += [t for t in build_market() if t[0] == "板块资金流出"]
    tasks += [t for t in build_market() if t[0] == "国家队ETF"]
    tasks.append(("期指持仓", "ak", trading_day(), 0))
    return tasks


def build_quick_complete():
    """快速复盘一次性完整采集包。

    在 quick 的情绪/指数/流入榜基础上，只追加 market core 的三个独有路：
    流出榜、国家队 ETF、期指。共享六路不重复调度，避免上层为了补“聪明资金”
    再跑一遍 market core。全部任务仍由同一个 dispatch 并行完成，最终一次性渲染。
    """
    tasks = list(build_market_quick())
    labels = {t[0] for t in tasks}
    for task in build_market_core():
        if task[0] not in labels:
            tasks.append(task)
            labels.add(task[0])
    return tasks


def build_market_quick():
    """快速复盘任务列表（🆕 v6.5 +接力情绪四路；2026-09-10 审计核对=15 路=13问财+2MX）

    v6.2: 涨停/跌停/量能/炸板判定基准从静态绝对值（心法年代阈值，注册制后失真）
    改为 今日值÷近30日均值（沿用 dynamic_thresholds.py v5.2 校准口径——该脚本
    已随 v6.9.44 审计归档至 tactics/.archive/，口径由本文件内联继承）。
    v6.5: +昨日涨停今日溢价（养家三问①直接数据源）/昨日连板晋级率（精确值替代估算）
    /一字板占比（情绪虚实）/涨跌家数（市场广度，走 market-query 独立配额桶）。
    昨日两路用显式 T/T-1 日期拼接（"昨日"在凌晨会被问财解析到错误基准日），
    非ST口径（ST 5%涨跌幅会污染溢价均值与晋级判定）；涨停/跌停总量路维持全口径。
    """
    t, pt = trading_day(), prev_trading_day()
    tasks = [
        ("涨停板", "iw:hithink-astock-selector", replace_today("今日涨停股票"), 100),
        ("跌停板", "iw:hithink-astock-selector", replace_today("今日跌停股票"), 100),
        ("炸板股", "iw:hithink-astock-selector", replace_today("今日炸板股票"), 100),
        ("连板天梯", "iw:hithink-astock-selector", replace_today("今日连板股票"), 50),
        ("牛熊分界线", "iw:hithink-market-query", replace_today("上证指数 MA360 MA250"), 1),
        ("板块资金", "iw:hithink-sector-selector", replace_today("今日主力净流入前10板块"), 10),
        ("隔夜美股", "iw:hithink-zhishu-query", "纳斯达克 标普500 道琼斯 最新价 涨跌幅", 3),
        # 🆕 v6.2 动态阈值基准（近30日均值）：涨停比/跌停比/量能比
        # 注：炸板率用绝对带宽（25%/35%）——比率自归一，不受涨停基数膨胀影响；
        #     MX 无炸板历史序列（"炸板"查询被错误映射为涨停家数，已实测验证）
        ("历史涨跌停", "mx", "近30日 A股每日涨停家数 跌停家数", 30),
        ("历史成交额", "mx", "近30日 A股每日成交额", 30),
        # 🆕 v6.5 接力情绪四路（增强数据，缺失时 TL;DR 对应行自动省略，不触发 MX 降级补跑）
        # 涨跌家数走 market-query 桶（与 astock-selector 分桶，不加重首选配额压力）；
        # ⚠️ MX 无涨跌家数能力（"上涨家数"类查询返回"无 dataTableDTOList"，2026-07-29 实测 3 种措辞）
        ("昨日涨停表现", "iw:hithink-astock-selector", f"{pt}涨停股票 {t}涨跌幅 非ST", 100),
        ("昨日连板表现", "iw:hithink-astock-selector", f"{pt}连板股票 {t}涨跌幅 非ST", 100),
        ("一字板", "iw:hithink-astock-selector", replace_today("今日一字涨停股票"), 50),
        ("涨跌家数", "iw:hithink-market-query", replace_today("今日上涨家数 下跌家数"), 1),
        # 🆕 v6.9 P5 封板率分层：20cm(双创=创业板+科创板)计数，10cm=总量-20cm；
        # 列表脚注总数口径（实测2026-08-03："家数"措辞被映射为指数，列表code_count可用），失败自动省略
        ("涨停20cm家数", "iw:hithink-astock-selector", replace_today("今日收盘涨停 双创 非ST"), 1),
        ("炸板20cm家数", "iw:hithink-astock-selector", replace_today("今日曾涨停但未封板 双创 非ST"), 1),
    ]
    return tasks


def build_market_quick_fallback():
    """🆕 v6.3 问财配额耗尽时的 MX 降级任务组（quick/market 共用）

    仅在问财核心路失败后补跑，正常情况不消耗 MX 调用：
    - mx_data 单点：今日涨停/跌停家数（✅ 已实测，与问财口径差≤2家）
    - mx_xuangu 选股：连板天梯（含连续涨停天数列）、炸板股（曾涨停未封板）
    ⚠️ MX 无炸板历史时间序列（查询会被错误映射为涨停家数），勿加
    """
    return [
        ("MX今日涨跌停", "mx", "今日A股涨停家数 跌停家数", 1),
        ("MX连板天梯", "xg", "今日连续涨停天数>=2的A股 非ST", 50),
        ("MX炸板股", "xg", "今日曾涨停但收盘未涨停的A股 非ST", 100),
        # MX 可查指数最新价/涨跌幅，但无 MA360/MA250（均线字段被静默丢弃，已实测）
        ("MX指数行情", "mx", "上证指数 最新价 涨跌幅", 1),
    ]


# 🆕 v7.0.9 THS 情绪面降级覆盖的段落（与问财路同名，round1_v2 解析器零改动）
THS_ZT_SECTIONS = ("涨停板", "跌停板", "炸板股", "连板天梯", "一字板")


def build_ths_fallback(sections=None):
    """🆕 v7.0.9 问财情绪五路失败 → THS 涨停行情 dataapi 降级（sources/ths_limitup.py，零配额）

    涨停池带 reason_type 涨停原因（问财同款+拆词）= 首板题材归类降级数据源；
    跌停/炸板为计数口径（池响应自带家数，个股明细仍由 MX 路）；一字板=封板类型
    精确口径（优于 AK 东财竞价近似）。仅在 MX 降级之后、AK 股池之前补跑——
    对应 iw 段已被补上的不再重复调用，正常情况零消耗。
    """
    tasks = [("涨停板", "ths_zt", "zt_pool", 100),
             ("跌停板", "ths_zt", "dt_count", 5),
             ("炸板股", "ths_zt", "bomb_count", 5),
             ("连板天梯", "ths_zt", "ladder", 50),
             ("一字板", "ths_zt", "yizi", 50)]
    if sections:
        tasks = [t for t in tasks if t[0] in sections]
    return tasks


def build_sector_fallback(kind: str = "industry"):
    """🆕 v7.0.9 板块资金路失败 → 同花顺资金流降级（sources/ths_fundflow.py，零配额）

    板块资金是唯一无 MX/AK 兜底的问财路（TL;DR 领涨板块行+主线确认③数据源）。
    kind=industry（行业口径）| concept（概念口径），净额降序 TOP10。
    """
    return [(LABEL_SECTOR, "ak_ff", kind, 10)]


LABEL_SECTOR = "板块资金"


def build_kline_ths(code: str, days: int = 60):
    """🆕 v7.0.9 历史K线路失败 → 同花顺行情 K线降级（sources/ths_line.py，零配额）

    查询串="code days"（runner 内解析）；输出经 tech.kline.fmt_kline 同构渲染，
    均线/MACD/KDJ/量价异常/关键位阶梯全继承。"""
    return [("历史K线", "ths_kline", f"{code} {days}", days)]


def build_etf_fallback():
    """🆕 国家队ETF 问财路失败（配额/限流）→ AKShare 交易所份额降级（sources/etf_ak.py）

    沪市 8 只按日期取份额算净申购（Δ份额×收盘价代理净值）；
    深市 2 只（159915/159919）深交所仅最新快照无历史 → 展示不计 Δ（输出诚实标注）。
    仅在 market/market core 的「国家队ETF」iw 路失败后补跑，正常情况零消耗。
    """
    return [("国家队ETF", "ak_etf", "", 10)]


def build_ztpool_fallback(sections=None):
    """🆕 接力情绪四路（昨日涨停溢价/昨日连板晋级率/一字板/涨跌家数）问财失败
    → AKShare 东财股池降级（sources/zt_pool_ak.py，零配额）。

    与问财路口径同源验证（2026-08-19：股池溢价均值 -2.56% == 问财路 -2.56%）；
    段落标签与问财路同名，round1_v2 解析器零改动直接消费。
    仅在对应 iw 路失败后补跑，正常情况零消耗；一字板为近似口径（竞价封死+0炸板）。
    """
    tasks = [("昨日涨停表现", "ak_zt", "premium", 100),
             ("昨日连板表现", "ak_zt", "promotion", 100),
             ("一字板", "ak_zt", "yizi", 50),
             ("涨跌家数", "ak_zt", "ad", 5)]
    if sections:
        tasks = [t for t in tasks if t[0] in sections]
    return tasks


def build_stock_fallback(symbols: str):
    """🆕 v6.4 个股诊断问财配额耗尽时的 MX 降级任务组

    已实测（2026-07-28, 300740）：
    - 行情/财务/龙虎榜 mx_data 全覆盖（龙虎榜返回席位为列的买卖额表）
    - 基本资料仅返回上市日期（降级可用但标注不全）
    - 解禁减持返回格式混乱（历史日期转置）→ 不降级，输出中标注缺失
    - 股东股本/机构评级/可转债 → MX 无覆盖，金十 search 可补资讯面
    """
    return [
        ("MX个股行情", "mx", f"{symbols} 最新价 涨跌幅 换手率 量比 市盈率 市净率 总市值 主力净流入", 3),
        ("MX财务速览", "mx", f"{symbols} 营业收入 归母净利润 ROE 毛利率 资产负债率", 5),
        ("MX基本资料", "mx", f"{symbols} 主营业务 所属行业 实控人 上市日期", 3),
        ("MX龙虎榜", "mx", f"{symbols} 今日龙虎榜 买入席位 卖出席位 净买入额", 5),
    ]


def is_etf(code: str) -> bool:
    return code.replace(" ", "").startswith(("51", "15", "16", "56", "58"))


def build_risk_scan(codes):
    """🆕 v7.0.12 风险负面扫描任务（sources/risk_scan.py，零配额，fail-closed）

    立案/行政处罚/监管函/减持/退市风险 标题扫描——问财风险层（监管扫描/事件提醒/
    候选三查）的零配额降级备份：东财公告→巨潮双源，全源失败输出"⚠️ 无法核查"
    手动检查横幅而非空结果。codes=list[6位代码]（多代码单任务聚合渲染）。
    """
    codes = list(codes or [])
    return [("风险扫描", "em_risk", ",".join(codes), len(codes) or 1)]


def build_stock(symbols: str):
    """个股诊断任务列表（🆕 v6.1 融合 deep 机构评级 + 自动附带60日K线）"""
    template = STOCK_ETF_IWENCAI if is_etf(symbols) else STOCK_IWENCAI
    tasks = []
    for item in template:
        label, sid, q = item[0], item[1], item[2]
        lim = item[3] if len(item) > 3 else 5
        tasks.append((label, f"iw:{sid}", replace_today(q.replace("{symbols}", symbols)), lim))
    # 🆕 自动附带60日K线（量价异常检测+关键位阶梯；展示仍截断30行，
    # 60日窗口保证 MA60/MACD/摆动点聚类有足够样本）
    tasks.append(build_kline(symbols, 60)[0])
    # 🆕 v7.0.12 风险扫描常驻段（零配额 fail-closed）：个股诊断是"能不能做"的
    # 裁决出口=荐股出口之一，必过风险硬闸；问财事件提醒/解禁减持路之外的独立
    # 第二层（8/28 航锦科技立案事故：问财死日风险层整体失明）。ETF 不适用。
    codes6 = [c for c in re.findall(r"(?<!\d)\d{6}(?!\d)", symbols) if not is_etf(c)]
    if codes6:
        tasks += build_risk_scan(codes6)
    return tasks


def build_kline(code, days=60):
    """历史日K线查询任务"""
    q = f"{code} 最近{days}日 交易日期 开盘价 收盘价 最高价 最低价 成交量 换手率"
    return [("历史K线", "iw:hithink-market-query", q, days)]


def build_trend():
    """🆕 v6.9 中期趋势独立模式（trend）：P1估值锚+P2市场宽度+P3周线结构，8路。

    与 quick/market 完全隔离（一路不加）：仅在用户问"趋势/中期/大涨还是大跌/方向"时
    手动触发（`round1_v2.py trend`）。中期层三铁律：①不参与四人裁决（零投票权）
    ②情绪层定操作、中期层定态度 ③只做减法不做加法（只压仓位上限，不产生开仓信号）。
    """
    return [
        # P1 估值锚：沪深300 PE/PB及历史分位；ERP=1/PE-10Y国债（tech/trend.py 现算）
        ("估值水位", "iw:hithink-market-query",
         "沪深300 市盈率 市净率 市盈率历史分位 市净率历史分位", 2),
        ("国债10Y", "iw:hithink-macro-query", "中国10年期国债收益率 最新", 2),
        # P1 汇率：USDCNH 现价（macro-query 实测可用；序列/20日变动问财+MX均不支持→标注缺失）
        ("汇率USDCHN", "iw:hithink-macro-query", "美元离岸人民币 最新价", 1),
        # P2 市场宽度：selector 脚注总数口径（limit=1 只要计数）
        ("宽度MA250上", "iw:hithink-astock-selector", "收盘价高于250日均线的A股 非ST", 1),
        ("宽度全A", "iw:hithink-astock-selector", "全部A股 非ST", 1),
        ("宽度新高", "iw:hithink-astock-selector", "创20日新高的A股 非ST", 1),
        ("宽度新低", "iw:hithink-astock-selector", "创20日新低的A股 非ST", 1),
        # P3 周线：150日日K收盘 → tech/trend.py 聚合周线 + 5/10/20周均线
        ("趋势日K", "iw:hithink-market-query", "上证指数 最近150日 交易日期 收盘价", 150),
    ]


def build_tailscan():
    """尾盘隔夜选股（14:00-14:55盘中跑）：候选池画像 + 板块资金。

    🎭 公开演示版：候选池的多条件筛选画像（量价/市值/涨停史等组合条件）
    属于私有选股策略，此处以占位查询代替 —— 结构（任务元组/数据源路由/
    降级链）与生产版完全一致，仅查询条件不可见。

    板块资金拆流入/流出两路（复合问法实测返回空，拆两路是问财可用的措辞）。
    """
    return [
        ("尾盘候选池", "iw:hithink-astock-selector",
         "<生产版：私有选股画像条件（已脱敏）>", 50),
        ("板块资金流入", "iw:hithink-sector-selector", "今日主力净流入前10板块", 10),
        ("板块资金流出", "iw:hithink-sector-selector", "今日主力净流出前10板块", 10),
    ]


def build_swing_scan():
    """3-20交易日趋势波段初筛。

    🎭 公开演示版：趋势波段候选的多条件筛选画像属于私有选股策略，
    此处以占位查询代替；板块资金两路与生产版一致。
    """
    return [
        ("趋势波段候选", "iw:hithink-astock-selector",
         "<生产版：私有选股画像条件（已脱敏）>", 50),
        ("板块资金流入", "iw:hithink-sector-selector", replace_today("近5日主力净流入前20板块"), 20),
        ("板块资金流出", "iw:hithink-sector-selector", replace_today("近5日主力净流出前20板块"), 20),
    ]


def build_cycle(industry_key: str = None):
    """🆕 v6.8 周期定位任务列表（tech/cycle.py 参数化，替代 industry-cycles.md 手写"当前阶段"）

    industry_key=None → 仪表盘模式：十六大行业全路查询（29 路并行，各行业 label 全局唯一，
                       与规则引擎段落锚定兼容），每行业出"底x/顶y"一行摘要。
    industry_key=行业键 → 单行业全路查询 + 规则引擎完整判定报告。
    """
    from tech.cycle import CYCLES
    if industry_key:
        return [(label, src, q, lim) for label, src, q, lim in CYCLES[industry_key]["queries"]]
    tasks = []
    for cfg in CYCLES.values():
        tasks.extend((label, src, q, lim) for label, src, q, lim in cfg["queries"])
    return tasks
