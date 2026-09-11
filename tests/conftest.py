# -*- coding: utf-8 -*-
"""pytest 全局夹具 —— 测试密闭性守卫（公开版）。

三层守卫，保证 `python -m pytest tests/ -q` 在 fresh clone、无缓存、
无 API key、无网络的环境下可重复通过：

1. 数据模式固定 legacy —— 不 spawn 真实 provider；
2. netguard 的 DNS 解析边界在测试环境直通 —— 保持 https+域名白名单
   校验生效的同时零真实解析；
3. 全局禁网闸 —— 未标记 `@pytest.mark.network` 的用例，任何进程内
   socket 外连/DNS 尝试立即 AssertionError（快速失败，漏网点第一时间暴露）。
"""
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
for _p in ("data", "data/sources", "data/strategy"):
    if str(_HERE / _p) not in sys.path:
        sys.path.insert(0, str(_HERE / _p))


@pytest.fixture(autouse=True)
def legacy_mode_for_existing_tests(monkeypatch):
    """Provider 路由相关测试默认走 legacy 回滚路径；provider 专项测试显式 opt-in hybrid。"""
    monkeypatch.setenv("STOCK_DATA_MODE", "legacy")


@pytest.fixture(autouse=True)
def netguard_no_dns(monkeypatch):
    """netguard 的解析 IP 边界检查在测试环境打为直通——保持测试零 DNS 密闭
    （https+域名白名单校验照常生效，仅跳过 getaddrinfo）。"""
    import common.netguard as ng
    monkeypatch.setattr(ng, "_resolve_ip_boundary", lambda host: None)


@pytest.fixture(autouse=True)
def no_calendar_net(monkeypatch):
    """交易日历获取在测试环境桩为失败（与真实网络失败同路径，走周末降级启发式）。"""
    import common.calendar as cal
    monkeypatch.setattr(cal, "_fetch_calendar", lambda: None)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: 允许真实网络外连（全局禁网闸豁免标记；默认拒绝）")


@pytest.fixture(autouse=True)
def no_socket_outbound(request, monkeypatch):
    """全局禁网闸：未显式标记 `@pytest.mark.network` 的用例，任何进程内
    socket 外连尝试立即 AssertionError。覆盖面=进程内直连
    （socket.connect/connect_ex/create_connection）与 DNS 解析
    （getaddrinfo/gethostbyname/gethostbyaddr）；子进程不受 in-process
    补丁影响，仍靠密闭夹具纪律。"""
    if request.node.get_closest_marker("network"):
        yield
        return
    import socket

    def _deny(what):
        def _f(*a, **k):
            raise AssertionError(
                f"测试尝试{what}{a!r} —— 未标记 @pytest.mark.network 的用例禁止外连"
                "（快速失败：密闭性契约见 conftest 头注，如需真实网络请显式打标）")
        return _f

    monkeypatch.setattr(socket.socket, "connect", _deny("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _deny("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _deny("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _deny("getaddrinfo"))
    monkeypatch.setattr(socket, "gethostbyname", _deny("gethostbyname"))
    monkeypatch.setattr(socket, "gethostbyaddr", _deny("gethostbyaddr"))
    yield
