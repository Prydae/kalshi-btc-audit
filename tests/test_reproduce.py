"""Checks that the reproduce script runs and that the label and settlement logic
behaves as documented. Frozen sample numbers guard against accidental changes to
the sample files or the method."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from btc15m.labels import fetch_kalshi_result, legacy_label, mismatch_summary, parse_result  # noqa: E402
from btc15m.models import Position  # noqa: E402
from scripts.reproduce import run  # noqa: E402


def test_reproduce_script_runs_and_writes_json(tmp_path):
    out = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reproduce.py"), "--json", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) >= {"windows", "trades", "labels", "lanes"}


def test_sample_frozen_numbers():
    r = run()
    assert r["windows"] == 280
    assert r["trades"] == 359
    assert r["labels"]["usable"] == 278
    assert r["labels"]["excluded"] == 2
    assert r["labels"]["mismatch"] == 16
    assert r["labels"]["legacy_rule_agreement"] == 278
    assert len(r["lanes"]) == 6
    assert r["lanes"]["REV01_FILTERED_CHEAP_FLIP"]["n"] == 18
    assert r["lanes"]["PR_NO_50_70_BOOK"]["n"] == 81
    assert sum(v["n"] for v in r["lanes"].values()) == 359


def test_legacy_rule_and_result_parsing():
    assert legacy_label(100.0, 99.0) == "yes"
    assert legacy_label(98.0, 99.0) == "no"
    assert legacy_label(None, 99.0) is None
    assert parse_result({"market": {"result": "NO"}}) == "no"
    assert parse_result({"market": {"result": ""}}) is None
    assert parse_result({}) is None


def test_mismatch_summary_on_synthetic_rows():
    rows = [
        dict(btc_final=101, strike=100, legacy_outcome="yes", kalshi_outcome="no"),   # 1 USD away, 0-5 band, wrong
        dict(btc_final=250, strike=100, legacy_outcome="yes", kalshi_outcome="yes"),  # 150 USD away, 100+ band, right
        dict(btc_final=None, strike=100, legacy_outcome="yes", kalshi_outcome="yes"), # excluded
    ]
    s = mismatch_summary(rows)
    assert s["usable"] == 2
    assert s["excluded"] == 1
    assert s["mismatch"] == 1
    assert s["bands"]["0-5"]["mismatch"] == 1
    assert s["bands"]["100-+"]["n"] == 1


def test_network_fetch_is_a_stub():
    with pytest.raises(NotImplementedError):
        fetch_kalshi_result("KXBTC15M-TEST")


def test_settlement_pnl_is_per_contract_times_contracts():
    p = Position(strategy="X", ticker="T", side="NO", entry_price=0.6,
                 contracts=2, entry_time="2026-06-23T00:00:00+00:00")
    assert p.close(1.0, "settlement") == pytest.approx(0.8)
    q = Position(strategy="X", ticker="T", side="NO", entry_price=0.6,
                 contracts=2, entry_time="2026-06-23T00:00:00+00:00")
    assert q.close(0.0, "settlement") == pytest.approx(-1.2)


def test_stubbed_modules_refuse_to_import():
    for name in ("engine", "live", "btcfeed", "client"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import btc15m.{name}"],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert proc.returncode != 0, name
