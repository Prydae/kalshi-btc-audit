"""Poll the front KXBTC15M market and turn each poll into a Snapshot.

The series runs one open market at a time. The orderbook is refetched every
poll; market metadata and the trade tape are refetched on slower cadences, which
keeps the request rate near 6/s instead of 15/s while the book still updates at
the full poll rate.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Protocol

from .config import settings
from .models import Snapshot, iso

# STUB: the private project's public-data REST client (client.py) is not included.
# The collector only needs these four read-only methods, so they are declared as a
# Protocol. Any object with these methods (for example a recorded-replay source)
# can drive the collector. The signed account/order client is intentionally absent.
class MarketSource(Protocol):
    async def open_markets(self) -> list[dict]: ...
    async def market(self, ticker: str) -> dict: ...
    async def orderbook(self, ticker: str) -> dict: ...
    async def trades(self, ticker: str, limit: int = 25) -> list[dict]: ...


# STUB: the BTC reference feed (btcfeed.py, live WebSocket feeds) is not included.
# The collector only calls metrics(); it is declared as a Protocol here.
class ReferenceFeed(Protocol):
    def metrics(self, strike: Optional[float] = None,
                secs_remaining: Optional[int] = None) -> dict: ...


log = logging.getLogger("collector")

META_EVERY = 2.0
TRADES_EVERY = 1.0
_STRIKE_KEYS = ("floor_strike", "floor_strike_dollars", "cap_strike",
                "cap_strike_dollars", "strike_dollars", "strike_value")


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_strike(m: dict) -> Optional[float]:
    for k in _STRIKE_KEYS:
        v = _num(m.get(k))
        if v is not None:
            return v
    return None


def _levels(raw: list) -> list[list[float]]:
    """Kalshi returns [[price, size], ...] ascending. Best bid first out."""
    out: list[list[float]] = []
    for item in raw or []:
        try:
            p, s = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if p > 0 and s > 0:
            out.append([round(p, 4), round(s, 2)])
    out.sort(key=lambda x: -x[0])
    return out


def secs_to_close(close_time: str) -> Optional[int]:
    if not close_time:
        return None
    try:
        dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))


class Collector:
    def __init__(self, client: MarketSource, feed: ReferenceFeed) -> None:
        self.client = client
        self.feed = feed
        self.market: dict = {}
        self.ticker: str = ""
        self._meta: dict = {}
        self._t_list = 0.0
        self._t_meta = 0.0
        self._t_trades = 0.0
        self.polls = 0

    async def refresh_market(self, force: bool = False) -> Optional[str]:
        """Returns the previous ticker if the front market rolled over."""
        now = time.time()
        if not force and now - self._t_list < settings.market_refresh_secs:
            return None
        self._t_list = now
        markets = await self.client.open_markets()
        if not markets:
            return None
        front = markets[0]
        prev = self.ticker
        if front.get("ticker") != prev:
            self.market = front
            self.ticker = front.get("ticker", "")
            self._meta = front
            self._t_meta = now
            log.info("front market: %s -> %s", prev or "(none)", self.ticker)
            return prev or None
        self.market = front
        return None

    async def poll(self) -> Optional[Snapshot]:
        if not self.ticker:
            return None
        now = time.time()

        ob = await self.client.orderbook(self.ticker)
        fp = ob.get("orderbook_fp") or {}
        yes = _levels(fp.get("yes_dollars"))
        no = _levels(fp.get("no_dollars"))
        if not yes and not no:
            legacy = ob.get("orderbook") or {}
            yes = _levels([[r[0] / 100, r[1]] for r in legacy.get("yes") or [] if len(r) >= 2])
            no = _levels([[r[0] / 100, r[1]] for r in legacy.get("no") or [] if len(r) >= 2])

        if now - self._t_meta >= META_EVERY:
            self._t_meta = now
            fresh = await self.client.market(self.ticker)
            if fresh:
                self._meta = fresh
        m = self._meta or self.market

        yes_bid = yes[0][0] if yes else None
        no_bid = no[0][0] if no else None
        # On a binary book the two sides are complements: the YES ask is
        # whatever a NO bidder is paying, inverted.
        yes_ask = round(1.0 - no_bid, 4) if no_bid is not None else None
        no_ask = round(1.0 - yes_bid, 4) if yes_bid is not None else None

        close_time = m.get("close_time", "")
        strike = parse_strike(m)
        secs = secs_to_close(close_time)
        bm = self.feed.metrics(strike=strike, secs_remaining=secs)

        snap = Snapshot(
            ticker=self.ticker, ts=iso(), ts_unix=now,
            strike=strike, secs_remaining=secs, close_time=close_time,
            status=m.get("status", "open"),
            yes_bid=yes_bid, yes_ask=yes_ask, no_bid=no_bid, no_ask=no_ask,
            yes_last=_num(m.get("last_price_dollars")) or _num(m.get("last_price")),
            yes_levels=yes[: settings.depth], no_levels=no[: settings.depth],
            volume=_num(m.get("volume_fp")) or _num(m.get("volume")) or 0.0,
            open_interest=_num(m.get("open_interest_fp")) or _num(m.get("open_interest")) or 0.0,
            btc_price=bm["price"], btc_velocity=bm["velocity"],
            btc_momentum=bm["momentum"], fair_yes_pct=bm["fair_yes_pct"],
            btc_source=bm["source"],
        )
        self.polls += 1
        return snap

    async def poll_trades(self, snap: Snapshot) -> list[dict]:
        now = time.time()
        if now - self._t_trades < TRADES_EVERY:
            return []
        self._t_trades = now
        raw = await self.client.trades(self.ticker)
        out = []
        for t in raw:
            out.append({
                "ts": t.get("created_time", snap.ts),
                "ts_unix": now,
                "ticker": self.ticker,
                "strike": snap.strike,
                "trade_id": t.get("trade_id"),
                "side": t.get("taker_outcome_side") or t.get("taker_side"),
                "yes_price": _num(t.get("yes_price_dollars")) or _num(t.get("yes_price")),
                "no_price": _num(t.get("no_price_dollars")) or _num(t.get("no_price")),
                "count": _num(t.get("count_fp")) or _num(t.get("count")) or 0.0,
                "taker_side": t.get("taker_side"),
                "secs_remaining": snap.secs_remaining,
            })
        return [t for t in out if t["trade_id"]]
