# -*- coding: utf-8 -*-
"""tests/test_network_gate.py — conftest 全局禁网闸的持久化自测（v7.2.13d 一轮回修 P1-4）。

闸契约：未打 @pytest.mark.network 的用例，进程内 socket connect/DNS 解析立即
AssertionError（快速失败）；打标的用例豁免（真实网络场景的唯一出口）。
本文件让"闸真的会咬人+marker 真的能豁免"成为仓库内可回归的契约，而不是
一次性手工验证。覆盖面口径=pytest 主进程内；子进程由逐项注入桩保证（见
conftest no_socket_outbound docstring），本文件不宣称子进程禁网。
"""
import socket
import unittest

import pytest


class TestGateBlocks(unittest.TestCase):
    """未标 marker：外连/DNS 尝试必须立即 AssertionError（不是 timeout）。"""

    def test_socket_connect_denied(self):
        with self.assertRaises(AssertionError):
            socket.socket().connect(("example.com", 443))

    def test_socket_connect_ex_denied(self):
        with self.assertRaises(AssertionError):
            socket.socket().connect_ex(("example.com", 443))

    def test_getaddrinfo_denied(self):
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("example.com", 443)

    def test_gethostbyname_denied(self):
        with self.assertRaises(AssertionError):
            socket.gethostbyname("example.com")

    def test_create_connection_denied(self):
        with self.assertRaises(AssertionError):
            socket.create_connection(("example.com", 443))


@pytest.mark.network
def test_pytest_function_marker_exempts():
    """pytest 函数级 network marker 豁免：闸未生效时对本地回环已关闭端口的
    connect 得到的是 OS 层拒绝（ConnectionRefusedError/OSError），
    而非闸的 AssertionError——外连行为回到用例自己手里。
    （选 127.0.0.1:1 保证本自测本身零外连。）"""
    with pytest.raises((ConnectionRefusedError, OSError)) as cm:
        socket.create_connection(("127.0.0.1", 1), timeout=1)
    assert not isinstance(cm.value, AssertionError)


class TestUnittestMethodMarker(unittest.TestCase):
    """unittest 方法级 marker 同样豁免（pytest marks 在 unittest 方法上生效）。"""

    @pytest.mark.network
    def test_method_marker_exempts(self):
        with self.assertRaises((ConnectionRefusedError, OSError)) as cm:
            socket.create_connection(("127.0.0.1", 1), timeout=1)
        self.assertNotIsInstance(cm.exception, AssertionError)

    def test_unmarked_still_blocked(self):
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("example.com", 443)
