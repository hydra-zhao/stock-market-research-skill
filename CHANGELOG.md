# Changelog（公开演示版）

本仓库是生产仓库的**公开作品展示版**（fresh git history，与生产仓库
历史无关联）。生产版的全量版本历史（v1→v7.3.5，含每版审计与测试锁定
记录）不属于公开内容。

## public-v1.0 · 2026-09-12（首发）

首次公开。保留生产仓库的管道与工程基建，策略层以 interface + mock 替代。

**保留（与生产同构）**

- Provider 能力路由层（capabilities.yaml 唯一事实源、DataResult 血缘、
  同族非独立验证审计）与全部数据商适配器
- FINAL-001 跨 Agent 交付链全五件套（context/render/lint/manifest/verify）
  与 quick_context.schema.json
- netguard 网络守卫、交易日历、路径单点定义等共享底座
- 多源降级源（同花顺三路 / AKShare 两路）与 fail-closed 风险负面扫描
- K线技术指标、前复权可用性判定
- 密闭测试基建（全局禁网闸）与 CI

**脱敏（结构保留、数值/内容替换为演示值）**

- builders.py 尾盘/波段选股画像查询 → 占位
- quick_context.py 主线确认/接力状态机判定阈值 → SAMPLE_* 演示常量，
  状态机判定折叠为 sanitized 中性态
- quick_renderer.py 内部规则 ID → 泛化文案
- tech/cycle.py 十大行业判据 → 虚构示例行业

**替换为 interface + mock**

- 决策层：strategy/interfaces.py（Protocol）+ example_strategy.py（示例）
- round1_v2.py：全量采集编排 → 精简编排 + demo 入口
- review_hooks.py / market_dump.py / case_lib.py → 骨架与 stub

**删除（不进入公开仓库）**

- 全部私有策略实现（signal_score / seat_profile / selection_evolution /
  backtest_rules / daywatch_* / wave_scan / tick_scan / cross_asset 等）
- rules/references/systems/tactics/core/knowledge 的生产内容（留格式示例）
- 交易日K缓存（189MB）、运行产物（output/）、个人看盘日记（journals/）、
  生产 CHANGELOG（284KB）、私有路径与持仓台账引用
- 原 git 历史（公开版全新初始化）
