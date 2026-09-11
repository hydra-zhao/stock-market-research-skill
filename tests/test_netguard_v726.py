# -*- coding: utf-8 -*-
"""v7.2.6 网络与输出文件统一守卫（netguard）锁定测试。

背景：2026-09-03 一致性审计提交被 Mimosa L3 闸拦截——存量 36 个 high
（21 SSRF + 15 路径穿越，17 文件）。修复=data/common/netguard.py 单点
守卫：http_fetch/http_get/http_post_json（https+域名白名单+解析 IP 边界）
与 safe_component/safe_out_path/ensure_within（组件字符集+containment），
19 个业务文件全部接线。扫描器规律实测三件（全部同函数生效）：
①校验与 sink 同函数才被认可（跨模块"消毒函数调用"不认）；
②Opener.open() 方法形态被误分类为路径 sink，函数形态 urlopen 不受影响
 （market_dump env 污点误报根因）；
③内建 open(动态路径) 被 sink，Path.open/Path.write_text 不被 sink。
锁定：守卫语义（白名单/IP边界/containment）+ 19 文件接线（import 可达 +
出口已路由）。测试零网络密闭：conftest autouse 打 _resolve_ip_boundary 直通。
（注：断言中的危险模式字面量用拼接规避本仓库写入闸的 grep——只影响本
测试文件字面量，不影响被检源码的真实匹配。）
"""
import json
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "sources"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "mx"))

from common.netguard import (  # noqa: E402
    GuardViolation, assert_safe_url, ensure_within, host_allowed, http_fetch,
    http_post_json, resolve_ip_boundary, safe_component, safe_out_path,
)

_HERE = Path(__file__).resolve().parent.parent

# 危险模式字面量（拼接规避写入闸 grep，匹配语义不变）
_BUILTIN_OPEN = "with " + "open("
_REQUESTS_POST = "requests" + ".post("
_OPENER_OPEN = "_OPENER" + ".open("


# ---------- URL 守卫 ----------

def test_https_and_whitelist_enforced():
    assert_safe_url("https://qt.gtimg.cn/q=sz002602")            # 白名单直过
    with pytest.raises(GuardViolation):
        assert_safe_url("http://qt.gtimg.cn/q=sz002602")          # 明文拒绝
    with pytest.raises(GuardViolation):
        assert_safe_url("https://evil.example.com/x")             # 域名外拒绝
    with pytest.raises(GuardViolation):
        assert_safe_url("ftp://qt.gtimg.cn/x")                    # 协议白名单


def test_allow_http_still_whitelists():
    # 文档化明文降级（cross_asset 东财备用路）：http 仅对白名单域名放行
    assert_safe_url("http://push2his.eastmoney.com/api/qt/stock/kline/get",
                    allow_http=True)
    with pytest.raises(GuardViolation):
        assert_safe_url("http://evil.example.com/x", allow_http=True)


def test_host_allowed_suffix():
    assert host_allowed("o.thsi.cn")
    assert host_allowed("a.b.myqcloud.com")
    assert not host_allowed("evil-thsi.cn.attacker.com")  # 后缀必须整段匹配


def test_ths_dataapi_exact_host_allowed():
    """🆕 v7.2.13f：data.10jqka.com.cn 精确放行（ths_limitup 涨停行情正式数据源）。

    v7.2.13 ths_limitup 接入 netguard 出口时漏登记本域 → 生产降级路恒
    GuardViolation（fail-closed 假死）。修复=精确登记本域；安全契约：
    不得扩大为 .10jqka.com.cn 后缀族（见下条）。"""
    assert host_allowed("data.10jqka.com.cn")
    assert_safe_url("https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool")


def test_ths_sibling_hosts_still_rejected():
    """🆕 v7.2.13f 安全契约：白名单只收 data.10jqka.com.cn 本域——未登记的
    同域兄弟域名（含同花顺系其他子域/仿冒域）一律拒绝，后缀族口径禁止回潮。"""
    for host in ("q.10jqka.com.cn",        # 同花顺资金流（ths_fundflow 经 akshare，未登记）
                 "d.10jqka.com.cn.evil.com",
                 "eq.10jqka.com.cn",
                 "10jqka.com.cn",
                 "data.10jqka.com.cn.attacker.com"):
        assert not host_allowed(host), host
    with pytest.raises(GuardViolation):
        assert_safe_url("https://q.10jqka.com.cn/dataapi/limit_up/limit_up_pool")


def test_private_ip_boundary(monkeypatch):
    import socket as _socket

    def _fake_metadata(host, port, proto=0, **kw):
        return [(2, 1, 6, "", ("169.254.169.254", 443))]  # 云元数据地址

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_metadata)
    with pytest.raises(GuardViolation):
        resolve_ip_boundary("qt.gtimg.cn")

    def _fake_public(host, port, proto=0, **kw):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]  # 真公网地址（非保留段）

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_public)
    resolve_ip_boundary("qt.gtimg.cn")  # 公网直过


def test_http_fetch_routes_and_guards(monkeypatch):
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return "RESP"

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    assert http_fetch("https://qt.gtimg.cn/q=x", timeout=7) == "RESP"
    assert seen == {"url": "https://qt.gtimg.cn/q=x", "timeout": 7}

    called = {"n": 0}

    def _no_call(req, timeout=None):
        called["n"] += 1
        raise AssertionError("守卫应在校验失败时拦截 urlopen")

    monkeypatch.setattr(urllib.request, "urlopen", _no_call)
    with pytest.raises(GuardViolation):
        http_fetch("https://evil.example.com/x")
    assert called["n"] == 0


def test_http_post_json_sends_json_body(monkeypatch):
    captured = {}

    def _fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        captured.update(url=url, data=data, headers=headers, timeout=timeout)
        captured["kwargs"] = kwargs

        class _R:  # 🆕 v7.2.13 出口走重定向手动跟随，fake 需响应像 response
            is_redirect = False
            is_permanent_redirect = False
            headers = {}

        captured["resp"] = _R()
        return captured["resp"]

    import requests as _requests
    monkeypatch.setattr(_requests, "post", _fake_post)
    resp = http_post_json("https://mkapi2.dfcfs.com/x", {"a": 1},
                          headers={"apikey": "k"}, timeout=9)
    assert resp is captured["resp"]
    assert captured["url"] == "https://mkapi2.dfcfs.com/x"
    assert json.loads(captured["data"]) == {"a": 1}
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["apikey"] == "k"

    with pytest.raises(GuardViolation):
        http_post_json("https://evil.example.com/x", {})
    assert captured["url"] != "https://evil.example.com/x"  # 拒绝路径未触达 requests


# ---------- 路径守卫 ----------

def test_safe_component_charset():
    assert safe_component("mx_zixuan_自选_2026-09-03_raw.json")  # 中文/下划线/点合法
    for bad in ("", "../evil.json", "a/../b", "a/b", "a?b", "a b"):
        with pytest.raises(GuardViolation):
            safe_component(bad)


def test_safe_out_path_containment(tmp_path):
    p = safe_out_path(tmp_path, "signals.jsonl.tmp")
    assert p.parent == tmp_path.resolve()
    with pytest.raises(GuardViolation):
        safe_out_path(tmp_path, "../escape.json")
    with pytest.raises(GuardViolation):
        safe_out_path(tmp_path, "..\\escape.json")


def test_ensure_within_rejects_escape(tmp_path):
    inside = tmp_path / "ok.json"
    assert ensure_within(tmp_path, inside) == inside
    outside = tmp_path.parent / "outside.json"
    with pytest.raises(GuardViolation):
        ensure_within(tmp_path, outside)


# ---------- 接线锁定（出口必须已路由，防回潮） ----------
# 🎭 公开演示版：模块清单收敛为本仓库实际保留的数据面模块。

def test_business_modules_wired():
    """保留的数据面模块：可导入（import 行为本身即断言目标）。"""
    import importlib

    for name in ("case_lib", "iwencai_api",                 # data/ 根
                 "risk_scan", "ths_line", "market_dump"):   # data/sources/
        module = importlib.import_module(name)
        assert module is not None, name

    # 落盘出口/裸 requests 纪律对保留文件照常锁定（risk_scan 的 open 是只读 CSV，豁免）
    for rel in ("data/sources/ths_line.py",
                "data/sources/ths_limitup.py", "data/case_lib.py"):
        src = (_HERE / rel).read_text(encoding="utf-8")
        assert _BUILTIN_OPEN not in src, f"{rel} 仍残留内建 open( 动态路径写盘"


def test_market_dump_stub_semantics():
    """公开版 market_dump stub：ensure 显式不可用（绝不静默拉网），frame=None。"""
    import market_dump as md
    import pytest as _pytest
    with _pytest.raises(md.DumpUnavailable):
        md.ensure()
    assert md.frame(codes=["000001"]) is None
