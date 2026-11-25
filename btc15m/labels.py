"""Settlement labels: the original rule, the corrected rule, and the mismatch summary.

Two ways to label a 15-minute window:

* **Original (spot-inferred):** `yes` if the BTC spot price at close is at or above
  the strike, otherwise `no`. This is what the early system stored in
  `windows.outcome`.
* **Corrected (Kalshi result):** the market's own `result` field (`yes` / `no`) from
  Kalshi's public market endpoint. KXBTC15M settles on a 60-second average of
  CF Benchmarks' BRTI, not on the spot feed, so the two disagree in some windows.

This module contains only the pure logic. The network fetch used by the original
backfill tool is a STUB below.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: distance-to-strike bands in USD, as used in the published analysis
BANDS: tuple[tuple[float, float], ...] = (
    (0, 5), (5, 10), (10, 25), (25, 50), (50, 100), (100, float("inf")),
)


def legacy_label(btc_final: Optional[float], strike: Optional[float]) -> Optional[str]:
    """Original spot-inferred rule."""
    if btc_final is None or strike is None:
        return None
    return "yes" if btc_final >= strike else "no"


def parse_result(payload: dict) -> Optional[str]:
    """Extract the settled result from a Kalshi market payload.

    Accepts the `{"market": {"result": ...}}` shape. Returns "yes", "no", or None
    when the market has no settled result yet.
    """
    res = (((payload or {}).get("market") or {}).get("result") or "").strip().lower()
    return res if res in ("yes", "no") else None


def fetch_kalshi_result(ticker: str) -> Optional[str]:
    """STUB: the network call that fetched a market's `result` during the backfill.

    Omitted from the public copy. The stored `outcome_source='kalshi_result'` values
    in the sample data are the record of what it returned. Use `parse_result` on
    any payload you obtain.
    """
    raise NotImplementedError("fetch_kalshi_result is a STUB in the public copy.")


def band_label(distance: float) -> str:
    for lo, hi in BANDS:
        if lo <= distance < hi:
            return f"{lo:g}-{'+' if hi == float('inf') else f'{hi:g}'}"
    return "n/a"


def mismatch_summary(rows: Iterable[dict]) -> dict:
    """Mismatch rate of the original label against the Kalshi label.

    Each row needs `btc_final`, `strike`, `legacy_outcome` and `kalshi_outcome`.
    Rows missing a value are excluded and counted in `excluded`.
    """
    usable, excluded = [], 0
    for r in rows:
        ok = (r.get("btc_final") is not None and r.get("strike") is not None
              and r.get("legacy_outcome") in ("yes", "no")
              and r.get("kalshi_outcome") in ("yes", "no"))
        if ok:
            usable.append(r)
        else:
            excluded += 1
    mism = [r for r in usable if r["legacy_outcome"] != r["kalshi_outcome"]]
    bands = {}
    for lo, hi in BANDS:
        label = band_label(lo)
        sub = [r for r in usable if lo <= abs(r["btc_final"] - r["strike"]) < hi]
        m = sum(1 for r in sub if r["legacy_outcome"] != r["kalshi_outcome"])
        bands[label] = {"n": len(sub), "mismatch": m,
                        "rate_pct": round(100 * m / len(sub), 2) if sub else None}
    return {
        "usable": len(usable),
        "excluded": excluded,
        "mismatch": len(mism),
        "mismatch_rate_pct": round(100 * len(mism) / len(usable), 2) if usable else None,
        "bands": bands,
        "legacy_rule_agreement": sum(
            1 for r in usable
            if legacy_label(r["btc_final"], r["strike"]) == r["legacy_outcome"]),
    }
