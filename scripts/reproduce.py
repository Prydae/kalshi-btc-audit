#!/usr/bin/env python3
"""Recompute the headline checks on the bundled public sample.

    python scripts/reproduce.py                # table to stdout
    python scripts/reproduce.py --json out.json

Reads data/sample/windows.csv and data/sample/paper_trades.csv (three archived
KXBTC15M days, 23-25 Jun 2026, all with Kalshi-verified labels). Computes:

1. label mismatch rate of the original spot-inferred label vs Kalshi's result,
   overall and by distance from the strike;
2. per-lane P&L in cents per contract under the original and corrected labels,
   with 95% bootstrap intervals over trades.

The sample is three days, so per-lane intervals are wide. The full-archive figures
behind the published results are in RESULTS.md and are not recomputed here.
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from btc15m.labels import mismatch_summary  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
N_BOOT = 5000
SEED = 7


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def bootstrap_ci(xs: list[float], n: int = N_BOOT, seed: int = SEED) -> tuple[float, float]:
    rnd = random.Random(seed)
    k = len(xs)
    means = sorted(sum(xs[rnd.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def pnl_cents(side: str, outcome: str, entry_cents: float) -> float:
    """Per-contract P&L in cents for a buyer at `entry_cents`, held to settlement."""
    return (100.0 if side.lower() == outcome else 0.0) - entry_cents


def run(sample_dir: Path = SAMPLE) -> dict:
    windows = _read(sample_dir / "windows.csv")
    trades = _read(sample_dir / "paper_trades.csv")

    rows = [{
        "ticker": w["ticker"],
        "btc_final": _f(w["btc_final"]),
        "strike": _f(w["strike"]),
        "legacy_outcome": w["legacy_outcome"],
        "kalshi_outcome": w["kalshi_outcome"],
    } for w in windows]
    labels = mismatch_summary(rows)

    by_lane: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "wins_orig": 0, "wins_corr": 0, "pnl_orig": [], "pnl_corr": [], "excluded": 0})
    for t in trades:
        lane = by_lane[t["strategy"]]
        entry = float(t["entry_cents"])
        if t["legacy_outcome"] not in ("yes", "no") or t["kalshi_outcome"] not in ("yes", "no"):
            lane["excluded"] += 1
            continue
        lane["n"] += 1
        lane["wins_orig"] += t["side"].lower() == t["legacy_outcome"]
        lane["wins_corr"] += t["side"].lower() == t["kalshi_outcome"]
        lane["pnl_orig"].append(pnl_cents(t["side"], t["legacy_outcome"], entry))
        lane["pnl_corr"].append(pnl_cents(t["side"], t["kalshi_outcome"], entry))

    lanes = {}
    for name, v in sorted(by_lane.items()):
        n = v["n"]
        lo_o, hi_o = bootstrap_ci(v["pnl_orig"])
        lo_c, hi_c = bootstrap_ci(v["pnl_corr"])
        lanes[name] = {
            "n": n,
            "excluded": v["excluded"],
            "win_rate_original": round(v["wins_orig"] / n, 3),
            "win_rate_corrected": round(v["wins_corr"] / n, 3),
            "cents_per_contract_original": round(sum(v["pnl_orig"]) / n, 2),
            "ci95_original": [round(lo_o, 2), round(hi_o, 2)],
            "cents_per_contract_corrected": round(sum(v["pnl_corr"]) / n, 2),
            "ci95_corrected": [round(lo_c, 2), round(hi_c, 2)],
        }
    return {"windows": len(windows), "trades": len(trades),
            "labels": labels, "lanes": lanes}


def _print(result: dict) -> None:
    L = result["labels"]
    print(f"Sample: {result['windows']} windows, {result['trades']} paper trades (23-25 Jun 2026)\n")
    print(f"Label mismatch (original vs Kalshi result): {L['mismatch']} of {L['usable']} "
          f"= {L['mismatch_rate_pct']}%  (excluded {L['excluded']})")
    print("\nBy distance |BTC - strike| (USD):")
    for band, b in L["bands"].items():
        rate = "n/a" if b["rate_pct"] is None else f"{b['rate_pct']:5.1f}%"
        print(f"  {band:>9}  n={b['n']:4d}  mismatch={b['mismatch']:3d}  rate={rate}")
    print("\nPer-lane P&L, cents per contract (95% bootstrap CI over trades):")
    print(f"  {'lane':34s} {'n':>4s}  {'orig':>7s}  {'CI':>18s}  {'corr':>7s}  {'CI':>18s}")
    for name, v in result["lanes"].items():
        print(f"  {name:34s} {v['n']:4d}  {v['cents_per_contract_original']:+7.2f}  "
              f"{str(v['ci95_original']):>18s}  {v['cents_per_contract_corrected']:+7.2f}  "
              f"{str(v['ci95_corrected']):>18s}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="also write the result to this path")
    ap.add_argument("--sample", type=Path, default=SAMPLE, help="sample directory")
    a = ap.parse_args()
    result = run(a.sample)
    _print(result)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
