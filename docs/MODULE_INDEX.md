# 生产模块索引（公开演示版 data/**/*.py）

> 维护契约：**新增或删除 `data/**/*.py` 必须同步本表**——
> `tests/test_public_structure.py::test_module_index_matches_tree` 强制
> （索引登记了不存在的模块即失败），与生产仓库的守护测试同构。
>
> 🎭 = 该位置在生产仓库是私有策略实现，公开版为 interface + mock/示例。
> 生产版完整索引共 90 模块；本公开版收录其中的管道与数据面部分。

## 采集编排入口（CLI）

| 模块 | 一句话职责 | 公开版形态 |
|---|---|---|
| `data/round1_v2.py` | 数据采集编排 CLI 入口（生产版含 quick/market/stock/kline/pattern/tailscan 等子命令与生态判定 `_quick_eval`） | 🎭 精简版：`_quick_eval` 兼容委托 + `demo` 子命令 |
| `data/builders.py` | 构造各类查询任务（任务元组 → dispatch） | 保留；两个选股画像查询已脱敏为占位 |
| `data/dispatch.py` | 任务调度器，并行协调各数据源 runner | 保留 |
| `data/iwencai_api.py` | 问财 OpenAPI 统一调用模块（key 只从环境变量读取） | 保留 |

## FINAL-001 快速复盘交付链（唯一入口 data/quick_pipeline.py）

| 模块 | 一句话职责 | 公开版形态 |
|---|---|---|
| `data/quick_pipeline.py` | 跨 Agent 交付稳定入口（`--final` / `--verify`） | 保留（原样） |
| `data/quick_context.py` | 快照 → canonical 事实归一化 + schema/语义校验 | 保留；主线确认/接力状态机的判定阈值替换为演示常量 |
| `data/quick_contract.py` | 共享交付原语（原子写/sha256/stage/seat 策略），无交易决策 | 保留（原样） |
| `data/quick_renderer.py` | 确定性渲染器，只接受 canonical context | 保留；文案中的内部规则 ID 泛化 |
| `data/quick_delivery.py` | 终态管道：context → render → lint → manifest → verify | 保留（原样） |
| `data/lint_review.py` | 复盘输出结构校验器（auto 判 quick/full） | 保留（原样） |
| `data/review_hooks.py` | 收尾钩子编排（生产版五钩子） | 🎭 骨架：仅保留 quick_context 依赖的两个函数签名 |
| `data/schemas/quick_context.schema.json` | canonical context 的 JSON Schema | 保留（原样） |

## 决策层（生产私有；公开版=接口+示例）

| 模块 | 一句话职责 | 公开版形态 |
|---|---|---|
| `data/strategy/interfaces.py` | 决策层 Protocol：MarketRegimeJudge / StockScorer / RiskGate | 新增（接口抽离） |
| `data/strategy/example_strategy.py` | 确定性示例实现（演示阈值 SAMPLE_*） | 🎭 新增（替代私有策略） |
| `data/case_lib.py` | 生产版=形态案例库；公开版仅保留腾讯日K取数函数 | 🎭 精简 stub |

## Provider 层（路由唯一事实源 = data/providers/capabilities.yaml）

| 模块 | 一句话职责 |
|---|---|
| `data/providers/__init__.py` | Unified stock data facade. |
| `data/providers/registry.py` | Capability-driven routing（能力路由唯一事实源）. |
| `data/providers/base.py` | Minimal provider protocol. |
| `data/providers/models.py` | DataResult / provenance 契约. |
| `data/providers/errors.py` | Typed provider failures. |
| `data/providers/cache.py` | 完整日/部分日感知的 provider cache. |
| `data/providers/compat.py` | legacy 任务元组 → capability 路由桥. |
| `data/providers/runner.py` | provider 结果 → round1 runner 契约桥. |
| `data/providers/health.py` | Provider 健康检查（永不打印 secrets）. |
| `data/providers/audit.py` | A/B 血缘审计（同族对比不算独立验证）. |
| `data/providers/local_compute.py` | 本地确定性计算（零网络）. |
| `data/providers/legacy.py` | IW/MX/THS/AK 兼容适配. |
| `data/providers/fuyao.py` / `iwencai.py` / `mx.py` / `ak.py` / `ths.py` / `jin10.py` | 各数据商 provider 适配器 |
| `data/providers/risk_official.py` | 官方公告风险链（fuyao 异动不得验证此链）. |
| `data/providers/eastmoney_qfq.py` | 东财 push2his 全程前复权历史. |
| `data/providers/tencent_qfq.py` | 腾讯 qfq 历史（experimental，显式 opt-in）. |

## 数据源与运行器（data/sources/）

| 模块 | 一句话职责 | 公开版形态 |
|---|---|---|
| `data/sources/market_dump.py` | 全市场日K底座（生产版 parquet 整包） | 🎭 stub：ensure 抛不可用 / frame=None |
| `data/sources/risk_scan.py` | 零配额风险负面扫描（fail-closed） | 保留 |
| `data/sources/ths_limitup.py` / `ths_line.py` / `ths_fundflow.py` | 同花顺三路降级源 | 保留 |
| `data/sources/zt_pool_ak.py` / `etf_ak.py` | AKShare 东财族降级路 | 保留 |
| `data/sources/net_guard.py` | 网络守卫（legacy 入口薄封装） | 保留 |

## 分析引擎与共享底座（data/tech/、data/common/）

| 模块 | 一句话职责 | 公开版形态 |
|---|---|---|
| `data/tech/kline.py` | K线格式化 + 技术指标计算 | 保留 |
| `data/tech/qfq.py` | 前复权可用性判定 | 保留 |
| `data/tech/cycle.py` | 周期定位规则引擎（十大行业参数化） | 🎭 示例引擎：虚构示例行业，生产判据不公开 |
| `data/common/paths.py` | 跨模块共享路径单点定义 | 保留；默认持仓路径指向示例模板 |
| `data/common/netguard.py` | 全局网络守卫（https+白名单+IP边界） | 保留（原样） |
| `data/common/calendar.py` | 交易日工具 | 保留（原样） |
| `data/common/review_state.py` | 复盘状态文件 | 保留（原样） |
| `data/common/timing.py` | 数据源耗时摘要 | 保留（原样） |
| `data/config/zodiac_themes.json` | 题材过滤白名单（人工维护，默认空） | 保留（原样，空配置） |

## 生产版存在、公开版不提供（策略核心，mock 边界）

`signal_score`（判定闭环与阈值寻优）、`seat_profile`（席位画像）、
`selection_evolution`（筛选器自动进化）、`backtest_rules`（规则反事实回测）、
`shouban_group`（题材归类引擎）、`wave_scan` / `tick_scan` / `cross_asset` /
`us_etf_valuation`、`daywatch_plan/run/leaders`（盯盘预案线）、`daily_journal`、
`catalyst_watch`、`hist_backfill`、`signal_log`、`watchlist_diff`、`source_drift`、
`data/mx/*`（自选接口）、`data/tech/pattern*`（形态匹配管线）、`tech/trend.py`（中期四锚）。
以上在 `data/strategy/README.md` 与主 README 的模块地图中标注为 mock/示例边界。
