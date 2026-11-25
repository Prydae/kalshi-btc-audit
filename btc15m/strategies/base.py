"""Strategy interface.

A strategy sees a Snapshot and returns Signals. It never places an order,
writes a file, or formats a log line another layer has to parse back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..models import Side, Signal, Snapshot

ET = ZoneInfo("America/New_York")

#: Production filter carried over from the previous system: entries are skipped
#: during these UTC hours for every lane that opts in.
V_LITE_HOURS_UTC = frozenset({12, 13, 14, 15})


def et_hour(ts_unix: float) -> int:
    return datetime.fromtimestamp(ts_unix, tz=ET).hour


def utc_hour(ts_unix: float) -> int:
    return datetime.fromtimestamp(ts_unix, tz=timezone.utc).hour


@dataclass
class Strategy:
    """Base lane. Subclasses implement :meth:`entry`."""

    key: str
    display_name: str
    description: str
    side: Side = "NO"
    #: hold to settlement unless a subclass overrides :meth:`exit`
    v_lite: bool = True
    skip_et_hour_12: bool = True
    enabled: bool = True

    #: tickers this lane has already traded — one entry per window
    _entered: set[str] = field(default_factory=set, repr=False)
    #: why the most recent snapshot did not produce an entry
    last_skip: str = field(default="", repr=False)

    # -- overridable -------------------------------------------------------

    def entry(self, s: Snapshot) -> Optional[tuple[Side, float, str]]:
        """Return ``(side, limit_price, reason)`` to enter, or None."""
        raise NotImplementedError

    def exit(self, s: Snapshot, pos) -> Optional[tuple[float, str]]:
        """Return ``(price, reason)`` to close early. Default: hold to settlement."""
        return None

    # -- driver ------------------------------------------------------------

    def on_snapshot(self, s: Snapshot, open_positions: list) -> list[Signal]:
        out: list[Signal] = []

        for pos in open_positions:
            got = self.exit(s, pos)
            if got:
                price, reason = got
                out.append(Signal(
                    strategy=self.key, action="EXIT", ticker=s.ticker,
                    side=pos.side, price=price, exit_reason=reason,  # type: ignore[arg-type]
                    reason=reason, ts_unix=s.ts_unix,
                ))

        if not self.enabled or s.ticker in self._entered or open_positions:
            return out
        if self.v_lite and utc_hour(s.ts_unix) in V_LITE_HOURS_UTC:
            self.last_skip = "v_lite hours 12-15 UTC"
            return out
        if self.skip_et_hour_12 and et_hour(s.ts_unix) == 12:
            self.last_skip = "ET hour 12"
            return out

        got = self.entry(s)
        if got is None:
            return out
        side, price, reason = got
        self._entered.add(s.ticker)
        self.last_skip = ""
        out.append(Signal(
            strategy=self.key, action="ENTER", ticker=s.ticker,
            side=side, price=price, reason=reason, ts_unix=s.ts_unix,
        ))
        return out

    def on_window_close(self, ticker: str) -> None:
        self._entered.discard(ticker)

    def to_ui(self) -> dict:
        return {
            "key": self.key, "name": self.display_name,
            "description": self.description, "side": self.side,
            "enabled": self.enabled, "last_skip": self.last_skip,
        }
