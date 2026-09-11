# Data Provider Architecture

## Runtime

```
round1_v2 / pattern / swing
             |
      capability registry
             |
   +---------+----------+----------------+------------------+
   |                    |                |                  |
Fuyao              IW special       Tencent qfq        Jin10 macro
ths_family         ths_family       tencent_family     jin10_family
   |                    |                |
MX / AK cross-source   legacy pattern_history       official risk chain
eastmoney_family       stays on IW; edge uses Eastmoney disclosure/exchange/regulator
```

`data/providers/capabilities.yaml` is the only priority matrix for migrated paths. A `DataResult` carries value, source, provider_family, as_of, status and fallback_from. Same-family comparison is `SAME_VENDOR_ONLY`; it is never represented as independent validation.

## Modes

- `hybrid` (default): provider routing and legacy adapters coexist.
- `legacy`: old task tuples and source order; emergency rollback.
- `fuyao_primary`: reserved for manual activation after sufficient live A/B evidence.

Failures are typed. Non-gate data may degrade visibly; risk verification and other hard-gate inputs fail closed. Provider cache keys distinguish provider, capability, request dimensions, schema version, and partial/complete day.

## Contract boundaries

- **`DataResult.usable` is complete-data semantics.** A provider may return a
  partial value with `status=incomplete` for diagnostics, but `usable=False`;
  statistics and hard-gate callers must not consume it by default.
- **Swing qfq precision has its own capability.** `swing_qfq_history` is
  routed through the registry to Tencent with a 380-row request and a 120-row
  minimum. It records cutoff/as-of/completeness/provenance and fails closed on
  an incomplete sequence. `round1_v2` keeps the unadjusted full-market dump as
  coarse screening only.
- **Legacy and edge pattern history are intentionally different.** Legacy
  `pattern_history` remains on the IWENCAI wide-row route and still requires
  its qfq coverage/field gates because under-delivery can be reported as
  `status=ok` (see `docs/IWENCAI_QFQ_1200_AVAILABILITY_REPORT.md` §1 B2).
  `pattern_edge_history` is the production Eastmoney strict-qfq capability; it
  does not inherit the legacy route or splice another source. Both edge
  statistics and the pattern forward-return backfill (`data/signal_score.py`)
  route to it, because both consume the whole-range qfq series; the IWENCAI
  wide-row contract is only needed by legacy shape matching, which stays on
  `pattern_history`.

## Current verified implementation boundary

Fuyao adapter: daily K, locally aggregated weekly/monthly K, full-market daily dump, limit-up/down/break pools, ladder, hot rank, dragon-tiger list and anomaly. Financials, valuation, index members and full ETF contracts remain registered but fall back until their live schema is recorded. Tencent qfq is only the registry-routed swing precision layer. Jin10 and the formal disclosure chain remain independent.
