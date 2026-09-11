---
name: stock-public
description: >-
  A 股多周期交易分析 Skill（公开作品展示版）。展示 AI Agent 的声明式路由、
  硬闸优先级、渐进加载与跨 Agent 交付契约。生产版的选股逻辑、评分权重、
  阈值与私有 prompt 不在本仓库公开，决策层以 interface + 示例策略替代。
  触发词：全面分析、复盘大盘、个股诊断、持仓管理、盯盘等（演示路由）。
metadata:
  version: public-v1.0
  note: 展示版骨架 —— 结构与生产版同构，策略参数以 mock 替代
---

# A 股多周期交易体系 · Skill 路由入口（公开展示版）

> 📌 **当前规则的唯一事实源 = `rules/`**（生产版为带稳定 ID 与四级标注的规则
> 库 + 注册表；公开版提供格式示例，见 `rules/README.md`）。
> 本文只保留：能力边界、硬闸纪律、执行顺序、入口路由、场景文件索引、声明。

## 1. 能力与适用边界

- 多周期交易分析与执行辅助：大盘复盘（快速/完整/盘中快照）、个股诊断、
  自选池管理、尾盘选股、日内盯盘、判定闭环与规则进化。
- 个人持仓台账通过 `STOCK_POSITIONS_FILE` 外置注入（公开版指向空模板）。
- 仅供学习参考，不构成投资建议；不代用户下单。

## 2. 全局硬闸纪律（任何场景先于场景细则；示例展示纪律形状）

| 示例 ID | 硬闸纪律 | 工程映射 |
|---|---|---|
| GATE-ORDER | 多套裁决体系按声明优先级串行，高优先级否决不可被覆盖 | `strategy/interfaces.py` 决策层顺序组合 |
| GATE-FAILCLOSED | 风险扫描失败=fail-closed：不给结论只判观察 | `sources/risk_scan.py`、`RiskGate` Protocol |
| GATE-TIME | 数据有时效口径：拿到的最后披露日必须显式标注，写错日期=数据造假 | `common/calendar.py` + renderer 数据日标注 |
| GATE-SOURCE | 数据源降级必须可见：同族源不算独立验证；异源交叉确认 | `providers/audit.py` 血缘审计 |
| GATE-NET | 网络出口统一守卫，新增数据源先登记白名单 | `common/netguard.py` |
| GATE-OUT | 状态类提醒防幻觉：先核验再输出，核验不到写"未验证" | FINAL-001 canonical 事实层 |
| GATE-DELIVER | 复盘正文只能由确定性 renderer 从 canonical context 生成，禁止 Agent 拼装 | `quick_pipeline.py --final/--verify` |

> 生产版的完整硬闸清单（生态判定、仓位、买卖边界等）属于私有规则库，
> 以 `rules/` 的格式示例代替；纪律形状（fail-closed / 优先级 / 显式降级）不变。

## 3. 共同执行顺序

**复盘（收盘后或盘前）**：Step 0 数据采集+持仓识别 → Step 1 生态判定
（决策层 Protocol）→ 不能做=不进入选股与战术步骤 / 能做 → Step 2 核心标的
锁定 → Step 3 战术执行 → Step 4 红线扫描 → 按模板输出 → 自检
（`lint_review.py`）→ 固定追问自选整理。

**FINAL-001 · 跨 Agent 交付契约（强制）**：快速复盘必须调用
`python data/quick_pipeline.py --final`；快照与工具 stdout 均不可交付；
仅当 `delivery-manifest-*.json` 的 `publishable=true` 且 `--verify` 哈希
复核通过时允许交付 `quick-review-*` 正文；Agent 只可增加一句简短前言。

**离线演示**：`python demo/run_demo.py` 用合成数据走完整链路。

## 4. 入口路由（关键词 → 模式 → 场景文件）

无关键词 = 先输出菜单询问，禁止直接开始复盘。

| 关键词 | 模式 | 读取 |
|---|---|---|
| 快速/简要/速览 | 快速复盘 | market-review 工作流 + rules |
| 复盘/大盘/完整/深度 | 完整复盘 | market-review 全文 |
| 股票代码（6 位数字） | 个股诊断 | stock-diagnosis 工作流 |
| 持仓/自选/整理 | 池管理 | position-and-pools 工作流 |
| 日内盯盘/盘中监控 | daywatch | daywatch 工作流 |
| 数据源故障/降级/health | 排障 | data-sources 工作流 |
| 阈值验证/规则进化 | 验证闭环 | validation-and-evolution 工作流 |

> 生产版的场景文件（references/*.md）含完整工作流细则与输出模板；
> 公开版在 `references/README.md` 保留渐进加载设计与场景索引。

## 5. 渐进加载规则（禁止一次性全读）

- 快速/完整复盘：`rules/` 相关段 + 复盘工作流文件
- 个股诊断 / 持仓 / 盯盘 / 排障 / 进化：按需读取对应工作流文件
- 心法与战术按需深读：`systems/`、`tactics/`、`core/`（公开版为格式示例）

## 6. 核心命令

| 命令 | 用途 |
|---|---|
| `python demo/run_demo.py` | 离线端到端演示（合成数据） |
| `python data/quick_pipeline.py --final --snapshot <file>` | FINAL-001 交付 |
| `python data/quick_pipeline.py --verify <manifest>` | 交付前哈希复核 |
| `python data/providers/health.py` | Provider 健康检查（零配额） |
| `python -m pytest tests/ -q` | 密闭测试套件 |

## 7. 文件结构

见根 [README.md 的目录结构](README.md#目录结构) 与
[docs/MODULE_INDEX.md](docs/MODULE_INDEX.md)。

## 8. 声明

本体系仅供学习参考，不构成投资建议。公开版不包含生产环境的完整策略与
参数（见 README「Mock 边界声明」）。股市有风险，投资需谨慎。
