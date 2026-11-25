# Sample data

Three archived KXBTC15M days, 23, 24 and 25 June 2026, exported from the private research archive. Every window in these files has a Kalshi-verified result.

| File | Rows | Columns |
|---|---:|---|
| `windows.csv` | 280 | `day`, `ticker`, `strike` (USD), `close_time` (UTC), `btc_final` (USD, reference spot at close), `legacy_outcome` (spot-inferred yes/no), `kalshi_outcome` (Kalshi result yes/no) |
| `paper_trades.csv` | 359 | `strategy`, `ticker`, `side`, `entry_cents` (entry price, cents), `contracts`, `secs_at_entry`, `exit_reason`, `legacy_outcome`, `kalshi_outcome` |

No balances, account identifiers, order IDs, or credentials are included. Prices are in cents. Market tickers are public identifiers.

Each trade is one paper entry (full fill at the signal price), so `paper_trades.csv` is a per-signal record, not a fill record.
