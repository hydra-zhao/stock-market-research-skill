"""common/review_state.py — 复盘状态文件（C2修复·2026-08-22 审计）

用途：①防止同一交易日重复复盘/整理时互相不知情（当晚实例：另一会话已
完成收盘整理，本会话只能靠读记忆 prose 获知）②为两会话并发编辑自选接口
提供最基础的感知依据。

设计：极简 JSON 落盘，任何失败静默降级（状态文件永远不阻塞主流程）。
"""
import json
import os
from datetime import datetime

try:
    from common.paths import REVIEW_STATE_FILE
except ImportError:  # 容错：直接以脚本方式运行时
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common.paths import REVIEW_STATE_FILE


def mark(kind, extra=None):
    """记录一次复盘动作。kind: quick / market / market_core / pool_sync ...
    🆕 v7.2.13e F03 同款事务：读改写在跨进程锁内完成——两个会话并发 mark 不同
    kind 时，后写者在锁内重读（旧实现读快照→整写会把对方 kind 抹掉）。"""
    try:
        REVIEW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        import contextlib
        lock_path = REVIEW_STATE_FILE.with_suffix(".json.lock")
        with contextlib.suppress(Exception):
            with open(lock_path, "a+") as lf:
                _lock_file(lf)
                try:
                    state = read()
                    state[kind] = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                    if extra:
                        state[kind].update(extra)
                    # 🆕 v7.2.13 原子写：write_text 半截 JSON 会让后续 read() 丢全部状态
                    tmp = REVIEW_STATE_FILE.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
                    os.replace(tmp, REVIEW_STATE_FILE)
                finally:
                    _unlock_file(lf)
    except Exception:
        pass


def _lock_file(f):
    if os.name == "nt":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock_file(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


# 🆕 2026-09-10（R7）：跨进程锁的**公开别名**——CFFEX 台账事务层（sources/
# cffex_track.py::ledger_txn）复用同一实现，两处必须同为 msvcrt/fcntl 语义；
# 只做别名不改行为（禁止另造不兼容锁，用户 R7.1-② 明令）。
lock_file = _lock_file
unlock_file = _unlock_file


def read():
    """读取全部状态；文件缺失/损坏/非dict 返回空 dict（不自动删，留人工排查）。"""
    try:
        data = json.loads(REVIEW_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def today_summary(now=None) -> dict:
    """🆕 v6.9.38：今日已发生的复盘动作 {kind: ts}——quick 横幅用。

    🆕 审查修复（2026-08-22）：口径从墙钟日期改为**数据日**（trading_day 推导）——
    周六跑 quick 时墙钟看不到周五晚的记录，而"周末同数据日防重复"恰是主场景。
    现在周五 22:00 的 quick 与周六 10:00 的 quick 同属数据日周五，互相可见。
    非 dict 状态/解析失败返回空 dict（模块自身兜底，不依赖调用方 try）。
    """
    from datetime import datetime as _dt
    now = now or _dt.now()
    st = read()
    if not isinstance(st, dict):
        return {}
    try:
        from common.calendar import trading_day
        cur_dd = trading_day(now)
    except Exception:
        cur_dd = now.strftime("%Y%m%d")
    out = {}
    for k, v in st.items():
        ts = str((v or {}).get("ts", "")) if isinstance(v, dict) else ""
        try:
            tdt = _dt.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
            if trading_day(tdt) == cur_dd:
                out[k] = ts
        except Exception:
            continue
    return out


if __name__ == "__main__":
    import sys  # 🆕 v7.2.12 顺序修复：旧版 reconfigure 在 import sys 之前——以
    try:        # 包模块方式运行（python -m common.review_state）时 sys 未导入=
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # v7.2.8 GBK 控制台/管道防崩（全 repo CLI 统一形态）
    except Exception:  # NameError 被静默吞=修复从未执行（直跑脚本路径恰有
        pass           # except ImportError 分支的 import sys 兜底才没暴露）
    if len(sys.argv) > 2 and sys.argv[1] == "mark":
        mark(sys.argv[2], extra={"note": " ".join(sys.argv[3:])} if len(sys.argv) > 3 else None)
        print(f"[OK] marked {sys.argv[2]}")
    else:
        print(json.dumps(read(), ensure_ascii=False, indent=1))
