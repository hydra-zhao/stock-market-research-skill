#!/usr/bin/env python3
"""net_guard — 全局网络看门狗 · v7.2.5

事故背景（2026-09-02 快速复盘）：一次网络通道挂死导致 round1_v2 quick 10 分钟
零输出（直接 requests 调用全部带 timeout，卡点在依赖链路——DNS/akshare 内部/
重试循环，单点审计防不住）。本模块 = 两个进程级兜底：

- install(): socket.setdefaulttimeout —— 给所有"未显式传 timeout"的新连接
  一个默认超时（urllib3 未传 timeout 时 socket 走 getdefaulttimeout，实测
  覆盖 requests/urllib 全族；DNS 解析本身不受控，但连接/读写阶段被兜住）。
- wall_clock_cap(sec): faulthandler 硬顶 —— 进程超时未退出就把全部线程栈
  打到 stderr 并退出。既是止损，也是诊断（哪一路挂死、卡在哪一行，栈里见）。
  正常退出无需 cancel：进程没了定时器自然失效。

用法（只在 CLI 入口的 __main__ 守卫里调，禁止模块级调用——库态导入方
（测试/其他模块）不应被改写全局 socket 行为）：
    from sources.net_guard import install, wall_clock_cap
    install(); wall_clock_cap(300)
"""

import socket

DEFAULT_TIMEOUT = 20


def install(timeout: int = DEFAULT_TIMEOUT):
    try:
        socket.setdefaulttimeout(timeout)
    except Exception:
        pass
    return timeout


def wall_clock_cap(seconds: int, _stream=None):
    """进程级硬顶：seconds 秒后仍存活 → 全线程栈打印到 _stream(默认stderr) 并退出。"""
    try:
        import faulthandler
        import sys
        faulthandler.dump_traceback_later(seconds, exit=True, file=_stream or sys.stderr)
    except Exception:
        pass


def cancel_wall_clock_cap():
    try:
        import faulthandler
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
