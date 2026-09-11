# rules/ — 规则层（公开演示版）

生产仓库中，本目录是**交易规则的唯一事实源**：

- `current-rules.md`（约 33KB）：当前全部规则，每条带稳定 ID 与四级标注
  （`hard_gate` / `scoring_feature` / `observation_only` / `disabled`），
  按域分段（ECO 生态 / TRACK 轨道 / POOL 池 / RISK 风险 / SRC 数据源 /
  TIME 时效 / OUT 输出 / HOOK 钩子 / WATCH 盯盘 / VAL 验证）；
- `registry.yaml`（约 64KB）：规则注册表——每条关键规则的来源、事故证据、
  锁定测试、撤销条件；
- `registry_exclusions.yaml`：注册豁免清单。

**以上生产内容不在本仓库公开**。此处提供格式示例：

| 文件 | 内容 |
|---|---|
| `example-rules.md` | 规则正文的格式示例（ID/级别/正文/撤销条件） |
| `example-registry.yaml` | 注册表的 schema 示例（虚构规则） |

这个设计的工程价值：

1. **稳定 ID**：规则可被代码、测试与文档精确引用（如 `POOL-003`），
   变更历史可追溯；
2. **级别标注**：`hard_gate` 由代码强制（fail-closed），`scoring_feature`
   只影响评分，`observation_only` 只输出观察——LLM Agent 按级别决定
   是"必须遵守"还是"参考"；
3. **测试锁定**：关键规则有对应 pytest 用例，规则与实现漂移即红灯；
4. **撤销条件前置**：每条硬规则写明什么证据出现时可以撤销，防止规则
   只增不减。
