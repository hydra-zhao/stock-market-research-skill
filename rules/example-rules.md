# 当前规则（格式示例 · 虚构规则，非生产内容）

> 本文件演示生产版 `current-rules.md` 的条目格式：稳定 ID + 级别标注 +
> 正文 + 撤销条件。所有规则均为虚构示例。

## POOL 段（池管理）

### POOL-901 `hard_gate`
**示例规则**：任何进入观察池的标的必须先通过风险负面扫描；扫描失败时
fail-closed——不给出观察结论，只标注"风险未验证"。

- 撤销条件：无（工程纪律级，不随行情变化）
- 锁定测试：`tests/test_demo_contract.py`、`sources/risk_scan.py` 出口语义

### POOL-902 `scoring_feature`
**示例规则**：主线确认采用 N 项复合检查的多数通过制（结构见
`data/quick_context.py::build_mainline_analysis`，具体阈值为演示值）。

- 撤销条件：连续两个统计月确认准确率低于随机基准时降级为 `observation_only`

## SRC 段（数据源）

### SRC-901 `hard_gate`
**示例规则**：所有网络出口必须经 `common/netguard.py`（https + 域名白名单
+ IP 边界）；新增数据源先登记白名单再接线。

- 撤销条件：无
- 锁定测试：`tests/test_netguard_v726.py`

### SRC-902 `scoring_feature`
**示例规则**：同供应商家族（vendor_family）内的数据源互相验证**不算**
独立交叉确认；异源确认才计入数据可信度。

- 撤销条件：无
- 锁定测试：`tests/test_provider_architecture.py`

## OUT 段（输出）

### OUT-901 `hard_gate`
**示例规则**：状态类输出防幻觉——先核验再输出；核验不到的一律写
"未验证"，禁止用推断补齐事实。

- 撤销条件：无
- 锁定测试：`tests/test_quick_delivery_contract.py`
