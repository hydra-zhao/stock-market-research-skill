"""Provider configuration/route/cache health check. Never prints secrets."""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from providers.registry import ProviderRegistry
else:
    from .registry import ProviderRegistry


def rows(registry: ProviderRegistry | None = None) -> list[dict]:
    reg = registry or ProviderRegistry()
    out = []
    for name, provider in reg.providers.items():
        # 计数含 experimental 能力（否则 tencent 会显示 0 能力，读起来像未登记）；
        # 是否需显式 opt-in 由 experimental 列单列，二者不混为一谈。
        caps = [c for c in reg.matrix["capabilities"]
                if name in reg.order(c, allow_experimental=True)]
        out.append({"provider": name, "key_configured": provider.configured(),
                    "connectivity": "NOT_CHECKED", "capabilities": len(caps),
                    "quota": "unknown", "rate_limited": False,
                    "schema_status": "ok" if not any(p == name for p, _ in reg.disabled) else "disabled",
                    "cache_status": "ready", "degraded": not provider.configured(),
                    "disabled": any(p == name for p, _ in reg.disabled),
                    "experimental": any(name in reg.experimental_providers(c) for c in caps)})
    return out


def render(items: list[dict]) -> str:
    lines = [f"STOCK_DATA_MODE={os.environ.get('STOCK_DATA_MODE', 'hybrid')}",
             "|Provider|Key configured?|Connectivity|Capabilities|Quota|Rate limited?|Schema|Cache|Degraded?|Disabled?|Experimental?|",
             "|---|:---:|---:|---:|---|:---:|---|---|:---:|:---:|:---:|"]
    for x in items:
        lines.append(f"|{x['provider']}|{'yes' if x['key_configured'] else 'no'}|{x['connectivity']}|{x['capabilities']}|{x['quota']}|{'yes' if x['rate_limited'] else 'no'}|{x['schema_status']}|{x['cache_status']}|{'yes' if x['degraded'] else 'no'}|{'yes' if x['disabled'] else 'no'}|{'yes' if x.get('experimental') else 'no'}|")
    lines.append("Connectivity is NOT_CHECKED by default; this command does not consume quota.")
    lines.append("Experimental=yes：该源仅在调用方显式 allow_experimental 时参与路由"
                 "（capabilities.yaml 的 experimental_providers 声明）。")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(rows()))
