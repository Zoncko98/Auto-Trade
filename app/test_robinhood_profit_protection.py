"""Take-profit, trailing high-water, and actual broker-fee regression scenarios."""
import tempfile,unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch
from robinhood_order_journal import OrderJournal
from robinhood_exit_tracker import ExitTracker
from robinhood_order_pass import review_sell,review_order,OrderPassBlocked
from robinhood_fee_estimates import effective_sell_fee_pct
from robinhood_policy import read_policy,save_policy,PolicyError

NOW=datetime(2026,11,3,20,0,tzinfo=timezone.utc)

def record_fill(root,client_id,qty,price,fee,symbol="BTC-USD",at=NOW-timedelta(minutes=40)):
    j=OrderJournal(root)
    j.record_intent("acct",client_id,symbol,qty,price)
    j.reconcile("acct",[{"client_order_id":client_id,"symbol":symbol,"state":"filled",
         "filled_asset_quantity":str(qty),"average_price":str(price),
         "fee_charged":str(fee),"updated_at":at.isoformat()}])
    return j

class Fake:
    def __init__(self,bid,ask,held="2",symbol="BTC-USD"):
        self.bid=str(bid);self.ask=str(ask);self.held=str(held);self.symbol=symbol
    def list_accounts(self):
        return [{"account_number":"acct","status":"active","is_api_tradable":True,
                 "buying_power_currency":"USD","buying_power":"100"}]
    def quote(self,symbol):
        return {"results":[{"symbol":symbol,"bid":self.bid,"ask":self.ask}]}
    def trading_pairs(self):
        return [{"symbol":self.symbol,"asset_code":self.symbol[:-4],"quote_code":"USD",
                 "is_api_tradable":True,"min_order_amount":"0.10",
                 "asset_increment":"0.001","max_order_size":"1000000"}]
    def positions(self,account):
        return [{"asset_code":self.symbol[:-4],"total_quantity":self.held,
                 "quantity_available_for_trading":self.held}]
    def orders(self,account):return []

def policy():
    return {"account":"acct","enabled":True,"max_order_usd":"7.50",
      "max_total_exposure_usd":"35","max_daily_loss_usd":"5",
      "max_open_positions":8,"verified_broker_minimum_usd":"0.1",
      "min_hold_minutes":15,"min_profit_pct":"1","stop_loss_pct":"2",
      "fee_buffer_pct":"0.25","take_profit_pct":"3",
      "trailing_activation_pct":"2","trailing_drawdown_pct":"0.75",
      "max_single_asset_exposure_pct":"60","min_add_interval_minutes":30}

class ExitAndConcentrationTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root=self.tmp.name
    self.policy=policy()
 def buy(self,quantity="2",price="10",fee="0.19",symbol="BTC-USD",when=NOW-timedelta(minutes=40)):
    return record_fill(self.root,"first-"+symbol,quantity,price,fee,symbol,when)
 def signal(self,technical=False,symbol="BTC-USD"):
    return {"symbol":symbol,"technical_exit":technical,"at":NOW.isoformat()}
 def test_real_fee_reserve_is_higher_than_user_minimum(self):
    j=self.buy()
    reserve,source=effective_sell_fee_pct(self.policy,j)
    self.assertEqual(source,"broker_fill_history")
    self.assertEqual(reserve,Decimal("0.9975"))
 def test_absent_fee_history_preserves_configured_floor(self):
    fee,source=effective_sell_fee_pct(self.policy,OrderJournal(self.root))
    self.assertEqual(fee,Decimal("0.25"))
    self.assertEqual(source,"configured")
 def test_3pct_take_profit_without_reversal(self):
    self.buy()
    result=review_sell(self.root,Fake("10.60","10.61"),self.policy,self.signal(),NOW)
    self.assertEqual(result["exit_mode"],"TAKE_PROFIT")
    self.assertGreater(Decimal(result["estimated_pnl_pct"]),Decimal("3"))
    self.assertEqual(Decimal(result["fee_buffer_pct"]),Decimal("0.9975"))
 def test_trailing_trigger_persists_across_restarts(self):
    j=self.buy()
    pos=j.positions()["BTC-USD"]
    first=ExitTracker(self.root)
    first.update("acct",{"BTC-USD":pos},{"BTC-USD":Decimal("10.50")})
    new_instance=ExitTracker(self.root)
    self.assertEqual(new_instance.peak("acct","BTC-USD",pos),Decimal("10.50"))
    new_instance.update("acct",{"BTC-USD":pos},{"BTC-USD":Decimal("10.41")})
    result=review_sell(self.root,Fake("10.41","10.42"),self.policy,self.signal(),NOW)
    self.assertEqual(result["exit_mode"],"TRAILING_PROFIT")
    self.assertGreater(Decimal(result["peak_retracement_pct"]),Decimal("0.75"))
    self.assertGreater(Decimal(result["estimated_pnl_pct"]),Decimal("1"))
 def test_no_trailing_if_peak_qualifies_but_profit_fell_below_one_percent(self):
    j=self.buy()
    pos=j.positions()["BTC-USD"]
    ExitTracker(self.root).update("acct",{"BTC-USD":pos},{"BTC-USD":Decimal("10.50")})
    with self.assertRaisesRegex(OrderPassBlocked,"Exit blocked"):
        review_sell(self.root,Fake("10.25","10.26"),self.policy,self.signal(),NOW)
 def test_peak_is_reset_on_new_filled_lot(self):
    j=self.buy()
    pos=j.positions()["BTC-USD"]
    tracker=ExitTracker(self.root)
    tracker.update("acct",{"BTC-USD":pos},{"BTC-USD":Decimal("10.50")})
    j.record_intent("acct","second-btc","BTC-USD","1","10")
    j.reconcile("acct",[{"client_order_id":"second-btc","state":"filled",
      "filled_asset_quantity":"1","average_price":"10","fee_charged":"0.095",
      "updated_at":(NOW-timedelta(minutes=25)).isoformat()}])
    new=j.positions()["BTC-USD"]
    tracker.update("acct",{"BTC-USD":new},{"BTC-USD":Decimal("10.30")})
    self.assertEqual(ExitTracker(self.root).peak("acct","BTC-USD",new),Decimal("10.30"))
 def test_stop_loss_trigger_remains_legacy_boundary_when_fee_reserve_rises(self):
    self.buy()
    result=review_sell(self.root,Fake("9.85","9.86"),self.policy,self.signal(),NOW)
    self.assertEqual(result["exit_mode"],"STOP_LOSS")
 def test_under_15_min_hold_does_not_trigger_profit_sell(self):
    self.buy(when=NOW-timedelta(minutes=4))
    with self.assertRaisesRegex(OrderPassBlocked,"Exit blocked"):
        review_sell(self.root,Fake("10.70","10.71"),self.policy,self.signal(),NOW)
 def test_repeated_buy_blocked_by_addon_interval(self):
    self.buy(quantity="1",fee="0.095",when=NOW-timedelta(minutes=8))
    with self.assertRaisesRegex(OrderPassBlocked,"Additional buy cooldown"):
        review_order(self.root,Fake("10","10.01","1"),self.policy,
          {"symbol":"BTC-USD","at":NOW.isoformat(),"technical_approved":True,"ai_approved":True},NOW)
 def test_asset_concentration_blocks_third_buy(self):
    self.buy(quantity="2",fee="0.19",when=NOW-timedelta(minutes=80))
    with self.assertRaisesRegex(OrderPassBlocked,"Single-asset exposure"):
        review_order(self.root,Fake("10","10.01","2"),self.policy,
          {"symbol":"BTC-USD","at":NOW.isoformat(),"technical_approved":True,"ai_approved":True},NOW)
 def test_buys_in_other_symbols_remain_allowed(self):
    self.policy["take_profit_pct"]="4.0"  # preserve a net target despite verified 1% per-side fees
    self.buy(quantity="2",fee="0.19",when=NOW-timedelta(minutes=80))
    p=review_order(self.root,Fake("10","10.01","0",symbol="ETH-USD"),self.policy,
       {"symbol":"ETH-USD","at":NOW.isoformat(),"technical_approved":True,"ai_approved":True},NOW)
    self.assertEqual(p["symbol"],"ETH-USD")
 def test_policy_can_save_all_new_controls(self):
    payload=dict(policy(),account="acct")
    result=save_policy(self.root,payload,Fake("10","10.01").list_accounts(),
                       Fake("10","10.01").trading_pairs())
    self.assertTrue(result["enabled"])
    self.assertEqual(result["take_profit_pct"],"3")
    self.assertEqual(result["trailing_drawdown_pct"],"0.75")
    self.assertEqual(result["max_single_asset_exposure_pct"],"60")
    self.assertEqual(result["min_add_interval_minutes"],30)

if __name__=="__main__":unittest.main()
