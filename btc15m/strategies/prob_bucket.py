"""Mined probability bucket: NO at 50-70c with book pressure behind it.

Research rule ``NO|120-420|50-70c|any|any|book_with`` — 79 trades, 68.3% win
rate, positive in 4 of 4 folds. Buy at the bid, hold to settlement, no TP/SL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Side, Snapshot
from .base import Strategy


def book_bucket(side: Side, imb: Optional[float]) -> str:
    """Imbalance signed so positive means the book leans the way we're buying."""
    if imb is None:
        return "imb_na"
    v = imb if side == "YES" else -imb
    if v < -0.20:
        return "book_against"
    if v <= 0.20:
        return "book_neutral"
    return "book_with"


@dataclass
class ProbBucket(Strategy):
    secs_min: int = 120
    secs_max: int = 420
    price_min: float = 0.50
    price_max: float = 0.70
    want_book: str = "book_with"

    def entry(self, s: Snapshot) -> Optional[tuple[Side, float, str]]:
        secs = s.secs_remaining
        if secs is None or not (self.secs_min <= secs <= self.secs_max):
            self.last_skip = f"secs {secs} outside {self.secs_min}-{self.secs_max}"
            return None

        px = s.bid(self.side)
        if px is None or not (self.price_min <= px <= self.price_max):
            self.last_skip = f"{self.side.lower()}_bid {px} outside {self.price_min}-{self.price_max}"
            return None

        bucket = book_bucket(self.side, s.ob_imbalance)
        if self.want_book != "any" and bucket != self.want_book:
            self.last_skip = f"book {bucket} != {self.want_book}"
            return None

        return self.side, px, f"{px:.2f} · {bucket} · {secs}s"


LANES = [
    ProbBucket(
        key="PR_NO_50_70_BOOK",
        display_name="Prob NO 50-70 Book",
        description="NO at 50-70c, 120-420s left, book pressure behind NO.",
        side="NO",
    ),
]
