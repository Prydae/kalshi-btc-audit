"""Fade a crowded favourite by buying NO.

Three lanes, one shape: when the resting book is skewed toward YES in a market
that is wide and mid-clock, buy NO at the bid and hold to settlement. Thresholds
are the frozen values from ``quant_paper_frozen_registry.py``.

The frozen specs also carried ``yes_bid_min/max``. Those were dead — the old
gate only ever read ``no_bid`` on a NO lane, and since ``yes_bid + no_bid <= 1``
on a real book they could never both hold. They are not reproduced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Side, Snapshot
from .base import Strategy


@dataclass
class BookFade(Strategy):
    secs_min: int = 0
    secs_max: int = 900
    imb_min: float = 0.0            # book must be at least this YES-skewed
    no_bid_min: float = 0.0
    no_bid_max: float = 1.0
    mny_max_bps: float = 500.0
    mny_min_bps: float = 0.0
    spread_min: float = 0.01
    abs_gap_max: Optional[float] = None

    def entry(self, s: Snapshot) -> Optional[tuple[Side, float, str]]:
        secs = s.secs_remaining
        if secs is None or not (self.secs_min <= secs <= self.secs_max):
            self.last_skip = f"secs {secs} outside {self.secs_min}-{self.secs_max}"
            return None

        sp = s.spread
        if sp is None or sp < self.spread_min:
            self.last_skip = f"spread {sp} < {self.spread_min}"
            return None

        if s.ob_imbalance < self.imb_min:
            self.last_skip = f"imbalance {s.ob_imbalance:+.3f} < {self.imb_min:+.3f}"
            return None

        nb = s.no_bid
        if nb is None or not (self.no_bid_min <= nb <= self.no_bid_max):
            self.last_skip = f"no_bid {nb} outside {self.no_bid_min}-{self.no_bid_max}"
            return None

        mny = s.moneyness_bps
        if mny is None or not (self.mny_min_bps <= mny <= self.mny_max_bps):
            self.last_skip = f"moneyness {mny} outside {self.mny_min_bps}-{self.mny_max_bps} bps"
            return None

        if self.abs_gap_max is not None:
            g = s.abs_gap
            if g is None or g > self.abs_gap_max:
                self.last_skip = f"|gap| {g} > {self.abs_gap_max}"
                return None

        return "NO", nb, (
            f"imb {s.ob_imbalance:+.3f} · no_bid {nb:.2f} · {secs}s · {mny:.0f}bps"
        )


LANES = [
    BookFade(
        key="TA_L_burst_wide_fade_no",
        display_name="L Burst Wide Fade",
        description="Short mid-window, wide book, YES-heavy — fade with NO, hold to settle.",
        secs_min=140, secs_max=280, imb_min=0.1492,
        no_bid_min=0.64, no_bid_max=0.92, mny_max_bps=520.0,
    ),
    BookFade(
        key="TB_Q_midwide_yesheavy_fade_no",
        display_name="Q Midwide YES-heavy Fade",
        description="Mid clock, wide book, YES skew — fade with NO, hold to settle.",
        secs_min=180, secs_max=340, imb_min=0.07795,
        no_bid_min=0.62, no_bid_max=0.90, mny_max_bps=500.0,
    ),
    BookFade(
        key="TB_N_stale_wide_crowded_yes_no",
        display_name="N Stale Midclock Fade",
        description="Mid clock, wide, crowded YES — fade with NO within 75 USD of strike.",
        # The live-recommended overlay tightened this lane from 220s to 360s
        # and added the gap cap; both are folded in here.
        secs_min=360, secs_max=520, imb_min=0.1492,
        no_bid_min=0.72, no_bid_max=0.94, mny_max_bps=500.0,
        abs_gap_max=75.0,
    ),
]
