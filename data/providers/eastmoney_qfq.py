"""Eastmoney ``push2his`` provider for strict whole-range qfq history.

This adapter owns the two ``pattern_edge_*`` capabilities.  The legacy
``pattern_history`` capability remains on its existing IWENCAI route because
legacy shape matching consumes the wide-row contract, which this payload does
not carry; the pattern forward-return backfill consumes the whole-range qfq
series instead and therefore routes here.

The endpoint is single-source and whole-range: one request asks for the full
window, one complete payload is cached, and a failed request never gets
stitched to another source or to a partial tail.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.calendar import completed_day
from common.netguard import http_fetch

from .base import Provider
from .cache import cache_key
from .errors import ProviderUnavailable, RateLimited, SchemaDrift
from .models import DataResult, ProviderIdentity


PROVIDER_VERSION = "eastmoney_qfq_v1"
PROVIDER_FAMILY = "eastmoney_family"
STOCK_CAPABILITY = "pattern_edge_history"
INDEX_CAPABILITY = "pattern_edge_index_history"
INDEX_SECID = "1.000001"  # 上证指数
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 0.75
DEFAULT_REQUEST_INTERVAL = 1.5
DEFAULT_BUFFER_ROWS = 200
_DATE8 = re.compile(r"^\d{8}$")
_BASE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&klt=101&fqt={fqt}&lmt={lmt}&end={end}"
    "&fields1=f1,f2,f3&fields2="
    "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
)
DISK_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "pattern_edge_qfq"
CACHE_SCHEMA_VERSION = 1
_HASH_FIELDS = ("date", "open", "close", "high", "low", "volume")


def _iso(date8: str) -> str:
    return f"{date8[:4]}-{date8[4:6]}-{date8[6:]}"


def _date8(value: Any) -> str:
    text = str(value).replace("-", "").strip()
    if not _DATE8.fullmatch(text):
        raise SchemaDrift(f"东财返回非法日期: {value!r}")
    return text


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _em_secid(code: str) -> str:
    """Map a six-digit A-share code to Eastmoney's ``secid``."""
    text = str(code).strip()
    if "." in text:
        return text
    text = text.zfill(6)
    if text.startswith(("4", "8", "92")):
        return "0." + text
    return ("1." if text[0] in "569" else "0.") + text


def _stable_number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _bars_hash(bars: Iterable[dict[str, Any]]) -> str:
    """Hash every field consumed by matching with explicit nulls."""
    digest = hashlib.sha256()
    for bar in bars:
        canonical = {field: (str(bar.get(field)) if field == "date"
                             else _stable_number(bar.get(field)))
                     for field in _HASH_FIELDS}
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _close_hash(bars: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for bar in bars:
        encoded = json.dumps(
            {"date": str(bar.get("date")),
             "close": _stable_number(bar.get("close"))},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False)
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class EastmoneyQfqProvider(Provider):
    """Strict whole-range Eastmoney qfq adapter.

    ``fetch`` returns a :class:`DataResult` even for network/contract
    failures.  A failed result has ``value=None`` so ``DataResult.usable`` is
    false and edge calculation cannot accidentally consume an incomplete
    payload.
    """

    identity = ProviderIdentity("eastmoney_qfq", PROVIDER_FAMILY)

    def __init__(self, *, retries: int = DEFAULT_RETRIES,
                 backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
                 request_interval: float = DEFAULT_REQUEST_INTERVAL,
                 buffer_rows: int = DEFAULT_BUFFER_ROWS,
                 cache_ttl: int = 900,
                 cache_dir: str | Path | None = None) -> None:
        self.retries = max(1, int(retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.request_interval = max(0.0, float(request_interval))
        self.buffer_rows = max(0, int(buffer_rows))
        self.cache_ttl = max(1, int(cache_ttl))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DISK_CACHE_DIR
        # Provider-local cache makes direct provider use safe; registry also
        # caches the resulting DataResult for normal production routing.
        self._cache: dict[str, tuple[float, DataResult]] = {}
        self._last_request_at = 0.0

    def supports(self, capability: str) -> bool:
        return capability in {STOCK_CAPABILITY, INDEX_CAPABILITY}

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if capability not in {STOCK_CAPABILITY, INDEX_CAPABILITY}:
            return self._failure(capability, "not_supported",
                                 f"eastmoney_qfq 不支持 capability={capability}")
        is_index = capability == INDEX_CAPABILITY
        return self._fetch_history(capability, is_index=is_index, **params)

    def _failure(self, capability: str, status: str, error: str,
                 **meta: Any) -> DataResult:
        metadata = {
            "provider_family": self.identity.family,
            "provider_used": self.identity.name,
            "provider_version": PROVIDER_VERSION,
            "fallback_reason": None,
            "adjust_method": meta.pop("adjust_method", "qfq"),
            "rows": meta.pop("rows", 0),
            "required_rows": meta.pop("required_rows", None),
            "qfq_rows": meta.pop("qfq_rows", 0),
            "qfq_coverage": meta.pop("qfq_coverage", None),
            "data_hash": meta.pop("data_hash", None),
            "consistency_status": "not_evaluated",
            "cache_hit": False,
            "from_cache": False,
            "cache_generated_at": meta.pop("cache_generated_at", None),
        }
        metadata.update(meta)
        return DataResult(value=None, source=self.identity.name,
                          provider_family=self.identity.family,
                          as_of=metadata.get("as_of"), status=status,
                          capability=capability, error=error,
                          metadata=metadata)

    @staticmethod
    def _cache_age(generated_at: str | None) -> float | None:
        if not generated_at:
            return None
        try:
            stamp = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0.0, time.time() - stamp.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None

    def _cache_get(self, key: str) -> DataResult | None:
        item = self._cache.get(key)
        if item is None:
            return None
        expires, result = item
        if expires <= time.time():
            self._cache.pop(key, None)
            return None
        hit = copy.deepcopy(result)
        hit.metadata["cache_hit"] = True
        hit.metadata["from_cache"] = True
        hit.metadata["cache_scope"] = "memory"
        hit.metadata["cache_age"] = self._cache_age(
            hit.metadata.get("cache_generated_at"))
        hit.metadata["cache_key"] = key
        hit.metadata["cache_version"] = PROVIDER_VERSION
        if isinstance(hit.value, dict):
            hit.value["cache_hit"] = True
            hit.value["from_cache"] = True
        return hit

    def _cache_put(self, key: str, result: DataResult) -> None:
        self._cache[key] = (time.time() + self.cache_ttl,
                            copy.deepcopy(result))

    def _disk_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _disk_put(self, key: str, fields: dict[str, Any],
                  result: DataResult) -> str | None:
        """Atomically persist one already-validated complete result."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            generated_at = result.metadata.get("cache_generated_at")
            blob = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "cache_key": key,
                "cache_version": PROVIDER_VERSION,
                "cache_fields": fields,
                "cache_generated_at": generated_at,
                "result": result.to_dict(),
            }
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{key}.", suffix=".tmp", dir=str(self.cache_dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(blob, handle, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self._disk_path(key))
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return None
        except (OSError, TypeError, ValueError) as exc:
            return f"disk_cache_write_failed:{type(exc).__name__}:{exc}"

    @staticmethod
    def _result_from_blob(raw: dict[str, Any]) -> DataResult:
        result = raw.get("result")
        if not isinstance(result, dict):
            raise ValueError("cache result missing")
        return DataResult(
            value=result.get("value"), source=str(result.get("source", "")),
            provider_family=str(result.get("provider_family", "")),
            as_of=result.get("as_of"), status=str(result.get("status", "")),
            fallback_from=result.get("fallback_from"),
            capability=result.get("capability"), error=result.get("error"),
            metadata=dict(result.get("metadata") or {}),
        )

    def _disk_get(self, key: str, fields: dict[str, Any], *,
                  capability: str, required: int, completed: str,
                  is_index: bool) -> tuple[DataResult | None, str | None]:
        path = self._disk_path(key)
        if not path.exists():
            return None, None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                raise ValueError("cache schema version mismatch")
            if raw.get("cache_key") != key or raw.get("cache_version") != PROVIDER_VERSION:
                raise ValueError("cache key/version mismatch")
            if raw.get("cache_fields") != fields:
                raise ValueError("cache fields mismatch")
            result = self._result_from_blob(raw)
            if result.status != "ok" or not isinstance(result.value, dict):
                raise ValueError("cache result is not a successful object")
            generated_at = (raw.get("cache_generated_at")
                            or result.metadata.get("cache_generated_at"))
            if not generated_at:
                raise ValueError("cache generation timestamp missing")
            checked = self._validate_bars(
                list(result.value.get("bars") or []), required=required,
                completed=completed, is_index=is_index)
            if not checked["ok"]:
                raise ValueError(f"cached contract invalid: {checked['error']}")
            computed = _bars_hash(checked["window"])
            if result.value.get("data_hash") != computed:
                raise ValueError("cached data_hash mismatch")
            cached = self._build_success(
                capability, checked["window"], required, completed, is_index,
                target=str(fields["instrument"]),
                validation_meta=checked["metadata"],
                generated_at=generated_at, cache_hit=True,
                cache_scope="disk", cache_age=self._cache_age(generated_at),
                cache_key_value=key)
            return cached, None
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return None, f"disk_cache_ignored:{type(exc).__name__}:{exc}"

    def _validate_bars(self, bars: list[dict[str, Any]], *, required: int,
                       completed: str, is_index: bool) -> dict[str, Any]:
        """Validate a complete window; used for network and every cache read."""
        before = len(bars)
        dropped = [bar.get("date") for bar in bars
                   if str(bar.get("date")) > completed]
        bars = [bar for bar in bars if str(bar.get("date")) <= completed]
        dates = [str(bar.get("date")) for bar in bars]
        common = {
            "rows": 0, "required_rows": required,
            "qfq_rows": None if is_index else 0,
            "qfq_coverage": None if is_index else 0.0,
            "completed_day": _iso(completed),
            "completed_day_requested": _iso(completed),
            "dropped_intraday_bars": before - len(bars),
            "dropped_intraday_dates": [_iso(str(d)) for d in dropped
                                       if _DATE8.fullmatch(str(d))],
        }
        if len(dates) != len(set(dates)):
            return {"ok": False, "status": "incomplete", "error": "窗口内日期重复",
                    "metadata": common}
        if any(not _DATE8.fullmatch(d) for d in dates):
            return {"ok": False, "status": "incomplete",
                    "error": "窗口内日期格式非法", "metadata": common}
        if dates != sorted(dates):
            return {"ok": False, "status": "incomplete", "error": "窗口内日期乱序",
                    "metadata": common}
        window = bars[-required:] if len(bars) >= required else bars
        rows_n = len(window)
        common["rows"] = rows_n
        if is_index:
            valid_qfq = None
        else:
            qfq_rows = sum(
                1 for bar in window
                if all(bar.get(field) is not None
                       for field in ("open", "close", "high", "low")))
            valid_qfq = qfq_rows / rows_n if rows_n else 0.0
            common["qfq_rows"] = qfq_rows
            common["qfq_coverage"] = valid_qfq
        if rows_n < required:
            return {"ok": False, "status": "incomplete",
                    "error": f"实际行数不足: rows={rows_n} < required_rows={required}",
                    "metadata": common}
        if not is_index and valid_qfq is not None and valid_qfq < 1.0:
            return {"ok": False, "status": "incomplete",
                    "error": f"qfq覆盖率不足: {valid_qfq:.6f}",
                    "metadata": common}
        def _invalid_bar(bar: dict[str, Any]) -> bool:
            for field in ("open", "close", "high", "low"):
                value = bar.get(field)
                if (value is None or not math.isfinite(float(value))
                        or float(value) <= 0):
                    return True
            volume = bar.get("volume")
            return volume is not None and not math.isfinite(float(volume))

        bad = [str(bar.get("date")) for bar in window if _invalid_bar(bar)]
        if bad:
            common["nonpositive_price_dates"] = bad
            return {"ok": False, "status": "incomplete",
                    "error": f"窗口存在非正/缺失价格: {bad[0]}",
                    "metadata": common}
        common["cache_generated_at"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "window": window, "metadata": common}

    def _build_success(self, capability: str, window: list[dict[str, Any]],
                       required: int, completed: str, is_index: bool, *,
                       target: str,
                       validation_meta: dict[str, Any] | None = None,
                       generated_at: str | None, cache_hit: bool,
                       cache_scope: str, cache_age: float | None,
                       cache_key_value: str) -> DataResult:
        data_range = [_iso(window[0]["date"]), _iso(window[-1]["date"])]
        data_hash = _bars_hash(window)
        close_hash = _close_hash(window)
        qfq_rows = None if is_index else sum(
            1 for bar in window
            if all(bar.get(field) is not None
                   for field in ("open", "close", "high", "low")))
        coverage = None if is_index else (qfq_rows or 0) / len(window)
        adjust = "raw" if is_index else "qfq"
        stamp = generated_at or datetime.now(timezone.utc).isoformat()
        validation_meta = validation_meta or {}
        processing_meta: dict[str, Any] = {
            key: validation_meta[key]
            for key in ("completed_day_requested", "dropped_intraday_bars",
                        "dropped_intraday_dates")
            if key in validation_meta
        }
        cache_meta: dict[str, Any] = {
            "cache_hit": cache_hit, "from_cache": cache_hit,
            "cache_scope": cache_scope, "cache_age": cache_age,
            "cache_generated_at": stamp, "cache_key": cache_key_value,
            "cache_version": PROVIDER_VERSION,
        }
        value: dict[str, Any] = {
            "bars": window,
            "series": [{"date": _iso(bar["date"]), "close": bar["close"]}
                       for bar in window],
            "dates": [bar["date"] for bar in window],
            "closes": [bar["close"] for bar in window],
            "highs": [bar["high"] for bar in window],
            "lows": [bar["low"] for bar in window],
            "volumes": [bar["volume"] or 0.0 for bar in window],
            "adjust": adjust, "adjust_method": adjust,
            "data_range": data_range, "data_hash": data_hash,
            "close_hash": close_hash,
            "target": target,
            "provider_family": self.identity.family,
            "provider_used": self.identity.name, "as_of": data_range[1],
            "rows": len(window), "required_rows": required,
            "qfq_rows": qfq_rows, "qfq_coverage": coverage,
            "fallback_reason": None, "consistency_status": "not_evaluated",
            "completed_day": _iso(completed), **processing_meta, **cache_meta,
        }
        metadata: dict[str, Any] = {
            "provider_family": self.identity.family,
            "provider_used": self.identity.name,
            "provider_version": PROVIDER_VERSION,
            "fallback_reason": None, "adjust_method": adjust,
            "data_range": data_range, "as_of": data_range[1],
            "rows": len(window), "required_rows": required,
            "qfq_rows": qfq_rows, "qfq_coverage": coverage,
            "data_hash": data_hash, "close_hash": close_hash,
            "consistency_status": "not_evaluated",
            "completed_day": _iso(completed), **processing_meta, **cache_meta,
        }
        return DataResult(value=value, source=self.identity.name,
                          provider_family=self.identity.family,
                          as_of=data_range[1], status="ok",
                          capability=capability, metadata=metadata)

    def _fetch_payload(self, secid: str, *, lmt: int, end: str,
                       fqt: int) -> list[str]:
        url = _BASE_URL.format(secid=secid, lmt=int(lmt), end=end, fqt=int(fqt))
        last: Exception | None = None
        for attempt in range(self.retries):
            if self.request_interval:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.request_interval:
                    time.sleep(self.request_interval - elapsed)
            self._last_request_at = time.monotonic()
            try:
                with http_fetch(url, timeout=20,
                                headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    status = getattr(resp, "status", None)
                    if status is not None and int(status) >= 400:
                        if int(status) in {429, 430, 503}:
                            raise RateLimited(f"东财 HTTP {status}")
                        raise ProviderUnavailable(f"东财 HTTP {status}")
                    payload = json.loads(resp.read())
                if not isinstance(payload, dict):
                    raise SchemaDrift("东财响应不是 JSON object")
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise ProviderUnavailable("东财返回 data 为空")
                klines = data.get("klines")
                if not isinstance(klines, list):
                    raise SchemaDrift("东财响应缺少 klines 列表")
                return klines
            except (RateLimited, ProviderUnavailable, SchemaDrift) as exc:
                last = exc
                # Schema/empty responses are deterministic, but keep the
                # bounded retry policy uniform and observable.
            except Exception as exc:  # network/JSON failures
                last = exc
            if attempt + 1 < self.retries and self.backoff_seconds:
                time.sleep(self.backoff_seconds * (2 ** attempt))
        if isinstance(last, (RateLimited, ProviderUnavailable, SchemaDrift)):
            raise last
        text = str(last) if last else "unknown network error"
        if any(token in text.lower() for token in ("429", "rate", "limit", "503")):
            raise RateLimited(f"东财请求失败（已重试{self.retries}次）: {text}")
        raise ProviderUnavailable(f"东财请求失败（已重试{self.retries}次）: {text}")

    @staticmethod
    def _parse_klines(rows: list[Any]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, str):
                raise SchemaDrift("东财 kline 行不是字符串")
            parts = raw.split(",")
            if len(parts) < 6:
                raise SchemaDrift("东财 kline 行字段不足")
            d = _date8(parts[0])
            parsed.append({
                "date": d,
                "open": _number(parts[1]),
                "close": _number(parts[2]),
                "high": _number(parts[3]),
                "low": _number(parts[4]),
                "volume": _number(parts[5]),
                "amount": _number(parts[6]) if len(parts) > 6 else None,
                "turnover": _number(parts[10]) if len(parts) > 10 else None,
            })
        return parsed

    def _fetch_history(self, capability: str, *, is_index: bool,
                       code: str = "", name: str = "", days: int = 1200,
                       min_rows: int | None = None, cutoff: str | None = None,
                       adjust_method: str | None = None,
                       provider_version: str = PROVIDER_VERSION,
                       **_kw: Any) -> DataResult:
        expected_adjust = "raw" if is_index else "qfq"
        if str(adjust_method or expected_adjust).lower() != expected_adjust:
            return self._failure(
                capability, "not_supported",
                f"{capability} 需要 adjust_method={expected_adjust}",
                adjust_method=expected_adjust,
                required_rows=int(min_rows or days))
        try:
            required = max(1, int(min_rows or days))
            requested_days = max(1, int(days))
        except (TypeError, ValueError) as exc:
            return self._failure(capability, "incomplete", f"窗口参数非法: {exc}",
                                 adjust_method=expected_adjust)
        try:
            completed = _date8(str(cutoff or completed_day()).replace("-", ""))
        except Exception as exc:  # noqa: BLE001
            return self._failure(capability, "incomplete", f"completed-day 无效: {exc}",
                                 adjust_method=expected_adjust,
                                 required_rows=required)
        instrument = INDEX_SECID if is_index else str(code or name)
        if not instrument:
            return self._failure(capability, "incomplete", "缺少股票代码/指数标识",
                                 adjust_method=expected_adjust,
                                 required_rows=required)
        secid = INDEX_SECID if is_index else _em_secid(instrument)
        fields = {
            "provider": self.identity.name,
            "provider_version": str(provider_version),
            "capability": capability,
            "instrument": instrument,
            "days": requested_days,
            "min_rows": required,
            "cutoff": _iso(completed),
            "completed_day": _iso(completed),
            "adjust_method": expected_adjust,
        }
        cache_params: dict[str, Any] = {
            key_name: value for key_name, value in fields.items()
            if key_name not in {"provider", "capability"}
        }
        key = cache_key(
            self.identity.name, capability,
            schema_version=str(provider_version),
            **cache_params)
        cached = self._cache_get(key)
        if cached is not None:
            checked = self._validate_bars(
                list((cached.value or {}).get("bars") or []),
                required=required, completed=completed, is_index=is_index)
            if checked["ok"] and (cached.value or {}).get("data_hash") == _bars_hash(checked["window"]):
                return cached
            self._cache.pop(key, None)
        disk_cached, disk_note = self._disk_get(
            key, fields, capability=capability, required=required,
            completed=completed, is_index=is_index)
        if disk_cached is not None:
            self._cache_put(key, disk_cached)
            return disk_cached
        try:
            raw_rows = self._fetch_payload(
                secid, lmt=max(required, requested_days) + self.buffer_rows,
                end=completed, fqt=0 if is_index else 1)
            bars = self._parse_klines(raw_rows)
        except RateLimited as exc:
            return self._failure(capability, "rate_limited", str(exc),
                                 adjust_method=expected_adjust,
                                 required_rows=required, completed_day=completed,
                                 cache_key=key, cache_version=provider_version,
                                 cache_scope="network", cache_hit=False,
                                 cache_age=None, cache_corrupt_reason=disk_note)
        except SchemaDrift as exc:
            return self._failure(capability, "schema_drift", str(exc),
                                 adjust_method=expected_adjust,
                                 required_rows=required, completed_day=completed,
                                 cache_key=key, cache_version=provider_version,
                                 cache_scope="network", cache_hit=False,
                                 cache_age=None, cache_corrupt_reason=disk_note)
        except ProviderUnavailable as exc:
            return self._failure(capability, "unavailable", str(exc),
                                 adjust_method=expected_adjust,
                                 required_rows=required, completed_day=completed,
                                 cache_key=key, cache_version=provider_version,
                                 cache_scope="network", cache_hit=False,
                                 cache_age=None, cache_corrupt_reason=disk_note)
        except Exception as exc:  # adapter boundary must be explicit
            return self._failure(capability, "unavailable",
                                 f"{type(exc).__name__}: {exc}",
                                 adjust_method=expected_adjust,
                                 required_rows=required, completed_day=completed,
                                 cache_key=key, cache_version=provider_version,
                                 cache_scope="network", cache_hit=False,
                                 cache_age=None, cache_corrupt_reason=disk_note)

        checked = self._validate_bars(bars, required=required,
                                      completed=completed, is_index=is_index)
        if not checked["ok"]:
            return self._failure(
                capability, checked["status"], checked["error"],
                adjust_method=expected_adjust, **checked["metadata"],
                cache_key=key, cache_version=provider_version,
                cache_scope="network", cache_hit=False, cache_age=None,
                cache_corrupt_reason=disk_note)
        result = self._build_success(
            capability, checked["window"], required, completed, is_index,
            target=str(code or name or INDEX_SECID),
            validation_meta=checked["metadata"],
            generated_at=None, cache_hit=False, cache_scope="network",
            cache_age=0.0, cache_key_value=key)
        if disk_note:
            result.metadata["cache_corrupt_reason"] = disk_note
            if isinstance(result.value, dict):
                result.value["cache_corrupt_reason"] = disk_note
        write_note = self._disk_put(key, fields, result)
        if write_note:
            result.metadata["cache_write_error"] = write_note
            if isinstance(result.value, dict):
                result.value["cache_write_error"] = write_note
        self._cache_put(key, result)
        return result
