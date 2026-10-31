import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ai_review import ReviewDecision
from paper_engine import PaperEngine
from risk_controls import RiskLimits


class ApproveFixture:
    def review(self, candidate):
        return ReviewDecision(True, "Approved by test fixture", "fixture")


class RejectFixture:
    def review(self, candidate):
        return ReviewDecision(False, "Insufficient evidence", "fixture", ("limited_data",))
from bot import configuration


class PaperEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "account.json"
        self.limits = RiskLimits(100, 25, 5, 3)
        self.engine = PaperEngine(self.path, self.limits, allowed_symbols={"SPY"},
                                  reviewer=ApproveFixture())
        self.now = datetime.now(timezone.utc)
        self.start = self.now - timedelta(seconds=150)

    def sample(self, number, value):
        timestamp = (self.start + timedelta(seconds=number * 10)).isoformat()
        return self.engine.process("SPY", value, timestamp, now=self.now)

    def test_buys_on_crossover_and_survives_restart(self):
        observations = [10, 9, 8, 7, 8, 11]
        for i, value in enumerate(observations):
            result = self.sample(i, value)
        self.assertEqual(result, "PAPER_BUY")
        self.assertEqual(len(self.engine.state["trades"]), 1)
        self.assertLessEqual(100 - self.engine.state["cash"], 25)
        restored = PaperEngine(self.path, self.limits, allowed_symbols={"SPY"},
                               reviewer=ApproveFixture())
        self.assertEqual(len(restored.state["trades"]), 1)
        self.assertEqual(restored.process("SPY", 11,
            (self.start + timedelta(seconds=50)).isoformat(), now=self.now),
            "SKIP: duplicate or out-of-order quote")
        self.assertEqual(len(restored.state["trades"]), 1)

    def test_no_orders_on_invalid_or_stale_quotes(self):
        self.assertIn("invalid price", self.sample(0, float("nan")))
        self.assertIn("not permitted", self.engine.process(
            "UNKNOWN", 10, self.start.isoformat(), now=self.now))
        self.assertIn("stale", self.engine.process("SPY", 10,
            (self.now - timedelta(hours=2)).isoformat(), now=self.now))
        self.assertEqual(len(self.engine.state["trades"]), 0)

    def test_cash_and_position_limits(self):
        engine = PaperEngine(self.path, RiskLimits(100, 25, 5, 1),
                             allowed_symbols={"SPY"}, allow_fractional=False,
                             reviewer=ApproveFixture())
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = engine.process("SPY", value,
                (self.start + timedelta(seconds=i * 10)).isoformat(), now=self.now)
        self.assertEqual(result, "PAPER_BUY")
        self.assertEqual(engine.state["positions"]["SPY"]["quantity"], 2)
        self.assertGreaterEqual(engine.state["cash"], 0)

    def test_daily_loss_halts_new_entries(self):
        self.engine.state["day"] = self.start.date().isoformat()
        self.engine.state["day_start_equity"] = 110
        result = self.sample(0, 10)
        self.assertEqual(result, "HOLD")
        self.assertTrue(self.engine.state["halted"])

    def test_atomic_state_is_written(self):
        self.sample(0, 10)
        self.assertTrue(self.path.exists())
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_rejects_candidate_when_ai_vetoes(self):
        self.engine.reviewer = RejectFixture()
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = self.sample(i, value)
        self.assertEqual(result, "AI_REJECTED")
        self.assertEqual(self.engine.state["trades"], [])
        self.assertEqual(self.engine.state["reviews"][-1]["approved"], False)

    def test_no_reviewer_fails_closed(self):
        self.engine.reviewer = None
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = self.sample(i, value)
        self.assertEqual(result, "AI_REJECTED")
        self.assertEqual(len(self.engine.state["positions"]), 0)

    def test_reviewer_exception_fails_closed(self):
        class Broken:
            def review(self, candidate):
                raise RuntimeError("simulated outage")
        self.engine.reviewer = Broken()
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = self.sample(i, value)
        self.assertEqual(result, "AI_REJECTED")
        self.assertEqual(len(self.engine.state["positions"]), 0)

    def test_daily_growth_target_prevents_new_entries(self):
        self.engine.state["day"] = self.start.date().isoformat()
        self.engine.state["day_start_equity"] = 99.0
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = self.sample(i, value)
        self.assertEqual(result, "HOLD")
        self.assertTrue(self.engine.state["daily_target_reached"])
        self.assertEqual(self.engine.state["trades"], [])

    def test_daily_growth_target_zero_disables_goal_gate(self):
        self.engine.state["day"] = self.start.date().isoformat()
        self.engine.state["day_start_equity"] = 99.0
        from dashboard_control import DEFAULT_SETTINGS
        settings=DEFAULT_SETTINGS.copy()
        settings["daily_growth_target_pct"] = 0
        self.engine.set_trade_settings(settings)
        for i, value in enumerate([10, 9, 8, 7, 8, 11]):
            result = self.sample(i, value)
        self.assertEqual(result, "PAPER_BUY")


    def test_fail_closed_live_trading_flag(self):
        with patch.dict(os.environ, {"LIVE_TRADING": "true"}):
            with self.assertRaisesRegex(ValueError, "prohibited"):
                configuration()

    def test_disallow_margin_and_options(self):
        with patch.dict(os.environ, {"LIVE_TRADING": "false", "ALLOW_MARGIN": "true"}):
            with self.assertRaisesRegex(ValueError, "prohibited"):
                configuration()


if __name__ == "__main__":
    unittest.main(verbosity=2)
