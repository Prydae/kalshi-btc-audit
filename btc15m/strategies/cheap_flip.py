"""REV01 — filtered cheap-side reversal.

Backtest spec (run26 row-gate): last 30-90s, cheapest side asking 10-15c,
|gap| <= 15 USD, fair edge >= 25c, spread <= 6c. Buy that side at the ask and hold
to settlement.

"Fair edge" leans on ``fair_yes_pct``, a heuristic logistic over the BTC gap
rather than a calibrated model, so this lane is the least well-founded of the
six. It fired zero times in the previous system's logs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Side, Snapshot
from .base import Strategy


@dataclass
class CheapFlip(Strategy):
    #: picks whichever side is cheap at the time, so it has no fixed side
    side_label: str = "ANY"
    secs_min: int = 30
    secs_max: int = 90
    cheap_lo: float = 0.10
    cheap_hi: float = 0.15
    max_abs_gap: float = 15.0
    min_fair_edge: float = 0.25
    max_spread: float = 0.06

    def entry(self, s: Snapshot) -> Optional[tuple[Side, float, str]]:
        secs = s.secs_remaining
        if secs is None or not (self.secs_min <= secs <= self.secs_max):
            self.last_skip = f"secs {secs} outside {self.secs_min}-{self.secs_max}"
            return None

        sp = s.spread
        if sp is None or sp > self.max_spread:
            self.last_skip = f"spread {sp} > {self.max_spread}"
            return None

        gap = s.abs_gap
        if gap is None or gap > self.max_abs_gap:
            self.last_skip = f"|gap| {gap} > {self.max_abs_gap}"
            return None

        fair = s.fair_yes_pct
        if fair is None:
            self.last_skip = "no fair value"
            return None

        # Cheapest side by ask, then require the heuristic fair value to sit
        # well above what that side costs.
        cands: list[tuple[Side, float, float]] = []
        if s.yes_ask is not None:
            cands.append(("YES", s.yes_ask, fair))
        if s.no_ask is not None:
            cands.append(("NO", s.no_ask, 1.0 - fair))
        cands = [c for c in cands if self.cheap_lo <= c[1] <= self.cheap_hi]
        if not cands:
            self.last_skip = f"no side asking {self.cheap_lo}-{self.cheap_hi}"
            return None

        side, ask, fair_side = min(cands, key=lambda c: c[1])
        edge = fair_side - ask
        if edge < self.min_fair_edge:
            self.last_skip = f"edge {edge:.3f} < {self.min_fair_edge}"
            return None

        return side, ask, f"{side} @{ask:.2f} · edge {edge:+.2f} · {secs}s"


LANES = [
    CheapFlip(
        key="REV01_FILTERED_CHEAP_FLIP",
        display_name="REV01 Cheap Flip",
        description="Cheapest side at 10-15c in the last 30-90s with a large fair-value edge.",
    ),
]
