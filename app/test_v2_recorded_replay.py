"""Recorded V2 paper replay uses ONLY real historical tape and simulated fills."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import os
import sqlite3
import unittest

from trader_v2.recorded_replay import (
    ReplayUnavailable, replay_status, run_recorded_replay, SUPPORTED
)


class RecordedPaperReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.first = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.closes = [10, 10, 10, 10, 10, 10, 10, 10, 10, 11, 12, 13,
                       12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 12, 11]

    def tape(self, symbols=None):
        symbols = symbols or {"BTCUSD": self.closes}
        path = self.root/"prices.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("timestamp","symbol","price"))
            for sym, closes in symbols.items():
                for i,close in enumerate(closes):
                    writer.writerow((self.first.replace(tzinfo=timezone.utc)
                        .__add__(timedelta(minutes=i)).isoformat(),sym,str(close)))
        path.chmod(0o600)
        return path

    def test_run_persists_simulated_journal_and_immutable_report(self):
        self.tape()
        before = replay_status(self.root)
        self.assertEqual(before["state"], "AVAILABLE")
        self.assertEqual(before["symbols"][0]["symbol"], "BTCUSD")
        self.assertIsNone(before["last_report"])
        result = run_recorded_replay(self.root, "BTCUSD")
        self.assertEqual(result["mode"], "HISTORICAL_SYNTHETIC_REPLAY_ONLY")
        self.assertFalse(result["broker_credentials_used"])
        self.assertFalse(result["market_executable"])
        self.assertFalse(result["live_orders_authorized"])
        self.assertFalse(result["ai_invoked"])
        self.assertEqual(result["live_orders_submitted"], 0)
        self.assertEqual(result["asset_class"], "CRYPTO")
        self.assertEqual(result["candles"], len(self.closes))
        self.assertGreater(result["signals"], 0)
        self.assertGreater(result["fills"], 0)
        self.assertGreater(result["journal"]["intents"],0)
        self.assertEqual(result["journal"]["unresolved"], 0)
        directory = self.root/"v2"/"recorded_replays"/result["run_id"]
        self.assertTrue((directory/"intents.sqlite3").exists())
        self.assertTrue((directory/"sim.sqlite3").exists())
        self.assertEqual((directory/"result.json").stat().st_mode & 0o077,0)
        self.assertEqual(replay_status(self.root)["last_report"]["run_id"],result["run_id"])

    def test_repeating_identical_tape_is_idempotent(self):
        self.tape()
        first = run_recorded_replay(self.root, "BTCUSD")
        path = self.root/"v2"/"recorded_replays"/first["run_id"]/"intents.sqlite3"
        with sqlite3.connect(path) as db:
            events1=db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        second=run_recorded_replay(self.root, "BTCUSD")
        with sqlite3.connect(path) as db:
            events2=db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(first,second)
        self.assertEqual(events1,events2)

    def test_replay_input_changes_get_distinct_workspace(self):
        self.tape()
        first=run_recorded_replay(self.root,"BTCUSD")
        self.tape({"BTCUSD":self.closes+[13,14]})
        second=run_recorded_replay(self.root,"BTCUSD")
        self.assertNotEqual(first["run_id"],second["run_id"])
        self.assertTrue((self.root/"v2"/"recorded_replays"/first["run_id"]/"result.json").exists())

    def test_recordings_are_separate_from_schwab_and_other_brokers(self):
        self.tape()
        r=run_recorded_replay(self.root,"BTCUSD")
        self.assertEqual(r["source"],"RECORDED_V1_PAPER_CLOSED_BARS")
        self.assertFalse((self.root/"live").exists())
        self.assertFalse((self.root/"robinhood").exists())
        self.assertFalse((self.root/"webull").exists())
        self.assertEqual(len(SUPPORTED)>0,True)

    def test_unrecognized_symbol_does_not_guess_asset_class(self):
        self.tape({"MYSTERY":self.closes})
        self.assertEqual(replay_status(self.root)["state"],"INSUFFICIENT_CANDLES")
        with self.assertRaisesRegex(ReplayUnavailable,"UNSUPPORTED_RECORDED_SYMBOL"):
            run_recorded_replay(self.root,"MYSTERY")

    def test_missing_or_malformed_tape_fails_without_state_change(self):
        self.assertEqual(replay_status(self.root)["state"],"RECORDED_SOURCE_UNAVAILABLE")
        with self.assertRaises(ReplayUnavailable):
            run_recorded_replay(self.root,"BTCUSD")
        self.assertFalse((self.root/"v2").exists())
        self.tape()
        (self.root/"prices.csv").write_text("not,csv\n1,2\n")
        with self.assertRaisesRegex(ReplayUnavailable,"RECORDED_SOURCE_SCHEMA_INVALID"):
            run_recorded_replay(self.root,"BTCUSD")

    def test_symlink_tape_refused_and_not_dereferenced(self):
        p=self.tape()
        real=self.root/"backup.csv"
        p.rename(real)
        p.symlink_to(real)
        with self.assertRaisesRegex(ReplayUnavailable,"RECORDED_SOURCE_UNSAFE"):
            run_recorded_replay(self.root,"BTCUSD")

    def test_duplicate_bar_refused_without_journal(self):
        self.tape()
        path=self.root/"prices.csv"
        rows=path.read_text().splitlines()
        path.write_text("\n".join(rows+[rows[5]])+"\n")
        with self.assertRaisesRegex(ReplayUnavailable,"RECORDED_CANDLE_DUPLICATE"):
            run_recorded_replay(self.root,"BTCUSD")
        self.assertFalse((self.root/"v2").exists())

    def test_unsafe_directory_refuses_persistent_ledger(self):
        self.tape()
        bad=self.root/"v2"
        bad.mkdir(mode=0o700)
        bad.chmod(0o777)
        with self.assertRaisesRegex(ReplayUnavailable,"REPLAY_DIRECTORY_UNSAFE"):
            run_recorded_replay(self.root,"BTCUSD")

    def test_read_only_status_does_not_create_v2(self):
        self.tape()
        available=replay_status(self.root)
        self.assertEqual(available["state"],"AVAILABLE")
        self.assertFalse((self.root/"v2").exists())


if __name__=="__main__":
    unittest.main()
