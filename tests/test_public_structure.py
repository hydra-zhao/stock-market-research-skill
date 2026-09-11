# -*- coding: utf-8 -*-
"""仓库结构守护测试（公开版新增）。

锁定公开版的结构契约：
- 决策层隔离：data/ 管道代码只允许通过 strategy.interfaces/example_strategy
  引用决策层，禁止 import 任何生产私有策略模块（它们不在本仓库）；
- 演示边界：docs/MODULE_INDEX.md 的 mock 标注与 data/ 实际文件一致
  （新增/删除模块必须同步索引，与生产仓库的守护测试同构）；
- 不含私人数据：任何被 git 跟踪的文件不得包含真实持仓路径特征。
"""
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent

FORBIDDEN_STRATEGY_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(signal_score|seat_profile|selection_evolution|"
    r"shouban_group|backtest_rules|wave_scan|daywatch_\w+|daily_journal|"
    r"hist_backfill|catalyst_watch|tick_scan|cross_asset|signal_log|watchlist_diff|"
    r"source_drift)\b", re.M)

# 通用私人路径特征（刻意不含任何生产环境专属命名——本仓库自身也不应携带）
PRIVATE_PATH_PATTERNS = ("C:\\Users\\", "C:/Users/", "/Users/", ".claude/")


def test_pipeline_only_imports_strategy_via_public_package():
    for rel in (_HERE / "data").rglob("*.py"):
        if ".archive" in rel.parts or "strategy" in rel.parts:
            continue
        src = rel.read_text(encoding="utf-8")
        leaked = FORBIDDEN_STRATEGY_IMPORTS.search(src)
        assert leaked is None, f"{rel} 引用了不在公开版的策略模块: {leaked.group(0)!r}"


def test_module_index_matches_tree():
    index = (_HERE / "docs" / "MODULE_INDEX.md").read_text(encoding="utf-8")
    actual = {p.relative_to(_HERE).as_posix() for p in (_HERE / "data").rglob("*.py")
              if "__pycache__" not in p.parts}
    indexed = {f"`{m}`" for m in re.findall(r"`(data/[A-Za-z_/]+\.py)`", index)}
    missing = {m.replace("`", "") for m in indexed} - actual
    assert not missing, f"MODULE_INDEX.md 登记了不存在的模块: {sorted(missing)}"


def test_no_private_paths_in_tree():
    offenders = []
    self_name = Path(__file__).name
    for rel in _HERE.rglob("*"):
        if not rel.is_file() or ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        if rel.name == self_name:      # 本文件的模式常量自身不参与扫描
            continue
        if rel.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml"}:
            continue
        text = rel.read_text(encoding="utf-8", errors="replace")
        for pattern in PRIVATE_PATH_PATTERNS:
            if pattern in text:
                offenders.append(f"{rel.relative_to(_HERE)} 含私人路径特征 {pattern!r}")
    assert not offenders, "\n".join(offenders)
