# references/ — 场景化渐进加载（公开演示版）

生产仓库的本目录含 6 份场景工作流文档（约 55KB），按场景**渐进加载**——
Agent 只读当前场景需要的文件，禁止一次性全读（控制上下文成本与注意力）：

| 场景文件 | 覆盖工作流 | 公开版 |
|---|---|---|
| `market-review.md` | 快速/完整复盘流程 + 输出模板（TL;DR → 生态判定 → 核心数据 → 聪明资金 → 梯队断板 → 首板题材 → 主线确认 → 持仓对照 → 趋势波段 → 自检 → 整理追问） | 生产内容私有；结构见下方"输出模板骨架" |
| `stock-diagnosis.md` | 个股诊断 / K线 / 以史为鉴（形态匹配） | 私有 |
| `position-and-pools.md` | 持仓台账 / 自选池 / 尾盘扫描 | 私有 |
| `daywatch.md` | 日内盯盘哨兵 | 私有 |
| `data-sources.md` | 数据源清单 / 降级链 / 排障 / CLI 总表 | 私有（架构层见 docs/DATA_PROVIDER_ARCHITECTURE.md） |
| `validation-and-evolution.md` | 阈值验证 / 规则升格降权 / 案例库 | 私有 |

## 渐进加载设计（保留的工程结构）

```
SKILL.md（路由，≤250 行）
   └── 关键词 → 场景文件（只加载一份）
          └── 场景文件 → rules/ 相关段（按 ID 引用）
                 └── 需要深读时 → systems/ tactics/ core/（心法/战术/行业知识）
```

- 每层只引用下一层的稳定 ID 与路径，不做内容复制；
- 输出模板以 required section 清单表达，由 `data/lint_review.py` 机械校验，
  Agent 输出缺段=lint 红灯。

## 输出模板骨架（快速复盘 required sections）

`data/lint_review.py::FINAL_REQUIRED_HEADINGS` 锁定的结构（公开版原样保留）：

TL;DR → 关键信号（四人裁决）→ 核心数据 → 聪明资金 → 连板梯队+断板名单 →
首板题材归类 → 主线确认 → 接力分析 → 持仓对照 → 趋势波段候选 →
美股ETF观察 → 数据采集自检 → 整理追问

实际产出示例见 `python demo/run_demo.py` 生成的 `quick-review-*.md`。
