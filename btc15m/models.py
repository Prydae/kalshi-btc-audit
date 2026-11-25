"""The types every layer passes around.

Strategies emit a :class:`Signal` object. Nothing downstream parses a log line
to work out what a strategy meant.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

Side = Literal["YES", "NO"]
Action = Literal["ENTER", "EXIT"]
ExitReason = Literal[
    "settlement", "stop_loss", "take_profit", "time_stop",
    "window_close", "entry_timeout", "manual", "shutdown",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso() -> str:
    return utcnow().isoformat()


@dataclass(slots=True)
class Level:
    price: float
    size: float


@dataclass(slots=True)
class Snapshot:
    """One poll of one market, plus the BTC context at that instant."""

    ticker: str
    ts: str
    ts_unix: float
    strike: Optional[float] = None
    secs_remaining: Optional[int] = None
    close_time: str = ""
    status: str = "open"

    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    yes_last: Optional[float] = None

    yes_levels: list[list[float]] = field(default_factory=list)
    no_levels: list[list[float]] = field(default_factory=list)

    volume: float = 0.0
    open_interest: float = 0.0

    btc_price: Optional[float] = None
    btc_velocity: Optional[float] = None
    btc_momentum: Optional[float] = None
    fair_yes_pct: Optional[float] = None
    btc_source: str = "none"

    # ---- derived ---------------------------------------------------------
    @property
    def spread(self) -> Optional[float]:
        if self.yes_ask is None or self.yes_bid is None:
            return None
        return round(self.yes_ask - self.yes_bid, 4)

    @property
    def mid_price(self) -> Optional[float]:
        if self.yes_bid is None or self.no_bid is None:
            return None
        return round((self.yes_bid + (1.0 - self.no_bid)) / 2, 4)

    @property
    def combined_cost(self) -> Optional[float]:
        if self.yes_ask is None or self.no_ask is None:
            return None
        return round(self.yes_ask + self.no_ask, 4)

    @property
    def yes_total_size(self) -> float:
        return round(sum(l[1] for l in self.yes_levels), 2)

    @property
    def no_total_size(self) -> float:
        return round(sum(l[1] for l in self.no_levels), 2)

    @property
    def yes_top3_size(self) -> float:
        return round(sum(l[1] for l in self.yes_levels[:3]), 2)

    @property
    def no_top3_size(self) -> float:
        return round(sum(l[1] for l in self.no_levels[:3]), 2)

    @property
    def ob_imbalance(self) -> float:
        """+1 = all resting size on YES, -1 = all on NO."""
        y, n = self.yes_total_size, self.no_total_size
        t = y + n
        return round((y - n) / t, 4) if t > 0 else 0.0

    @property
    def signed_gap(self) -> Optional[float]:
        if self.btc_price is None or self.strike is None:
            return None
        return round(self.btc_price - self.strike, 2)

    @property
    def abs_gap(self) -> Optional[float]:
        g = self.signed_gap
        return None if g is None else abs(g)

    @property
    def moneyness_bps(self) -> Optional[float]:
        """|BTC - strike| in basis points of the strike."""
        if self.strike in (None, 0) or self.btc_price is None:
            return None
        return round(abs(self.btc_price - self.strike) / self.strike * 10_000, 2)

    def bid(self, side: Side) -> Optional[float]:
        return self.yes_bid if side == "YES" else self.no_bid

    def ask(self, side: Side) -> Optional[float]:
        return self.yes_ask if side == "YES" else self.no_ask

    def to_ui(self) -> dict:
        return {
            "ticker": self.ticker, "ts_unix": self.ts_unix, "strike": self.strike,
            "secs_remaining": self.secs_remaining, "status": self.status,
            "yes_bid": self.yes_bid, "yes_ask": self.yes_ask,
            "no_bid": self.no_bid, "no_ask": self.no_ask,
            "yes_levels": self.yes_levels, "no_levels": self.no_levels,
            "volume": self.volume, "open_interest": self.open_interest,
            "spread": self.spread, "mid_price": self.mid_price,
            "ob_imbalance": self.ob_imbalance,
            "btc_price": self.btc_price, "btc_velocity": self.btc_velocity,
            "btc_momentum": self.btc_momentum, "btc_source": self.btc_source,
            "fair_yes_pct": self.fair_yes_pct,
            "signed_gap": self.signed_gap, "moneyness_bps": self.moneyness_bps,
            "yes_total_size": self.yes_total_size, "no_total_size": self.no_total_size,
        }


@dataclass(slots=True)
class Signal:
    """A strategy's decision. Typed — never a string another layer re-parses."""

    strategy: str
    action: Action
    ticker: str
    side: Side
    price: float                      # limit / reference price, 0-1 dollars
    reason: str = ""
    exit_reason: Optional[ExitReason] = None
    contracts: Optional[int] = None   # None = size from notional
    ts_unix: float = field(default_factory=time.time)


@dataclass(slots=True)
class Position:
    strategy: str
    ticker: str
    side: Side
    entry_price: float
    contracts: int
    entry_time: str
    strike: Optional[float] = None
    secs_at_entry: Optional[int] = None
    mode: Literal["paper", "live"] = "paper"
    entry_reason: str = ""

    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    settled: bool = False

    order_id: Optional[str] = None
    filled: bool = True

    @property
    def cost(self) -> float:
        return round(self.entry_price * self.contracts, 4)

    def mark(self, snap: Optional[Snapshot]) -> Optional[float]:
        """Unrealised PnL at the current bid for this side."""
        if snap is None or self.settled:
            return None
        b = snap.bid(self.side)
        if b is None:
            return None
        return round((b - self.entry_price) * self.contracts, 4)

    def close(self, exit_price: float, reason: str) -> float:
        self.exit_price = round(exit_price, 4)
        self.exit_time = iso()
        self.exit_reason = reason
        self.pnl = round((self.exit_price - self.entry_price) * self.contracts, 4)
        self.settled = True
        return self.pnl

    def to_ui(self) -> dict:
        return {
            "strategy": self.strategy, "ticker": self.ticker, "side": self.side,
            "entry_price": self.entry_price, "contracts": self.contracts,
            "cost": self.cost, "entry_time": self.entry_time, "strike": self.strike,
            "secs_at_entry": self.secs_at_entry, "mode": self.mode,
            "entry_reason": self.entry_reason,
            "exit_price": self.exit_price, "exit_time": self.exit_time,
            "exit_reason": self.exit_reason, "pnl": self.pnl,
            "settled": self.settled, "filled": self.filled,
        }
