"""V2 broker-fill inventory is exactly cumulative, never assumed from ACKs."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from trader_v2.models import AssetClass,OrderSide,OrderIntent,RiskDecision,OrderState
from trader_v2.store import EventStore
from trader_v2.live_position_projection import reconstruct,PortfolioEvidenceError

class PositionProjectionTests(TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name)
  self.db=EventStore(self.base/"v2/events.sqlite3")
  self.now=datetime.now(timezone.utc)
 def intent(self,key,side,qty,asset=AssetClass.CRYPTO):
  order=OrderIntent(key,"acct","v2crypto","BTC-USD",asset,side,D(qty),D("10"),self.now)
  self.db.prepare(order,RiskDecision("PASS","ACCEPTED",D(qty),D("10"),D("15")))
  self.db.transition(key,OrderState.SUBMITTING)
  self.db.transition(key,OrderState.BROKER_ACCEPTED,
    evidence={"broker_order_id":"signed-order-"+key})
 def fill(self,key,state,qty,price="10",fee="0"):
  self.db.transition(key,state,evidence={
    "filled_quantity":qty,"average_price":price,"fees":fee})
 def view(self):return reconstruct(self.base,"acct")
 def test_absent_live_journal_cannot_fabricate_holdings(self):
  with TemporaryDirectory() as empty:
   with self.assertRaises(PortfolioEvidenceError):
    reconstruct(empty,"unknown")
 def test_ack_not_inventory_and_unknown_blocks(self):
  self.intent("buy_1",OrderSide.BUY,"1")
  row=self.view()
  self.assertEqual(row["verified_v2_inventory"],{})
  self.assertEqual(row["unresolved_intents"],1)
  self.db.transition("buy_1",OrderState.UNKNOWN_REQUIRES_RECONCILIATION)
  row=self.view()
  self.assertEqual(row["state"],"RECONCILIATION_REQUIRED")
  self.assertEqual(row["reconciled_lots"],0)
 def test_multiple_cumulative_partial_fill_updates_not_double_counted(self):
  self.intent("buy_1",OrderSide.BUY,"2")
  self.fill("buy_1",OrderState.PARTIALLY_FILLED,"0.5","10","0.01")
  self.fill("buy_1",OrderState.PARTIALLY_FILLED,"1.2","10","0.02")
  self.fill("buy_1",OrderState.FILLED,"2","10","0.05")
  row=self.view()
  self.assertEqual(row["verified_v2_inventory"]["BTC-USD"]["quantity"],"2")
  self.assertEqual(D(row["verified_v2_inventory"]["BTC-USD"]["cost_basis"]),D("10.025"))
  self.assertEqual(row["unresolved_intents"],0)
  self.assertEqual(row["buy_fills"],1)
 def test_signed_sell_allocates_fee_adjusted_basis_and_pnl(self):
  self.intent("buy_1",OrderSide.BUY,"2")
  self.fill("buy_1",OrderState.FILLED,"2","10","0.1")
  self.intent("sell_1",OrderSide.SELL,"1")
  self.fill("sell_1",OrderState.FILLED,"1","12","0.2")
  row=self.view()
  self.assertEqual(row["verified_v2_inventory"]["BTC-USD"]["quantity"],"1")
  self.assertEqual(D(row["realized_net_usd"]),D("1.75"))
  self.assertEqual(row["sell_fills"],1)
  self.assertFalse(row["live_order_authority"])
 def test_signed_fill_opened_at_and_daily_net_provenance(self):
  self.intent("buy_1",OrderSide.BUY,"2")
  self.fill("buy_1",OrderState.FILLED,"2","10","0.1")
  entry=self.view()["verified_v2_inventory"]["BTC-USD"]
  stamp=datetime.fromisoformat(entry["opened_at"])
  self.assertIsNotNone(stamp.utcoffset())
  self.intent("sell_1",OrderSide.SELL,"1")
  self.fill("sell_1",OrderState.FILLED,"1","12","0.2")
  result=self.view()
  self.assertEqual(result["realized_net_by_reconciled_utc_day"][self.now.date().isoformat()],"1.75")
  self.assertEqual(result["verified_v2_inventory"]["BTC-USD"]["opened_at"],entry["opened_at"])
  self.assertEqual(result["unresolved_intents"],0)

 def test_closed_position_does_not_reuse_prior_lot_open_time(self):
  self.intent("buy_first",OrderSide.BUY,"1")
  self.fill("buy_first",OrderState.FILLED,"1","10","0.01")
  first=self.view()["verified_v2_inventory"]["BTC-USD"]["opened_at"]
  self.intent("sell_first",OrderSide.SELL,"1")
  self.fill("sell_first",OrderState.FILLED,"1","10","0.01")
  self.assertEqual(self.view()["verified_v2_inventory"],{})
  self.intent("buy_second",OrderSide.BUY,"1")
  self.fill("buy_second",OrderState.FILLED,"1","10","0.01")
  second=self.view()["verified_v2_inventory"]["BTC-USD"]["opened_at"]
  self.assertTrue(second>=first)
  self.assertEqual(self.view()["unresolved_intents"],0)

 def test_cancelled_partial_retains_actual_filled_quantity(self):
  self.intent("buy_1",OrderSide.BUY,"2")
  self.fill("buy_1",OrderState.PARTIALLY_FILLED,"0.5","10","0")
  self.fill("buy_1",OrderState.CANCELED,"0.5","10","0")
  row=self.view()
  self.assertEqual(row["state"],"RECONCILED")
  self.assertEqual(row["verified_v2_inventory"]["BTC-USD"]["quantity"],"0.5")
 def test_duplicate_cumulative_or_broker_overfill_blocks(self):
  self.intent("buy_1",OrderSide.BUY,"1")
  self.fill("buy_1",OrderState.PARTIALLY_FILLED,"0.6","10","0")
  self.fill("buy_1",OrderState.PARTIALLY_FILLED,"0.5","10","0")
  with self.assertRaises(PortfolioEvidenceError):
   self.view()
 def test_unverified_broker_fill_qty_never_becomes_position(self):
  self.intent("buy_1",OrderSide.BUY,"1")
  self.fill("buy_1",OrderState.FILLED,"0.9","10","0")
  with self.assertRaises(PortfolioEvidenceError):
   self.view()
 def test_sell_over_verified_bot_holdings_blocks(self):
  self.intent("sell_1",OrderSide.SELL,"1")
  self.fill("sell_1",OrderState.FILLED,"1","12","0")
  with self.assertRaises(PortfolioEvidenceError):
   self.view()
 def test_fingerprint_tamper_blocks_provenance(self):
  self.intent("buy_1",OrderSide.BUY,"1")
  self.fill("buy_1",OrderState.FILLED,"1","10","0")
  with self.db._write() as db:
   db.execute("UPDATE intents SET fingerprint='bad' WHERE key='buy_1'")
  with self.assertRaises(PortfolioEvidenceError):
   self.view()

if __name__=="__main__":main()
