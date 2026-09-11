# 公开发布安全审查报告

> 审查对象：本仓库（stock-public，public-v1.0）
> 审查日期：2026-09-12 · 审查方式：全树内容扫描 + git 历史（全新初始化）复核
> 结论先行：**本仓库可以设为 Public** —— 未发现任何 API key、token、cookie、
> 密码、数据库连接、私人路径或个人持仓/日记数据；核心交易策略已按
> README「Mock 边界声明」脱敏。发布前请完成文末「需作者确认」清单。

## 一、保留了什么（与生产仓库同构的管道代码）

| 类别 | 内容 | 泄密风险评估 |
|---|---|---|
| Provider 能力路由层 | capabilities.yaml 路由矩阵、DataResult 血缘契约、同族非独立验证审计 | 低：数据源拓扑是工程架构，不含选股参数 |
| FINAL-001 交付链 | quick_context/renderer/lint/manifest/verify + JSON Schema | 低：这是防幻觉交付机制；其中两处判定阈值已替换为 SAMPLE 演示常量 |
| 多源降级链 | 同花顺三路 / AKShare 两路 / 东财公告风险扫描 | 低：公开接口的调用与解析，零凭据 |
| 网络守卫 | netguard（https+白名单+IP边界） | 低：白名单均为公开财经域名 |
| 测试基建 | 密闭 conftest（全局禁网闸）、CI（windows-latest pytest） | 无 |
| 多代理协作约定 | AGENTS.md（Sol/Luna 复核链、交付契约） | 低：通用工程纪律 |

## 二、删除了什么

- **策略核心实现**：signal_score（判定闭环/阈值寻优）、seat_profile（席位
  画像）、selection_evolution、backtest_rules、shouban_group、wave_scan、
  tick_scan、cross_asset、daywatch_*（盯盘预案线）、daily_journal、
  catalyst_watch、hist_backfill、signal_log、mx/*（自选接口）、
  tech/pattern*（形态匹配管线）、tech/trend（中期四锚）、tactics/backtest.py、
  a-stock-swing.md 战术手册、8 套交易心法文档、生产版 rules/references 内容
- **私人数据**：个人看盘日记 journals/、运行产物 output/（含真实复盘正文
  与席位落盘）、行情缓存 data/cache/（189MB）、真实持仓台账引用
- **生产变更叙事**：CHANGELOG.md（284KB，含策略演化全过程）
- **原 git 历史**：公开版全新初始化（生产仓库保持 private）

## 三、脱敏了什么（结构保留、数值替换）

| 位置 | 处理 |
|---|---|
| `data/builders.py` 尾盘/波段候选池查询串 | 多条件选股画像 → `<生产版：私有选股画像条件（已脱敏）>` 占位 |
| `data/quick_context.py` 主线确认阈值（涨停家数门槛/通过数门槛） | → `SAMPLE_MAINLINE_MIN_LIMITS / _MIN_PASS` 演示常量 |
| `data/quick_context.py` 接力状态机（高度/晋级率/溢价的组合判定） | → 折叠为 `sanitized` 中性态，判定条件不公开 |
| `data/quick_context.py` 断板大面口径 | → `SAMPLE_BROKEN_LOSS_PCT` 演示常量（并标注"非交易阈值"） |
| `data/tech/cycle.py` | 十大真实行业判据 → 虚构示例行业 `demo_steel` |
| `data/quick_renderer.py` | 内部规则 ID（如 POOL-003/ECO-003 字样）→ 泛化文案 |
| `data/common/paths.py` | 默认持仓路径（含用户名与项目目录特征）→ 仓库内空模板 |
| `data/round1_v2.py` | 2045 行采集编排 + 完整 `_quick_eval` 生态判定 → 精简入口 + 示例委托 |

## 四、mock/示例替代

`data/strategy/`（interfaces + example_strategy，演示阈值 `SAMPLE_*`）、
`data/review_hooks.py`（骨架）、`data/sources/market_dump.py`（stub）、
`data/case_lib.py`（仅保留腾讯日K取数函数）、`rules/ systems/ references/
tactics/ core/ knowledge/`（格式与结构示例）。边界清单见 README
「Mock 边界声明」，并由 `tests/test_public_structure.py` 自动守护
（管道禁止 import 已移除的私有策略模块）。

## 五、扫描方法与结果

对**暂存区全部内容**执行：

1. 凭据模式：`api_key|apikey|token|cookie|password|secret|bearer` 赋值形
   长字符串 —— 0 命中；
2. 云厂商 AccessKey 模式（阿里云 LTAI*/AKID*、GitHub ghp_*、Slack xox*）、
   PEM 私钥头 —— 0 命中；
3. 45+ 位高熵 token 样字符串 —— 0 命中；
4. 私人路径特征（用户名、生产项目目录名）—— 仅 `tests/test_public_structure.py`
   的检测模式常量自身命中（预期内，且已被该测试排除出扫描对象）；
5. 结构守护测试：全树私人路径特征扫描 0 命中（CI 持续强制）；
6. 演示可复现性：`demo/run_demo.py`（固定种子）+ `quick_pipeline --final/--verify`
   全链 publishable=true；`pytest -q` 150 passed（零网络）。

## 六、git 历史说明

- **本仓库**：全新初始化，2 个提交，无历史泄露面；
- **原生产仓库**（保持 private）：曾对其全量历史做过同等扫描（增删文件
  清单、`-S` 字符串搜索、密钥模式匹配），未发现 key/token 入库史；日记与
  output 从未入库（.gitignore 自始覆盖）。若未来将生产仓库的历史推送到
  任何远端，建议先重跑扫描。

## 七、需作者确认的事项

1. **裁决者命名**：仓库保留"四人裁决"体系命名（退神/涅槃/养家/见股起意，
   见 renderer/schema/lint 关键词）。这属于体系结构命名而非策略参数，
   但若你希望彻底匿名化，可全局替换为泛化角色名（改动点见
   `docs/MODULE_INDEX.md` 决策层一节）。
2. **市场级查询串**：builders.py 保留的涨停/跌停/板块资金等问财查询串是
   公开市场数据口径，不属于选股策略——若你连这些口径也想视为私有，可
   进一步占位化。
3. **capabilities.yaml 注释**：含少量内部决策编号（如"v7.3.4 冻结决策
   #18"）与 MA360/MA250 技术参数引用——均为工程溯源信息，确认可接受。
4. **仓库作者署名**：LICENSE 与 git 提交使用的占位署名（`hydra` /
   noreply 邮箱）——发布前替换为你希望公开的身份。
5. **capabilities.yaml 中 fuyao.aicubes.cn 等私有数据商域名**：出现在
   netguard 白名单与路由配置中。这是第三方服务端点而非凭据，但若该服务
   不希望被公开关联，可从白名单示例中泛化。
