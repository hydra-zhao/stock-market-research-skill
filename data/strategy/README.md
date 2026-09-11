# strategy/ — 决策层（公开演示版）

生产仓库中，这一层是整套体系的私有核心：市场生态判定、四位裁决者、
个股评分权重、风险否决规则、买卖触发条件。**这些实现不在本仓库公开**，
此处仅提供：

| 文件 | 内容 |
|---|---|
| `interfaces.py` | 决策层 Protocol：`MarketRegimeJudge` / `StockScorer` / `RiskGate`，数据管道只依赖这些形状 |
| `example_strategy.py` | 确定性示例实现：演示用分档阈值（`SAMPLE_*`）+ 简单动量评分，专供 demo 与测试驱动管道 |

## 为什么这样设计

```
采集层 (providers/sources)  →  归一化 (quick_context)  →  决策层 (strategy.*)  →  确定性渲染 (quick_renderer)  →  交付契约 (manifest+verify)
```

决策层被隔离在独立包中、只通过 Protocol 与管道耦合，因此：

1. **策略可整体替换**：替换 `example_strategy` 不触碰任何管道代码；
2. **管道可独立测试**：测试注入固定判定结果即可锁定渲染/交付行为；
3. **安全边界清晰**：私有参数只存在于生产仓库的策略实现里。

## 示例实现的边界（诚实声明）

- `example_strategy.py` 的所有阈值都是演示值，**不构成投资建议**；
- 它只解析 demo fixtures 的快照格式，生产快照的字段远多于此；
- 生产版对应的模块地图见 `docs/MODULE_INDEX.md`（策略模块标注为 mock）。
