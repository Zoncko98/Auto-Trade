"""Synthetic tests for owner-configured Schwab risk without placing broker orders."""
from decimal import Decimal
from pathlib import Path
from datetime import datetime,timezone
from tempfile import TemporaryDirectory
import unittest
from live_extension import RISK_DEFAULTS,validate_risk,read_live_risk,set_live_risk
from live_order_safety import LiveBlocked,OrderLedger,buy_quantity
from dashboard_control import write_atomic
from live_worker import risk_preflight

class OwnerRiskTests(unittest.TestCase):
    def test_more_than_old_25_dollar_cap_is_allowed_within_verified_budget(self):
        qty,limit=buy_quantity(Decimal("10"),Decimal("80"),Decimal("20"),
            capital=Decimal("100"),max_position=Decimal("50"))
        self.assertGreater(qty*limit,Decimal("25"))
        self.assertLessEqual(qty*limit,Decimal("50"))
        self.assertLessEqual(qty*limit,Decimal("80"))

    def test_account_capital_exposure_limits_remain_active(self):
        qty,price=buy_quantity(Decimal("10"),Decimal("100"),Decimal("95"),
            capital=Decimal("100"),max_position=Decimal("100"))
        self.assertEqual(qty,0)
        self.assertGreater(price,Decimal("10"))

    def test_order_journal_uses_selected_capital_without_auto_order(self):
        with TemporaryDirectory() as folder:
            journal=OrderLedger.open(Path(folder)/"orders.json")
            with self.assertRaisesRegex(LiveBlocked,"strategy capital"):
                journal.record_before_network("F","BUY",20,Decimal("10"),
                    123,capital_limit=Decimal("100"))
            entry=journal.record_before_network("F","BUY",20,Decimal("10"),
                    123,capital_limit=Decimal("500"))
            self.assertEqual(entry["state"],"SUBMITTING")
            self.assertEqual(journal.data["orders"][0]["quantity"],20)
            # Entries are journaled before network; no broker is invoked.

    def test_daily_loss_threshold_is_operator_value_not_old_five_dollar_clamp(self):
        with TemporaryDirectory() as folder:
            journal=OrderLedger.open(Path(folder)/"orders.json")
            journal.data["day"]=datetime.now(timezone.utc).date().isoformat()
            journal.data["day_start_equity"]="100"
            settings={**RISK_DEFAULTS,"max_daily_loss":10.0}
            held,hit=risk_preflight(journal,{},Decimal("92"),Decimal("92"),
                    Decimal("0"),"F",settings)
            self.assertEqual(held,0)
            self.assertFalse(hit)
            with self.assertRaisesRegex(LiveBlocked,"drawdown"):
                risk_preflight(journal,{},Decimal("89"),Decimal("89"),
                    Decimal("0"),"F",settings)

    def test_risk_revision_conflict_still_protects_concurrent_changes(self):
        with TemporaryDirectory() as folder:
            raised={**RISK_DEFAULTS,"max_order_usd":50.0,
                "max_position_pct":50.0,"max_open_positions":6,
                "max_buys_per_day":6,"max_orders_per_day":15,
                "max_daily_loss":10.0}
            self.assertEqual(validate_risk(raised)["max_order_usd"],50.0)
            saved=set_live_risk(folder,0,raised,write_atomic)
            self.assertEqual(saved["revision"],1)
            with self.assertRaises(RuntimeError):
                set_live_risk(folder,0,RISK_DEFAULTS,write_atomic)
            self.assertEqual(read_live_risk(folder)["settings"],raised)

if __name__=="__main__":unittest.main()
