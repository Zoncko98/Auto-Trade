"""Read-only, signed V1 bot lot and exit policy adoption boundaries."""
import json,sqlite3
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from trader_v2.v1_managed_lots import (
    managed_v1_lot, legacy_exit_policy, V1LotUnavailable,
)
from trader_v2.v1_order_inheritance import InheritedOrderLimits
from trader_v2.models import Account,AuthState,Capability,AssetClass

NOW=datetime(2026,11,23,16,0,tzinfo=timezone.utc)

class ManagedLotAdoptionTests(TestCase):
    def setUp(self):
        self.t=TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.state=Path(self.t.name)
        self.proof=patch("trader_v2.v1_managed_lots.read_inherited",
            return_value=InheritedOrderLimits("robinhood_crypto","rh1",0,0,
                       frozenset(),False,True,True))
        self.read=self.proof.start()
        self.addCleanup(self.proof.stop)
    def account(self,broker,qty=D("1")):
        sym="BTC-USD" if broker=="robinhood_crypto" else "AAPL"
        cap=Capability(frozenset({AssetClass.CRYPTO if broker=="robinhood_crypto"
                       else AssetClass.STOCK}))
        return Account("rh1" if broker=="robinhood_crypto" else "wb1",
                       broker,cap,D("50"),D("100"),{sym:qty},
                       AuthState.CONNECTED,True)
    def save(self,path,data):
        path=self.state/path
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        path.parent.chmod(0o700)
        path.write_text(json.dumps(data))
        path.chmod(0o600)
    def buy(self):
        when=(NOW-timedelta(hours=2)).isoformat()
        self.save("robinhood/order_intents.json",{"version":1,"orders":[{
            "account":"rh1","client_order_id":"id1",
            "symbol":"BTC-USD","side":"buy","status":"filled",
            "quantity":"1","filled_quantity":"1",
            "average_fill_price":"10","fee_charged":"0.1",
            "created_at":when,"filled_at":when
        }]})
    def test_robinhood_exact_signed_quantity_and_fee_adjusted_cost(self):
        self.buy()
        lot=managed_v1_lot(self.state,"robinhood_crypto","rh1","BTC-USD",
                           self.account("robinhood_crypto"),now=NOW)
        self.assertEqual(lot.quantity,D("1"))
        self.assertEqual(lot.cost_basis,D("10.1"))
        self.assertTrue(lot.cost_basis_broker_verified)
        self.assertTrue(lot.original_fills_reconciled)
        self.assertIsNone(lot.high_water_bid)
    def test_signed_account_identity_cannot_be_crossed_to_other_broker_login(self):
        self.buy()
        another=Account("rh-different","robinhood_crypto",
                 self.account("robinhood_crypto").capability,
                 D("50"),D("100"),{"BTC-USD":D("1")},
                 AuthState.CONNECTED,True)
        with self.assertRaises(V1LotUnavailable) as ctx:
            managed_v1_lot(self.state,"robinhood_crypto","rh1","BTC-USD",
                          another,now=NOW)
        self.assertEqual(ctx.exception.code,"V1_MANAGED_SIGNED_ACCOUNT_UNVERIFIED")

    def test_signed_quantity_mismatch_cannot_sell_external_inventory(self):
        self.buy()
        with self.assertRaises(V1LotUnavailable) as ctx:
            managed_v1_lot(self.state,"robinhood_crypto","rh1","BTC-USD",
                 self.account("robinhood_crypto",D("2")),now=NOW)
        self.assertEqual(ctx.exception.code,"V1_BOT_LOT_OR_SIGNED_AVAILABILITY_MISMATCH")
    def test_unverified_signed_history_blocks_before_reading_lot(self):
        self.read.side_effect=ValueError("invalid history")
        with self.assertRaises(V1LotUnavailable) as ctx:
            managed_v1_lot(self.state,"robinhood_crypto","rh1","BTC-USD",
                 self.account("robinhood_crypto"),now=NOW)
        self.assertEqual(ctx.exception.code,"V1_SIGNED_HISTORY_AND_ACCOUNT_REQUIRED")
    def test_webull_verified_fill_cost_uses_actual_broker_fees(self):
        folder=self.state/"webull"
        folder.mkdir(mode=0o700)
        path=folder/"orders.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE orders(account TEXT,symbol TEXT,asset TEXT,
                   side TEXT,status TEXT,filled_qty TEXT,filled_price TEXT,
                   fee TEXT,fill_at TEXT,created_at TEXT,client_id TEXT)""")
            at=(NOW-timedelta(hours=3)).isoformat()
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              ("wb1","AAPL","EQUITY","BUY","FILLED","1","10","0.1",at,at,"a"))
        path.chmod(0o600)
        self.read.return_value=InheritedOrderLimits("webull","wb1",0,0,
                               frozenset(),False,True,True)
        lot=managed_v1_lot(self.state,"webull","wb1","AAPL",
                           self.account("webull"),now=NOW)
        self.assertEqual(lot.cost_basis,D("10.1"))
        self.assertEqual(lot.quantity,D("1"))
        self.assertIsNone(lot.high_water_bid)
    def test_webull_fee_missing_fails_closed(self):
        folder=self.state/"webull"
        folder.mkdir(mode=0o700)
        path=folder/"orders.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE orders(account TEXT,symbol TEXT,asset TEXT,
                   side TEXT,status TEXT,filled_qty TEXT,filled_price TEXT,
                   fee TEXT,fill_at TEXT,created_at TEXT,client_id TEXT)""")
            at=(NOW-timedelta(hours=3)).isoformat()
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              ("wb1","AAPL","EQUITY","BUY","FILLED","1","10",None,at,at,"a"))
        path.chmod(0o600)
        self.read.return_value=InheritedOrderLimits("webull","wb1",0,0,
                               frozenset(),False,True,True)
        with self.assertRaises(V1LotUnavailable):
            managed_v1_lot(self.state,"webull","wb1","AAPL",
                           self.account("webull"),now=NOW)
    def test_schwab_manually_adopted_lots_require_broker_confirmed_cost(self):
        self.read.return_value=InheritedOrderLimits("schwab","hash",0,0,
                                frozenset(),False,True,True,10)
        with self.assertRaises(V1LotUnavailable) as ctx:
            managed_v1_lot(self.state,"schwab","hash","AAPL",
                 self.account("webull"),now=NOW)
        self.assertEqual(ctx.exception.code,"V1_MANAGED_SIGNED_ACCOUNT_UNVERIFIED")
    def test_webull_original_exit_policy_requires_no_live_configuration_mutation(self):
        p=legacy_exit_policy(self.state,"webull","wb1")
        self.assertEqual(p.stop_loss_pct,D("2"))
        self.assertEqual(p.take_profit_pct,D("3"))
        self.assertFalse((self.state/"webull").exists())
    def test_unknown_robinhood_saved_policy_not_guessed(self):
        with self.assertRaises(V1LotUnavailable):
            legacy_exit_policy(self.state,"robinhood_crypto","rh1")
