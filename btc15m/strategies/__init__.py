"""The active roster.

Six lanes, carried over from the previous system's
``ACTIVE_DASHBOARD_STRATEGY_KEYS``. Everything else in that codebase was
retired; the retired names are not reproduced here.
"""
from __future__ import annotations

from .base import Strategy
from .book_fade import LANES as _BOOK_FADE
from .cheap_flip import LANES as _CHEAP_FLIP
from .late_fade import LANES as _LATE_FADE
from .prob_bucket import LANES as _PROB_BUCKET

ALL: list[Strategy] = [*_BOOK_FADE, *_PROB_BUCKET, *_LATE_FADE, *_CHEAP_FLIP]

BY_KEY: dict[str, Strategy] = {s.key: s for s in ALL}

#: Lanes that may be armed for real money. TA_L was 81% correlated with the
#: other two fade lanes and had the weakest average PnL of the trio, so it
#: stays paper-only.
LIVE_ELIGIBLE = frozenset(
    k for k in BY_KEY if k != "TA_L_burst_wide_fade_no"
)

__all__ = ["ALL", "BY_KEY", "LIVE_ELIGIBLE", "Strategy"]
