# 安装与运行（公开演示版）

## 前提

- Python 3.12+（CI 在 3.13 上验证，Windows/Linux 均可）
- 无需任何 API key —— demo 与测试全部离线密闭

## 快速开始

```bash
pip install -r requirements-ci.txt

# 离线端到端 demo：合成快照 → FINAL-001 交付链（context→render→lint→manifest→verify）
python demo/run_demo.py

# 等价的外部入口（与生产交付契约同一条命令面）
python data/quick_pipeline.py --final --snapshot output/demo/quick-snapshot-*.md --output-dir output/demo
python data/quick_pipeline.py --verify output/demo/delivery-manifest-*.json

# 密闭测试套件（零网络，conftest 全局禁网闸）
python -m pytest tests/ -q
```

## 环境变量（均为可选；不配置时相关数据源显式降级，绝不静默假数据）

| 变量 | 必需 | 说明 |
|------|------|------|
| `FUYAO_API_KEY` | 否 | Fuyao 结构化 A 股数据（日K底座/涨停池主源） |
| `IWENCAI_API_KEY` | 否 | 问财 OpenAPI（选股/宏观测速） |
| `MX_APIKEY` | 否 | 东方财富妙想（独立交叉验证源） |
| `JIN10_MCP_TOKEN` | 否 | 金十资讯 MCP |
| `STOCK_DATA_MODE` | 否 | `hybrid`（默认）/ `legacy`（回滚）/ provider 路由 |
| `STOCK_POSITIONS_FILE` | 否 | 私有持仓台账路径（公开版默认指向 `data/config/positions.sample.md` 空模板） |
| `STOCK_ZODIAC_THEME_CODES` | 否 | 题材过滤白名单（覆盖 config 文件） |

## 作为 Claude Code Skill 挂载（可选）

把仓库根的 `SKILL.md` 所在目录放入你的 skills 目录即可被识别。
公开版的 `SKILL.md` 是展示版骨架：保留路由/工作流/交付契约结构，
不含生产策略参数。

## 常见问题

- **没有配置任何 key 会怎样？** 相关能力显式降级并在输出标注（fail-closed：
  核验不到就写"未验证"，不硬凑）；`demo` 与 `pytest` 完全不触网。
- **Windows 控制台乱码？** 脚本已统一 `sys.stdout.reconfigure(encoding="utf-8")`。
