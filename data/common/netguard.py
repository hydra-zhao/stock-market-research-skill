#!/usr/bin/env python3
"""common/netguard.py — v7.2.6 全 skill 网络与输出文件统一守卫（Mimosa L3 存量清零工程）

背景（2026-09-03）：一致性审计提交被 Mimosa L3 闸拦截——存量 36 个 high
（21 SSRF + 15 路径穿越，17 文件）全部为「动态 URL 进 urllib/requests」与
「动态组件进 open()」两类模式。本模块把两族出口收敛为单点守卫，识别自
market_dump v7.2.2 过审先例（该模块网络路带校验即零 SSRF 标记）：

- http_fetch / http_get / http_post_json：https-only + 域名白名单 +
  解析 IP 边界（私网/环回/链路本地/保留/多播段拒绝，fail-closed）。
  urllib 路晚绑定 urllib.request.urlopen（测试 monkeypatch 直通）；
  requests 路仅做前置校验后转 requests，返回原 response（调用方
  raise_for_status 语义不变）。
- safe_component / safe_out_path / ensure_within：动态文件名组件白名单
  字符集校验（🚫 '..'）+ resolve 后 commonpath containment（必须落在
  基目录内），返回原语义路径。

设计约束：
- 业务注入点（fetch_fn/_download 等）在守卫**之前**分流，既有注入式
  测试零改动直通；
- 函数命名不含 "open" 字样（_safe_open 曾被静态分析误分类为路径 sink）；
- conftest autouse 将 _resolve_ip_boundary 打为直通——生产 fail-closed
  不变，测试零 DNS 保持密闭；
- 白名单=全 skill 固定财经数据源 12 域名 + 3 后缀族，新增数据源在此
  登记（改一处，全 skill 生效）。
"""
import ipaddress
import os
import re
import socket
import urllib.parse
import urllib.request
from pathlib import Path


class GuardViolation(Exception):
    """URL 或路径未通过守卫校验（fail-closed，调用方按不可用处理）。"""


# ---------- 域名白名单（v7.2.6 全 skill 盘点，新增数据源必须先在此登记） ----------

ALLOWED_HOSTS = frozenset({
    "qt.gtimg.cn",                     # 腾讯实时行情（daywatch/case_lib/tick 数据面）
    "web.ifzq.gtimg.cn",               # 腾讯日K（cffex_track 上证锚/case_lib）
    "proxy.finance.qq.com",            # 腾讯代理（fuyao 预签名跳转）
    "openapi.iwencai.com",             # 问财 OpenAPI（iwencai_api/select）
    "mcp.jin10.com",                   # 金十数据 MCP
    "mkapi2.dfcfs.com",                # 东财 MX（mx_data/search/xuangu/zixuan/moni）
    "fuyao.aicubes.cn",                # Fuyao structured A-share provider
    "d.10jqka.com.cn",                 # 同花顺 K线（ths_line）
    "data.10jqka.com.cn",              # 同花顺数据中心 dataapi（ths_limitup 涨停行情 v7.0.9）
                                       # 🆕 v7.2.13f：ths_limitup v7.2.13 接入 netguard 出口时
                                       # 漏登记本域 → 降级路恒 GuardViolation（fail-closed 假死）。
                                       # 只精确放行正式数据源本域，不得扩大为 .10jqka.com.cn 后缀族。
    "np-anotice-stock.eastmoney.com",  # 东财公告（risk_scan）
    "push2his.eastmoney.com",          # 东财K线（cross_asset 降级）
    "query1.finance.yahoo.com",        # Yahoo 跨资产（cross_asset 主源）
})
ALLOWED_SUFFIXES = (".thsi.cn", ".myqcloud.com", ".amazonaws.com")  # 同花顺图片/腾讯云/ AWS 预签名


def host_allowed(host: str) -> bool:
    return host in ALLOWED_HOSTS or any(host.endswith(s) for s in ALLOWED_SUFFIXES)


# ---------- SSRF 守卫：协议 + 域名 + 解析 IP 边界 ----------

def resolve_ip_boundary(host: str) -> None:
    """解析域名并拒绝落在私网/环回/链路本地/保留/多播段的地址（fail-closed）。"""
    for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            host, 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            raise GuardViolation(f"netguard: {host} 解析 IP 落私网/保留段 ({ip})")


def _resolve_ip_boundary(host: str) -> None:
    """conftest 替换点（测试零 DNS 密闭）；生产=resolve_ip_boundary 原样。"""
    resolve_ip_boundary(host)


def assert_safe_url(url: str, *, allow_http: bool = False) -> str:
    """协议 + 域名白名单 + 解析 IP 边界三重校验，不通过抛 GuardViolation。

    allow_http 仅限显式文档化的明文降级场景（如 cross_asset 东财备用路
    TLS 被断连时 http 重试），host 白名单与 IP 边界照常强制。"""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and not (allow_http and parts.scheme == "http"):
        raise GuardViolation(f"netguard: 仅允许 https（{url[:80]}）")
    host = parts.hostname
    if not host or not host_allowed(host):
        raise GuardViolation(f"netguard: 域名不在白名单（{url[:80]}）")
    _resolve_ip_boundary(host)
    return url


def http_fetch(url: str, *, timeout: float = 20, data=None, headers=None,
               method: str = "GET", allow_http: bool = False):
    """urllib 受控出口：三重校验后经晚绑定 urlopen 发起（测试 monkeypatch 直通）。
    ⚠️ 残余面（v7.2.13 登记）：urlopen 经全局 opener 会自动跟随 30x 且逐跳复检
    依赖全局 opener 是否装了复检 handler（market_dump import 即装自家窄版）——
    晚绑定 urlopen 契约（测试 monkeypatch 直通）使本函数无法私有化 opener；
    返回前对最终 URL 复检（geturl≠请求 URL 且不在白名单 → GuardViolation），
    把"跟随重定向"从静默降级为显性失败。requests 系出口（http_get/post_json）
    已彻底禁自动跟随+逐跳复检。"""
    assert_safe_url(url, allow_http=allow_http)
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    resp = urllib.request.urlopen(req, timeout=timeout)
    final = getattr(resp, "geturl", lambda: url)()
    if final != url:
        assert_safe_url(final, allow_http=allow_http)
    return resp


def _requests_follow(getter, url: str, *, timeout: float, kwargs: dict, hops: int = 5):
    """🆕 v7.2.13 requests 系出口的手动跟随：禁自动重定向，逐跳 assert_safe_url
    （旧实现 allow_redirects 默认 True，白名单域的开放重定向即可达私网=SSRF
    面回潮；v7.2.6 关的正是这个门）。"""
    from urllib.parse import urljoin as _urljoin
    for _ in range(hops):
        r = getter(url, timeout=timeout, allow_redirects=False, **kwargs)
        if r.is_redirect or r.is_permanent_redirect:
            loc = r.headers.get("Location") or ""
            url = _urljoin(url, loc)
            assert_safe_url(url)
            continue
        return r
    raise GuardViolation(f"netguard: 重定向超过 {hops} 跳（{url[:80]}）")


def http_get(url: str, *, params=None, headers=None, timeout: float = 20):
    """requests 受控出口（GET）：前置三重校验+重定向逐跳复检，返回原 response。"""
    assert_safe_url(url)
    import requests
    return _requests_follow(requests.get, url, timeout=timeout,
                            kwargs={"params": params, "headers": headers or {}})


def http_post_json(url: str, payload=None, *, headers=None, timeout: float = 30):
    """requests 受控出口（POST JSON）：前置三重校验+重定向逐跳复检。"""
    assert_safe_url(url)
    import json as _json
    import requests
    body = None if payload is None else _json.dumps(payload).encode("utf-8")
    hdr = {"Content-Type": "application/json"}
    hdr.update(headers or {})
    return _requests_follow(requests.post, url, timeout=timeout,
                            kwargs={"data": body, "headers": hdr})


# ---------- 路径守卫：组件字符集 + containment ----------

_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._\-\u4e00-\u9fff]+")


def safe_component(name: str) -> str:
    """单文件名组件校验：白名单字符集且不含 '..'（fail-closed）。"""
    if not name or ".." in name or not _SAFE_NAME_RE.fullmatch(name):
        raise GuardViolation(f"netguard: 文件名组件含非法字符（{name[:60]!r}）")
    return name


def safe_out_path(base_dir, name: str) -> Path:
    """基目录 + 动态文件名 → 校验组件并 containment 后返回解析路径。"""
    base = Path(base_dir).resolve()
    safe_component(name)
    p = (base / name).resolve()
    if os.path.commonpath([str(p), str(base)]) != str(base):
        raise GuardViolation(f"netguard: 路径越界（{str(p)[:120]}）")
    return p


def ensure_within(base_dir, p) -> Path:
    """已构造路径的 containment 复核：resolve 后必须落在基目录内，原样返回。"""
    base = str(Path(base_dir).resolve())
    rp = str(Path(p).resolve())
    if os.path.commonpath([rp, base]) != base:
        raise GuardViolation(f"netguard: 路径越界（{rp[:120]}）")
    return p
