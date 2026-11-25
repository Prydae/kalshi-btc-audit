"""SQLite persistence.

Schema matches the archived corpus in ``data/archive`` column-for-column, so
newly collected days union directly with the 5,747 windows already on disk.

Writes are buffered and flushed on a worker thread so the poll loop never
blocks on disk.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .models import Position, Snapshot

log = logging.getLogger("store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, ts_unix REAL NOT NULL, ticker TEXT NOT NULL,
    strike REAL, secs_remaining INTEGER,
    yes_bid REAL, yes_ask REAL, no_bid REAL, no_ask REAL, yes_last REAL,
    combined_cost REAL, yes_levels TEXT, no_levels TEXT,
    yes_total_size REAL, no_total_size REAL, yes_top3_size REAL, no_top3_size REAL,
    ob_imbalance REAL, volume REAL, open_interest REAL, status TEXT, source TEXT,
    btc_price REAL, btc_velocity REAL, btc_momentum REAL, fair_yes_pct REAL,
    spread REAL, mid_price REAL,
    btc_gap_to_strike REAL, btc_signed_gap REAL, contract_velocity REAL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, ts_unix REAL NOT NULL, ticker TEXT NOT NULL, strike REAL,
    trade_id TEXT UNIQUE, side TEXT, yes_price REAL, no_price REAL,
    count REAL, taker_side TEXT, secs_remaining INTEGER
);
CREATE TABLE IF NOT EXISTS windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE, strike REAL, open_time TEXT, close_time TEXT,
    open_ts_unix REAL, close_ts_unix REAL,
    open_yes_bid REAL, open_no_bid REAL, close_yes_bid REAL, close_no_bid REAL,
    settled INTEGER DEFAULT 0, outcome TEXT, outcome_source TEXT,
    btc_final REAL, btc_vs_strike REAL,
    snapshot_count INTEGER DEFAULT 0, total_volume REAL
);
CREATE TABLE IF NOT EXISTS btc_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, ts_unix REAL NOT NULL, price REAL NOT NULL,
    source TEXT, velocity REAL, momentum REAL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL,
    mode TEXT NOT NULL, entry_price REAL, contracts INTEGER, cost REAL,
    entry_time TEXT, exit_price REAL, exit_time TEXT, exit_reason TEXT,
    pnl REAL, strike REAL, secs_at_entry INTEGER,
    entry_reason TEXT, order_id TEXT, filled INTEGER DEFAULT 1,
    UNIQUE(strategy, ticker, mode, entry_time)
);
CREATE INDEX IF NOT EXISTS ix_ob_ticker_ts ON orderbook_snapshots(ticker, ts_unix);
CREATE INDEX IF NOT EXISTS ix_ob_ts        ON orderbook_snapshots(ts_unix);
CREATE INDEX IF NOT EXISTS ix_tr_ticker_ts ON trades(ticker, ts_unix);
CREATE INDEX IF NOT EXISTS ix_win_close    ON windows(close_ts_unix);
CREATE INDEX IF NOT EXISTS ix_pos_strategy ON positions(strategy, mode);
"""

_OB_COLS = (
    "ts, ts_unix, ticker, strike, secs_remaining, yes_bid, yes_ask, no_bid, no_ask, "
    "yes_last, combined_cost, yes_levels, no_levels, yes_total_size, no_total_size, "
    "yes_top3_size, no_top3_size, ob_imbalance, volume, open_interest, status, source, "
    "btc_price, btc_velocity, btc_momentum, fair_yes_pct, spread, mid_price, "
    "btc_gap_to_strike, btc_signed_gap, contract_velocity"
)


def _pragmas(c: sqlite3.Connection) -> None:
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-64000")


class Store:
    """One SQLite file per UTC day, rotating at midnight."""

    def __init__(self) -> None:
        self.dir = Path(settings.db_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._day = ""
        self._conn: Optional[sqlite3.Connection] = None
        self._buf: list[tuple] = []
        self._last_mid: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()
        self.snapshots_written = 0
        self.trades_written = 0
        self._seen_trades: set[str] = set()
        self._open()

    # -- lifecycle ---------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.dir / f"kalshi_{self._day}.db"

    def _open(self) -> None:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        if day == self._day and self._conn is not None:
            return
        if self._conn is not None:
            self._flush_sync()
            self._conn.close()
        self._day = day
        c = sqlite3.connect(str(self.path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        _pragmas(c)
        c.executescript(SCHEMA)
        c.commit()
        self._conn = c
        row = c.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()
        self.snapshots_written = row[0] if row else 0
        log.info("store: %s (%d snapshots)", self.path.name, self.snapshots_written)

    def close(self) -> None:
        self._flush_sync()
        if self._conn is not None:
            with_ = self._conn
            self._conn = None
            with_.close()

    # -- writes ------------------------------------------------------------

    def add_snapshot(self, s: Snapshot) -> None:
        prev = self._last_mid.get(s.ticker)
        cv = 0.0
        mid = s.mid_price
        if mid is not None:
            if prev:
                pm, pt = prev
                dt = s.ts_unix - pt
                if dt > 0:
                    cv = round((mid - pm) / dt, 6)
            self._last_mid[s.ticker] = (mid, s.ts_unix)

        self._buf.append((
            s.ts, s.ts_unix, s.ticker, s.strike, s.secs_remaining,
            s.yes_bid, s.yes_ask, s.no_bid, s.no_ask, s.yes_last,
            s.combined_cost, json.dumps(s.yes_levels), json.dumps(s.no_levels),
            s.yes_total_size, s.no_total_size, s.yes_top3_size, s.no_top3_size,
            s.ob_imbalance, s.volume, s.open_interest, s.status, "rest",
            s.btc_price, s.btc_velocity, s.btc_momentum, s.fair_yes_pct,
            s.spread, mid, s.abs_gap, s.signed_gap, cv,
        ))

    def add_trades(self, rows: list[dict]) -> None:
        if not self._conn or not rows:
            return
        fresh = [r for r in rows if r.get("trade_id") not in self._seen_trades]
        if not fresh:
            return
        for r in fresh:
            self._seen_trades.add(r["trade_id"])
        if len(self._seen_trades) > 20000:
            self._seen_trades = set(list(self._seen_trades)[-8000:])
        self._conn.executemany(
            "INSERT OR IGNORE INTO trades (ts, ts_unix, ticker, strike, trade_id, side,"
            " yes_price, no_price, count, taker_side, secs_remaining)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(r["ts"], r["ts_unix"], r["ticker"], r.get("strike"), r["trade_id"],
              r.get("side"), r.get("yes_price"), r.get("no_price"), r.get("count"),
              r.get("taker_side"), r.get("secs_remaining")) for r in fresh],
        )
        self.trades_written += len(fresh)

    def upsert_window(self, ticker: str, **fields) -> None:
        if not self._conn:
            return
        self._conn.execute("INSERT OR IGNORE INTO windows (ticker) VALUES (?)", (ticker,))
        if fields:
            sets = ", ".join(f"{k}=COALESCE(?,{k})" for k in fields)
            self._conn.execute(
                f"UPDATE windows SET {sets} WHERE ticker=?",
                (*fields.values(), ticker),
            )

    def settle_window(self, ticker: str, outcome: Optional[str], source: str,
                      btc_final: Optional[float]) -> None:
        self.upsert_window(
            ticker, settled=1, outcome=outcome, outcome_source=source, btc_final=btc_final
        )

    def add_btc_price(self, m: dict) -> None:
        if not self._conn or m.get("price") is None:
            return
        self._conn.execute(
            "INSERT INTO btc_price_history (ts, ts_unix, price, source, velocity, momentum)"
            " VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), time.time(), m["price"],
             m.get("source"), m.get("velocity"), m.get("momentum")),
        )

    def save_position(self, p: Position) -> None:
        if not self._conn:
            return
        self._conn.execute(
            "INSERT INTO positions (strategy, ticker, side, mode, entry_price, contracts,"
            " cost, entry_time, exit_price, exit_time, exit_reason, pnl, strike,"
            " secs_at_entry, entry_reason, order_id, filled)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(strategy, ticker, mode, entry_time) DO UPDATE SET"
            " exit_price=excluded.exit_price, exit_time=excluded.exit_time,"
            " exit_reason=excluded.exit_reason, pnl=excluded.pnl, filled=excluded.filled",
            (p.strategy, p.ticker, p.side, p.mode, p.entry_price, p.contracts, p.cost,
             p.entry_time, p.exit_price, p.exit_time, p.exit_reason, p.pnl, p.strike,
             p.secs_at_entry, p.entry_reason, p.order_id, int(p.filled)),
        )
        self._conn.commit()

    # -- flush -------------------------------------------------------------

    def _flush_sync(self) -> None:
        if not self._conn or not self._buf:
            if self._conn:
                self._conn.commit()
            return
        buf, self._buf = self._buf, []
        try:
            self._conn.executemany(
                f"INSERT INTO orderbook_snapshots ({_OB_COLS})"
                f" VALUES ({','.join('?' * 31)})",
                buf,
            )
            self._conn.commit()
            self.snapshots_written += len(buf)
        except sqlite3.Error as e:
            log.error("snapshot flush failed: %s", e)
            self._conn.rollback()

    async def flush(self) -> None:
        async with self._lock:
            self._open()          # rotates at UTC midnight
            await asyncio.to_thread(self._flush_sync)

    # -- reads for the UI --------------------------------------------------

    def recent_positions(self, limit: int = 400) -> list[dict]:
        if not self._conn:
            return []
        rows = self._conn.execute(
            "SELECT * FROM positions ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        return {
            "db": self.path.name,
            "snapshots": self.snapshots_written,
            "trades": self.trades_written,
            "pending": len(self._buf),
        }
