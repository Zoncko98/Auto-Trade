"""V2 simulated economics must reconcile to the real SimulatedBroker ledger."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json,sqlite3

from trader_v2.models import AssetClass,MarketSnapshot,OrderIntent,OrderSide
from trader_v2.simulation import SimulatedBroker
from trader_v2.sim_economics import read_economics

class SimEconomicsTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.now=datetime(2026,11,21,15,0,tzinfo=timezone.utc)
        self.clock=self.now
        self.broker=SimulatedBroker(self.root/"sim.sqlite3",
            fee_bps=Decimal("5"),slippage_bps=Decimal("5"),
            clock=lambda:self.clock)
        self.broker.seed("v2-paper-btcusd",AssetClass.CRYPTO,
                         Decimal("1000"),fractional=True)
        self.broker.seed("v2-paper-ethusd",AssetClass.CRYPTO,
                         Decimal("1000"),fractional=True)

    def quote(self,symbol,bid,ask):
        return MarketSnapshot(symbol,AssetClass.CRYPTO,"coinbase_public_paper",
            self.clock-timedelta(seconds=1),self.clock,
            Decimal(str(bid)),Decimal(str(ask)),
            Decimal(str(bid)),True)

    def trade(self,symbol,side,amount,bid,ask,limit,key):
        self.broker.quote(self.quote(symbol,bid,ask))
        account="v2-paper-"+symbol.lower()
        intent=OrderIntent(key,account,"crypto_sma",symbol,
            AssetClass.CRYPTO,OrderSide(side),Decimal(str(amount)),
            Decimal(str(limit)),self.clock)
        return self.broker.submit(intent)

    def test_empty_private_ledger_is_reconciled_as_zero_activity(self):
        cards=read_economics(self.root,now=self.now)
        for card in cards.values():
            self.assertEqual(card["state"],"SIMULATED_CASH_AND_POSITIONS_RECONCILED")
            self.assertEqual(card["simulated_fills"],0)
            self.assertEqual(card["completed_round_trips"],0)
            self.assertEqual(card["total_assumed_fees_usd"],"0.00")
            self.assertFalse(card["live_orders_authorized"])
            self.assertTrue(card["cash_reconciled"])

    def test_real_simulation_buy_and_sell_exact_net_after_costs(self):
        self.trade("BTCUSD","BUY","0.2","100","101","102","btc1")
        self.clock+=timedelta(minutes=5)
        self.trade("BTCUSD","SELL","0.2","99","100","98","btc2")
        cards=read_economics(self.root,now=self.clock)
        card=cards["BTCUSD"]
        self.assertEqual(card["state"],"SIMULATED_CASH_AND_POSITIONS_RECONCILED")
        self.assertEqual(card["simulated_fills"],2)
        self.assertEqual(card["simulated_buys"],1)
        self.assertEqual(card["simulated_sells"],1)
        self.assertEqual(card["completed_round_trips"],1)
        self.assertEqual(card["winning_round_trips"],0)
        self.assertEqual(card["total_assumed_fees_usd"],"0.02")
        self.assertEqual(card["remaining_quantity"],"0.00000000")
        cash=self.broker.account("v2-paper-btcusd").cash
        expected=str((cash-Decimal("1000")).quantize(Decimal("0.01")))
        self.assertEqual(card["realized_net_pnl_usd"],expected)
        self.assertEqual(card["slippage_attribution"],"NOT_SEPARATELY_VERIFIED")
        self.assertTrue(card["cash_reconciled"])
        self.assertEqual(cards["ETHUSD"]["simulated_fills"],0)

    def test_open_buy_is_not_miscounted_as_realized_profit(self):
        self.trade("ETHUSD","BUY","0.2","100","101","102","eth1")
        c=read_economics(self.root,now=self.now)["ETHUSD"]
        self.assertEqual(c["state"],"SIMULATED_CASH_AND_POSITIONS_RECONCILED")
        self.assertEqual(c["completed_round_trips"],0)
        self.assertEqual(c["simulated_fills"],1)
        self.assertEqual(c["realized_net_pnl_usd"],"0.00")
        self.assertEqual(c["remaining_quantity"],"0.20000000")

    def test_winning_complete_cycle_is_detected(self):
        self.trade("BTCUSD","BUY","0.2","100","101","102","btc3")
        self.clock+=timedelta(minutes=7)
        self.trade("BTCUSD","SELL","0.2","107","108","106","btc4")
        c=read_economics(self.root,now=self.clock)["BTCUSD"]
        self.assertEqual(c["completed_round_trips"],1)
        self.assertEqual(c["winning_round_trips"],1)
        self.assertGreater(Decimal(c["realized_net_pnl_usd"]),0)

    def test_tampered_cash_fails_closed_not_false_economic_performance(self):
        self.trade("BTCUSD","BUY","0.2","100","101","102","btc5")
        with sqlite3.connect(self.root/"sim.sqlite3") as db:
            db.execute("UPDATE sim_accounts SET cash='9999' WHERE account_id='v2-paper-btcusd'")
        c=read_economics(self.root,now=self.now)["BTCUSD"]
        self.assertEqual(c["state"],"SIMULATOR_RECONCILIATION_REQUIRED")
        self.assertIsNone(c["realized_net_pnl_usd"])
        self.assertIsNone(c["completed_round_trips"])
        self.assertFalse(c["cash_reconciled"])

    def test_invalid_order_source_or_future_timestamp_fails_closed(self):
        self.trade("BTCUSD","BUY","0.2","100","101","102","btc6")
        with sqlite3.connect(self.root/"sim.sqlite3") as db:
            db.execute("UPDATE sim_orders SET created_at='2100-01-01T00:00:00+00:00'")
        c=read_economics(self.root,now=self.now)["BTCUSD"]
        self.assertEqual(c["state"],"SIMULATOR_RECONCILIATION_REQUIRED")
        self.assertIsNone(c["simulated_fills"])

    def test_extra_cross_account_inventory_is_not_silently_ignored(self):
        with sqlite3.connect(self.root/"sim.sqlite3") as db:
            db.execute("""INSERT INTO sim_positions VALUES(?,?,?,?,?)""",
                       ("v2-paper-btcusd","ETHUSD","1","100","100"))
        c=read_economics(self.root,now=self.now)["BTCUSD"]
        self.assertEqual(c["state"],"SIMULATOR_RECONCILIATION_REQUIRED")
        self.assertIsNone(c["realized_net_pnl_usd"])

    def test_invalid_public_or_symlinked_database_not_followed(self):
        db=self.root/"sim.sqlite3"
        db.chmod(0o644)
        c=read_economics(self.root,now=self.now)["BTCUSD"]
        self.assertEqual(c["state"],"SIMULATOR_LEDGER_UNAVAILABLE")
        self.assertIsNone(c["realized_net_pnl_usd"])
        db.chmod(0o600)
        other=self.root/"other.db"
        db.rename(other)
        db.symlink_to(other)
        self.assertEqual(read_economics(self.root,now=self.now)["ETHUSD"]["state"],
                         "SIMULATOR_LEDGER_UNAVAILABLE")

    def test_reader_never_creates_file_or_broker_credentials(self):
        with TemporaryDirectory() as tmp:
            cards=read_economics(tmp,now=self.now)
            self.assertTrue(all(x["state"]=="SIMULATOR_LEDGER_UNAVAILABLE" for x in cards.values()))
            self.assertEqual(list(Path(tmp).iterdir()),[])

if __name__=="__main__":main()
