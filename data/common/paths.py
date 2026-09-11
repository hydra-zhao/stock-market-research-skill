"""common/paths.py — 跨模块共享路径单点定义。

所有消费方统一 import，路径变更只改此处（或设 STOCK_POSITIONS_FILE）。
公开演示版：默认指向仓库内示例台账模板（不含任何真实持仓）；
生产部署通过 STOCK_POSITIONS_FILE 注入私有台账路径。
"""
import os
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent

# 公开版默认=仓库内示例模板（空持仓）；生产部署设 STOCK_POSITIONS_FILE 覆盖。
_DEFAULT_POSITIONS = _SKILL_ROOT / "data" / "config" / "positions.sample.md"


def positions_file() -> Path:
    """持仓台账运行时真相源。

    每次调用读取 STOCK_POSITIONS_FILE：同一进程内改环境变量即时生效（无需
    reload/重开进程）。消费方统一走本函数，禁止各自硬编码路径。
    """
    env = os.environ.get("STOCK_POSITIONS_FILE")
    return Path(env) if env else _DEFAULT_POSITIONS


# 兼容常量（import 时求值，旧引用不破）：运行时路径解析一律用 positions_file()，
# 禁止再把本常量当真相源消费（CFG-001 关闭条件）。
POSITIONS_FILE: Path = positions_file()

# 复盘状态文件（C2：防重复复盘/会话并发感知）
REVIEW_STATE_FILE: Path = _SKILL_ROOT / "output" / "review_state.json"
