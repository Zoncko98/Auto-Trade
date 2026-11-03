import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch
from robinhood_portfolio_pnl import estimated_acquisition_cost,position_return

T0=datetime(2026,11,1,tzinfo=timezone.utc)
def order(symbol,side,qty,price,offset=0,state="filled",executions=None):
    row={"symbol":symbol,"side":side,"state":state,
         "filled_asset_quantity":str(qty),"average_price":str(price),
         "created_at":(T0+timedelta(minutes=offset)).isoformat()}
    if executions is not None:row["executions"]=executions
    return row

class PnlBasisTests(unittest.TestCase):
    def test_buy_and_partial_sell_preserve_weighted_cost(self):
        rows=[order("PEPE-USD","buy","100","0.002",0),
              order("PEPE-USD","buy","100","0.004",10),
              order("PEPE-USD","sell","50","0.005",20)]
        avg,issue=estimated_acquisition_cost("PEPE-USD","150",rows)
        self.assertIsNone(issue)
        self.assertEqual(avg,Decimal("0.003"))
        pnl,pct=position_return("150","0.0033",avg)
        self.assertEqual(pnl,Decimal("0.0450"))
        self.assertEqual(pct,Decimal("10.0"))
    def test_negative_unrealized_pnl(self):
        avg,issue=estimated_acquisition_cost("ZEC-USD","0.00527",
                        [order("ZEC-USD","buy","0.00527","10100")])
        self.assertIsNone(issue)
        pnl,pct=position_return("0.00527","9756.34",avg)
        self.assertLess(pnl,0)
        self.assertLess(pct,0)
    def test_unmatched_external_position_is_not_given_zerobasis(self):
        avg,reason=estimated_acquisition_cost("ZEC-USD","5",[])
        self.assertIsNone(avg)
        self.assertIn("No matching",reason)
    def test_transfer_or_reward_quantity_mismatch_fails_closed(self):
        avg,reason=estimated_acquisition_cost("PEPE-USD","1000",
                 [order("PEPE-USD","buy","100","0.01")])
        self.assertIsNone(avg)
        self.assertIn("do not reconcile",reason)
    def test_missing_fill_price_cannot_use_limit_price(self):
        row=order("ZEC-USD","buy","1","2")
        row["average_price"]=None
        row["limit_order_config"]={"limit_price":"2"}
        avg,reason=estimated_acquisition_cost("ZEC-USD","1",[row])
        self.assertIsNone(avg)
        self.assertIn("incomplete",reason)
    def test_execution_fallback_uses_weighted_average_fill(self):
        row=order("BTC-USD","buy","1","1")
        row["average_price"]=None
        row["executions"]=[{"quantity":"0.3","effective_price":"100"},
                           {"quantity":"0.7","effective_price":"200"}]
        avg,_=estimated_acquisition_cost("BTC-USD","1",[row])
        self.assertEqual(avg,Decimal("170.0"))
    def test_does_not_count_order_with_zero_fill(self):
        row=order("BTC-USD","buy","0","100",state="canceled")
        avg,_=estimated_acquisition_cost("BTC-USD","1",[row])
        self.assertIsNone(avg)
    def test_out_of_sequence_sell_fails_closed(self):
        rows=[order("BTC-USD","sell","2","50000",0),order("BTC-USD","buy","2","60000",5)]
        avg,why=estimated_acquisition_cost("BTC-USD","2",rows)
        self.assertIsNone(avg)
        self.assertIn("earlier holdings",why)

class PortfolioApiTests(unittest.TestCase):
    def test_two_holdings_gain_and_loss_and_cash_separation(self):
        import broker_workspace
        class Fake:
            def list_accounts(self):
                return [{"account_number":"test","buying_power":"28.30","buying_power_currency":"USD"}]
            def positions(self,ref):
                return [{"asset_code":"PEPE","total_quantity":"3922534","quantity_available_for_trading":"3922534"},
                        {"asset_code":"ZEC","total_quantity":"0.00527","quantity_available_for_trading":"0.00527"}]
            def orders(self,ref):
                return [order("PEPE-USD","buy","3922534","0.000000432"),
                        order("ZEC-USD","buy","0.00527","10100")]
            def quote(self,symbol):
                if symbol=="PEPE-USD":return {"results":[{"symbol":symbol,"bid":"0.00000047","ask":"0.00000048"}]}
                return {"results":[{"symbol":symbol,"bid":"9750","ask":"9760"}]}
        with patch.object(broker_workspace,"_robinhood_client",return_value=Fake()):
            data=broker_workspace.robinhood_portfolio("/unused")
        self.assertTrue(data["available"])
        self.assertEqual(data["pnl_covered_holdings"],2)
        self.assertEqual(data["pnl_completeness"],"complete_estimate")
        self.assertGreater(Decimal(data["holdings"][0]["unrealized_pnl_usd"]),0)
        self.assertLess(Decimal(data["holdings"][1]["unrealized_pnl_usd"]),0)
        self.assertGreater(Decimal(data["estimated_crypto_account_value_usd"]),Decimal(data["known_holdings_value_usd"]))
    def test_partial_basis_never_claims_complete_pnl(self):
        import broker_workspace
        class Fake:
            def list_accounts(self):return [{"account_number":"a","buying_power":"0","buying_power_currency":"USD"}]
            def positions(self,ref):
                return [{"asset_code":"PEPE","total_quantity":"100","quantity_available_for_trading":"100"},
                        {"asset_code":"ZEC","total_quantity":"1","quantity_available_for_trading":"1"}]
            def orders(self,ref):return [order("PEPE-USD","buy","100","0.01")]
            def quote(self,symbol):
                return {"results":[{"symbol":symbol,"bid":"0.02","ask":"0.02"}]}
        with patch.object(broker_workspace,"_robinhood_client",return_value=Fake()):
            data=broker_workspace.robinhood_portfolio("/unused")
        self.assertIsNone(data["unrealized_pnl_usd"])
        self.assertEqual(data["pnl_covered_holdings"],1)
        self.assertEqual(data["pnl_total_holdings"],2)
        self.assertIsNone(data["holdings"][1]["average_cost_usd"])

if __name__=="__main__":
    unittest.main()
