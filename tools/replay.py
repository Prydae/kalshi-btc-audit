"""Replay archived snapshots through the live strategy code.

    python tools/replay.py data/archive/daily/kalshi_20260620.db
    python tools/replay.py data/archive/daily/*.db --lane TB_N_stale_wide_crowded_yes_no
    python tools/replay.py data/archive/daily/*.db --legacy

Runs the exact classes the paper engine runs, so a lane that fires here fires in
the terminal. Archives are opened read-only.

Label caveat: `windows.outcome` in early archives was inferred from the BTC spot
feed. After the backfill, `outcome` holds Kalshi's own result and `outcome_legacy`
holds the spot-inferred value. The two disagree in 7.95% of Kalshi-verified windows
(84 of 1,056), concentrated near the strike. Use `--legacy` to score the same
entries under the original labels. The reproduce script in scripts/ runs this
comparison on a small public sample.
"""
from __future__ import annotations

import argparse
import glob
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from btc15m.models import Snapshot                    # noqa: E402
from btc15m.paper import PaperEngine                  # noqa: E402
from btc15m.strategies import ALL                     # noqa: E402


class NullStore:
    def save_position(self, _p) -> None:
        pass


def snapshot_from_row(r: sqlite3.Row) -> Snapshot:
    import json

    def lv(raw):
        try:
            return json.loads(raw) if raw else []
        except (TypeError, ValueError):
            return []

    return Snapshot(
        ticker=r["ticker"], ts=r["ts"], ts_unix=r["ts_unix"],
        strike=r["strike"], secs_remaining=r["secs_remaining"],
        status=r["status"] or "open",
        yes_bid=r["yes_bid"], yes_ask=r["yes_ask"],
        no_bid=r["no_bid"], no_ask=r["no_ask"], yes_last=r["yes_last"],
        yes_levels=lv(r["yes_levels"]), no_levels=lv(r["no_levels"]),
        volume=r["volume"] or 0.0, open_interest=r["open_interest"] or 0.0,
        btc_price=r["btc_price"], btc_velocity=r["btc_velocity"],
        btc_momentum=r["btc_momentum"], fair_yes_pct=r["fair_yes_pct"],
    )


def replay(paths: list[str], lanes: set[str] | None, limit_windows: int | None,
           legacy: bool = False) -> None:
    for s in ALL:
        s.enabled = (lanes is None) or (s.key in lanes)

    engine = PaperEngine(NullStore())
    outcomes: dict[str, str] = {}
    seen_windows: set[str] = set()
    snaps = 0

    for path in paths:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(windows)")}
        # After a backfill, `outcome` is Kalshi's own result and `outcome_legacy`
        # holds what the old bot inferred from spot. --legacy replays the latter
        # so the two can be compared directly.
        col = "outcome_legacy" if (legacy and "outcome_legacy" in cols) else "outcome"
        for t, o in con.execute(
            f"SELECT ticker, {col} FROM windows WHERE {col} IS NOT NULL"
        ):
            outcomes[t] = o

        current = None
        q = ("SELECT * FROM orderbook_snapshots WHERE yes_bid IS NOT NULL "
             "ORDER BY ts_unix ASC")
        for row in con.execute(q):
            tk = row["ticker"]
            if tk != current:
                if current is not None:
                    engine.settle(current, outcomes.get(current))
                current = tk
                seen_windows.add(tk)
                if limit_windows and len(seen_windows) > limit_windows:
                    current = None
                    break
            engine.on_snapshot(snapshot_from_row(row))
            snaps += 1
        if current is not None:
            engine.settle(current, outcomes.get(current))
        con.close()
        print(f"  read {Path(path).name}", flush=True)

    labelled = sum(1 for w in seen_windows if w in outcomes)
    print(f"\n{snaps:,} snapshots · {len(seen_windows):,} windows "
          f"({labelled:,} labelled)\n")

    hdr = f"{'lane':34s}{'trades':>7s}{'WR':>8s}{'PnL':>10s}{'ROI':>8s}{'fires/win':>11s}"
    print(hdr)
    print("-" * len(hdr))
    total = 0.0
    for lane in engine.lanes.values():
        if not lane.strategy.enabled:
            continue
        n = len(lane.closed)
        total += lane.realised
        wr = f"{lane.win_rate * 100:.1f}%" if lane.win_rate is not None else "--"
        roi = f"{lane.roi * 100:+.2f}%" if lane.roi is not None else "--"
        rate = f"{n / len(seen_windows) * 100:.1f}%" if seen_windows else "--"
        print(f"{lane.key:34s}{n:>7d}{wr:>8s}{lane.realised:>+10.2f}{roi:>8s}{rate:>11s}")
    print("-" * len(hdr))
    print(f"{'TOTAL':34s}{'':>7s}{'':>8s}{total:>+10.2f}")

    by_reason: dict[str, int] = defaultdict(int)
    for lane in engine.lanes.values():
        for p in lane.closed:
            by_reason[p.exit_reason or "?"] += 1
    if by_reason:
        print("\nexits: " + " · ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help="archive .db files (globs allowed)")
    ap.add_argument("--lane", action="append", help="restrict to these lanes")
    ap.add_argument("--windows", type=int, help="stop after N windows per file")
    ap.add_argument("--legacy", action="store_true", help="replay the pre-backfill spot-inferred labels")
    a = ap.parse_args()

    paths: list[str] = []
    for p in a.paths:
        paths.extend(sorted(glob.glob(p)) or [p])
    paths = [p for p in paths if Path(p).is_file()]
    if not paths:
        sys.exit("no databases matched")

    replay(paths, set(a.lane) if a.lane else None, a.windows, a.legacy)


if __name__ == "__main__":
    main()
