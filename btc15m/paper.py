"""Paper execution and settlement.

Current fill model: **every entry fills, in full, immediately, at the signal
price.** No queue position, no partial fills, no adverse selection. That is
deliberate, since it isolates signal quality from execution, but it is
optimistic. Paper results are an upper bound on what a live resting order
would have earned.

Positions are held to settlement unless a lane returns an early exit.

Public-copy note: the private project also tracked simulated cash per lane.
That tracking is removed here; this repo reports cents per contract only.
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import settings
from .models import Position, Signal, Snapshot, iso
from .strategies import ALL, Strategy

log = logging.getLogger("paper")


def contracts_for(notional: float, price: float) -> int:
    return max(1, int(notional / max(price, 0.01)))


class Lane:
    """Per-strategy paper ledger."""

    def __init__(self, strategy: Strategy) -> None:
        self.strategy = strategy
        self.key = strategy.key
        self.open: list[Position] = []
        self.closed: list[Position] = []

    # -- stats -------------------------------------------------------------

    @property
    def realised(self) -> float:
        return round(sum(p.pnl or 0.0 for p in self.closed), 4)

    @property
    def wins(self) -> int:
        return sum(1 for p in self.closed if (p.pnl or 0) > 0)

    @property
    def losses(self) -> int:
        return sum(1 for p in self.closed if (p.pnl or 0) <= 0)

    @property
    def win_rate(self) -> Optional[float]:
        n = len(self.closed)
        return round(self.wins / n, 4) if n else None

    def unrealised(self, snap: Optional[Snapshot]) -> float:
        return round(sum(p.mark(snap) or 0.0 for p in self.open), 4)

    @property
    def notional(self) -> float:
        return round(sum(p.cost for p in self.closed), 4)

    @property
    def roi(self) -> Optional[float]:
        n = self.notional
        return round(self.realised / n, 4) if n else None

    def to_ui(self, snap: Optional[Snapshot]) -> dict:
        return {
            "key": self.key,
            "name": self.strategy.display_name,
            "description": self.strategy.description,
            "side": getattr(self.strategy, "side_label", None) or self.strategy.side,
            "enabled": self.strategy.enabled,
            "last_skip": self.strategy.last_skip,
            "trades": len(self.closed),
            "open": len(self.open),
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "realised": self.realised,
            "unrealised": self.unrealised(snap),
            "roi": self.roi,
            "notional": self.notional,
        }


class PaperEngine:
    def __init__(self, store, notional: Optional[float] = None) -> None:
        self.store = store
        self.notional = notional if notional is not None else settings.paper_notional_usd
        self.lanes: dict[str, Lane] = {
            s.key: Lane(s) for s in ALL
        }

    # -- driving -----------------------------------------------------------

    def on_snapshot(self, snap: Snapshot) -> list[Signal]:
        """Run every lane, apply the resulting signals, return them for the UI."""
        applied: list[Signal] = []
        for lane in self.lanes.values():
            open_here = [p for p in lane.open if p.ticker == snap.ticker]
            for sig in lane.strategy.on_snapshot(snap, open_here):
                if self._apply(lane, sig, snap):
                    applied.append(sig)
        return applied

    def _apply(self, lane: Lane, sig: Signal, snap: Snapshot) -> bool:
        if sig.action == "ENTER":
            return self._enter(lane, sig, snap)
        return self._exit(lane, sig)

    def _enter(self, lane: Lane, sig: Signal, snap: Snapshot) -> bool:
        price = sig.price
        if price is None or price <= 0 or price >= 1:
            return False
        n = sig.contracts or contracts_for(self.notional, price)
        pos = Position(
            strategy=lane.key, ticker=sig.ticker, side=sig.side,
            entry_price=round(price, 4), contracts=n, entry_time=iso(),
            strike=snap.strike, secs_at_entry=snap.secs_remaining,
            mode="paper", entry_reason=sig.reason,
            filled=settings.paper_assume_full_fill,
        )
        lane.open.append(pos)
        log.info("[%s] ENTER %s %dx @%.2f — %s", lane.key, sig.side, n, price, sig.reason)
        return True

    def _exit(self, lane: Lane, sig: Signal) -> bool:
        for pos in list(lane.open):
            if pos.ticker != sig.ticker or pos.side != sig.side:
                continue
            pnl = pos.close(sig.price, sig.exit_reason or "manual")
            lane.open.remove(pos)
            lane.closed.append(pos)
            self.store.save_position(pos)
            log.info("[%s] EXIT %s @%.2f  pnl %+.2f (%s)",
                     lane.key, pos.side, pos.exit_price, pnl, pos.exit_reason)
            return True
        return False

    # -- settlement --------------------------------------------------------

    def settle(self, ticker: str, outcome: Optional[str]) -> list[Position]:
        """Close every open position on ``ticker`` against the settled outcome."""
        done: list[Position] = []
        for lane in self.lanes.values():
            lane.strategy.on_window_close(ticker)
            for pos in list(lane.open):
                if pos.ticker != ticker:
                    continue
                if outcome is None:
                    price = pos.entry_price          # unknown result: scratch
                    reason = "no_settlement_data"
                else:
                    won = pos.side.lower() == outcome
                    price = 1.0 if won else 0.0
                    reason = "settlement"
                pnl = pos.close(price, reason)
                lane.open.remove(pos)
                lane.closed.append(pos)
                self.store.save_position(pos)
                done.append(pos)
                log.info("[%s] SETTLED %s %s  pnl %+.2f",
                         lane.key, pos.side, outcome, pnl)
        return done

    # -- reporting ---------------------------------------------------------

    @property
    def total_realised(self) -> float:
        return round(sum(l.realised for l in self.lanes.values()), 4)

    def total_unrealised(self, snap: Optional[Snapshot]) -> float:
        return round(sum(l.unrealised(snap) for l in self.lanes.values()), 4)

    def open_positions(self) -> list[Position]:
        return [p for l in self.lanes.values() for p in l.open]

    def to_ui(self, snap: Optional[Snapshot]) -> dict:
        return {
            "lanes": [l.to_ui(snap) for l in self.lanes.values()],
            "realised": self.total_realised,
            "unrealised": self.total_unrealised(snap),
            "open": len(self.open_positions()),
            "trades": sum(len(l.closed) for l in self.lanes.values()),
            "assume_full_fill": settings.paper_assume_full_fill,
            "notional": self.notional,
        }
