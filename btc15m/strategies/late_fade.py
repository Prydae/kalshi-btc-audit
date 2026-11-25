"""Strategy 01 — locked late-window YES fade (buys NO).

Enters only in three locked feature cells, ``phase|spread|btc_gap_pct quartile``:
``late|medium|q3``, ``late|tight|q3``, ``final|medium|q3``. The q3 boundaries are
the 50th and 75th percentiles of ``btc_gap_pct`` over the training fold.

This lane opts out of the v_lite hour filter, matching the previous roster.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import Side, Snapshot
from .base import Strategy

WINDOW_SECS = 900
Q3_LOWER = -4.1161577125896695e-05
Q3_UPPER = 6.841466030825035e-04
LOCKED_CELLS = frozenset({"late|medium|q3", "late|tight|q3", "final|medium|q3"})


def phase_label(secs_remaining: int) -> str:
    minute = int((WINDOW_SECS - secs_remaining) // 60)
    if minute <= 2:
        return "opening"
    if minute <= 6:
        return "early"
    if minute <= 10:
        return "mid"
    if minute <= 12:
        return "late"
    return "final"


def spread_label(spread: Optional[float]) -> str:
    if spread is None:
        return "unknown"
    cents = spread * 100.0
    if cents < 1.0:
        return "tight"
    if cents < 2.0:
        return "medium"
    return "wide"


@dataclass
class LateWindowFade(Strategy):
    v_lite: bool = False
    skip_et_hour_12: bool = False
    max_open: int = 5
    locked: frozenset = field(default=LOCKED_CELLS)

    def entry(self, s: Snapshot) -> Optional[tuple[Side, float, str]]:
        secs = s.secs_remaining
        if secs is None or secs <= 0 or secs > WINDOW_SECS:
            self.last_skip = f"secs {secs} out of window"
            return None

        if s.btc_price in (None, 0) or s.strike is None:
            self.last_skip = "no BTC reference"
            return None
        gap_pct = (s.btc_price - s.strike) / s.btc_price
        if not (Q3_LOWER <= gap_pct <= Q3_UPPER):
            self.last_skip = f"btc_gap_pct {gap_pct:.6f} not in q3"
            return None

        cell = f"{phase_label(secs)}|{spread_label(s.spread)}|q3"
        if cell not in self.locked:
            self.last_skip = f"cell {cell} not locked"
            return None

        px = s.no_bid
        if px is None:
            self.last_skip = "no NO bid"
            return None
        return "NO", px, f"cell {cell} · gap {gap_pct * 100:+.3f}%"


LANES = [
    LateWindowFade(
        key="S01_LATE_WINDOW_YES_FADE",
        display_name="S01 Late Window Fade",
        description="Locked late/final-window YES fade in the q3 BTC-gap band.",
        side="NO",
    ),
]
