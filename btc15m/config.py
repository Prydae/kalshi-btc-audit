"""Settings for the research modules.

Public-copy rewrite: the private project read these values from a local
environment file and kept credential fields here. This copy has no credential
fields and reads nothing from disk. The values below are the defaults the
research code uses.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # market
    series: str = "KXBTC15M"
    depth: int = 10
    market_refresh_secs: float = 5.0
    # where a live collector would write daily SQLite files (unused by the sample)
    db_dir: Path = ROOT / "data" / "live"
    # paper engine
    paper_notional_usd: float = 10.0
    #: Fill every paper entry at the quoted price, in full, immediately.
    paper_assume_full_fill: bool = True


settings = Settings()
