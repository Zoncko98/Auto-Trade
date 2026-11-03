"""Regression: externally executed Robinhood sells must not leave phantom bot exposure."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from robinhood_order_journal import OrderJournal
from robinhood_order_pass import review_order,OrderPassBlocked

NOW=datetime(2026,11,3,14,38,tzinfo=timezone.utc)
ACCOUNT="acct"
BUY1="2026-11-03T11:09:46Z"
BUY2="2026-11-03T13:12:20Z"
SOLD1="2026-11-03T13:35:37Z"
SOLD2="2026-11-03T13:36:20Z"

def funded(root,symbol,qty,price,stamp,client_id):
    j=OrderJournal(root)
    j.record_intent(ACCOUNT,client_id,symbol,qty,price)
    j.reconcile(ACCOUNT,[{"client_order_id":client_id,"state":"filled",
        "filled_asset_quantity":str(qty),"average_price":str(price),
        "fee_charged":"0.01","updated_at":stamp}])

def manual_sell(sym,qty,when,broker_id="external-fill"):
    return {"id":broker_id,"symbol":sym,"side":"sell","state":"filled",
            "client_order_id":"manual-"+broker_id,"filled_asset_quantity":str(qty),
            "created_at":when,"updated_at":when}

class Fake:
    def list_accounts(self):
        return [{"account_number":ACCOUNT,"status":"active",
            "is_api_tradable":True,"buying_power_currency":"USD","buying_power":"53.61"}]
    def orders(self,account):
        return []
    def quote(self,symbol):
        pairs={"PEPE-USD":("0.00000485","0.00000487"),
               "ZEC-USD":("1189.37","1189.67"),
               "HYPE-USD":("87.017","87.031")}
        bid,ask=pairs[symbol]
        return {"results":[{"symbol":symbol,"bid":bid,"ask":ask}]}
    def trading_pairs(self):
        return [{"symbol":"HYPE-USD","is_api_tradable":True,
                 "min_order_amount":"0.10","asset_increment":"0.001",
                 "max_order_size":"100000"}]
    def positions(self,account):return []

class ExternalSalesJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=self.temp.name
        funded(self.root,"PEPE-USD","5194138","0.0000048",BUY2,"auto-pepe")
        funded(self.root,"ZEC-USD","0.00527","1181.70",BUY1,"auto-zec")
        self.j=OrderJournal(self.root)
        self.sells=[
            manual_sell("PEPE-USD","5194138",SOLD1,"manual-pepe-1"),
            manual_sell("ZEC-USD","0.00527",SOLD2,"manual-zec-1")]

    def test_external_fills_reduce_exposure_without_fake_bot_sell(self):
        self.assertEqual(len(self.j.positions()),2)
        result=self.j.reconcile_external_sells(ACCOUNT,self.sells,[])
        self.assertEqual(result["status"],"EXTERNAL_SALE_RECONCILED")
        self.assertEqual({x["symbol"] for x in result["adjustments"]},{"PEPE-USD","ZEC-USD"})
        self.assertEqual(self.j.positions(),{})
        self.assertEqual(self.j.pending(),[])
        added=[r for r in self.j.load()["orders"] if r.get("side")=="external_reduction"]
        self.assertEqual(len(added),2)
        self.assertTrue(all(r.get("source")=="broker_verified_external_sale" for r in added))
        self.assertFalse(any(r.get("realized_pnl_usd") for r in added))
        self.assertEqual(self.j.daily_realized_pnl(NOW),Decimal("0"))
        self.assertEqual(self.j.last_exit_at("PEPE-USD"),datetime.fromisoformat(SOLD1.replace("Z","+00:00")))

    def test_external_broker_sells_are_idempotent(self):
        self.j.reconcile_external_sells(ACCOUNT,self.sells,[])
        count=len(self.j.load()["orders"])
        result=self.j.reconcile_external_sells(ACCOUNT,self.sells,[])
        self.assertEqual(result["status"],"NO_BOT_POSITIONS")
        self.assertEqual(len(self.j.load()["orders"]),count)

    def test_broker_zero_without_sale_proof_keeps_lock(self):
        result=self.j.reconcile_external_sells(ACCOUNT,[],[])
        self.assertEqual(result["status"],"BROKER_HOLDINGS_MISMATCH")
        self.assertEqual(len(self.j.positions()),2)

    def test_pending_external_broker_order_does_not_clear_inventory(self):
        result=self.j.reconcile_external_sells(ACCOUNT,self.sells+[
            {"id":"pending","state":"open","side":"sell","symbol":"HYPE-USD"}],[])
        self.assertEqual(result["status"],"PENDING_BROKER_ORDER")
        self.assertEqual(len(self.j.positions()),2)

    def test_stale_external_sale_preceding_bot_purchase_does_not_clear(self):
        before="2026-11-03T10:00:00Z"
        sells=[manual_sell("PEPE-USD","5194138",before,"old-pepe"),
               manual_sell("ZEC-USD","0.00527",before,"old-zec")]
        result=self.j.reconcile_external_sells(ACCOUNT,sells,[])
        self.assertEqual(result["status"],"BROKER_HOLDINGS_MISMATCH")
        self.assertEqual(len(self.j.positions()),2)

    def test_partial_broker_holding_reconciles_only_confirmed_missing_quantity(self):
        result=self.j.reconcile_external_sells(ACCOUNT,self.sells,[
            {"asset_code":"PEPE","total_quantity":"194138"},
            {"asset_code":"ZEC","total_quantity":"0.00527"}])
        self.assertEqual(result["status"],"EXTERNAL_SALE_RECONCILED")
        self.assertEqual(self.j.positions()["PEPE-USD"]["quantity"],Decimal("194138"))
        self.assertEqual(self.j.positions()["ZEC-USD"]["quantity"],Decimal("0.00527"))

    def test_invalid_holdings_fails_closed(self):
        with self.assertRaises(Exception):
            self.j.reconcile_external_sells(ACCOUNT,self.sells,[
                {"asset_code":"PEPE","total_quantity":None}])
        self.assertEqual(len(self.j.positions()),2)

    def test_hype_risk_rejects_before_and_passes_after_external_reconciliation(self):
        policy={"enabled":True,"account":ACCOUNT,"max_order_usd":"7.50",
            "max_total_exposure_usd":"35","max_daily_loss_usd":"5",
            "max_open_positions":8,"verified_broker_minimum_usd":"0.1",
            "reentry_cooldown_minutes":30}
        sig={"symbol":"HYPE-USD","at":NOW.isoformat(),
             "technical_approved":True,"ai_approved":True}
        with self.assertRaisesRegex(OrderPassBlocked,"Maximum bot crypto exposure"):
            review_order(self.root,Fake(),policy,sig,NOW)
        self.j.reconcile_external_sells(ACCOUNT,self.sells,[])
        proposal=review_order(self.root,Fake(),policy,sig,NOW)
        self.assertGreater(Decimal(proposal["notional"]),Decimal("0"))
        self.assertLessEqual(Decimal(proposal["notional"]),Decimal("7.50"))
        self.assertEqual(proposal["risk"]["open_positions"],0)
        self.assertEqual(Decimal(proposal["risk"]["current_exposure_usd"]),0)

if __name__=="__main__":unittest.main()
