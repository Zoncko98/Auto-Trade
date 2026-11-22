"""Webull V2 official SDK cash-stock adapter, no actual broker calls."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from unittest import TestCase,main
from trader_v2.models import AssetClass,OrderSide,OrderIntent
from trader_v2.live_pipeline import LiveMigrationRejected
from trader_v2.webull_stock_live_adapter import WebullStockLiveAdapter,WebullLiveBlocked
from trader_v2.webull_signed_receipts import client_order_id

NOW=datetime.now(timezone.utc)

class FakeSignedWebull:
 def __init__(self):
  self.posts=[]
  self.details=[]
  self.preview_calls=0
  self.accounts_calls=0
  self.cash="500"
  self.position_rows=[]
  self.pending=[]
  self.quoted_at=NOW
  self.kind="INDIVIDUAL_STOCK"
 def verify_account(self,account):
  self.accounts_calls+=1
  if account!="acct001":raise ValueError("not signed")
  return {"account_id":account,"account_type":self.kind}
 def balance(self,account):
  self.verify_account(account)
  return {"total_asset_currency":"USD",
   "total_net_liquidation_value":"500",
   "total_market_value":"0",
   "total_cash_balance":self.cash,"total_day_profit_loss":"1",
   "account_currency_assets":[{"currency":"USD","cash_balance":self.cash,
                                "settled_cash":self.cash,"held_amount":"0","frozen_amount":"0"}],
   "used_margin":"0"}
 def positions(self,account):
  self.verify_account(account)
  return self.position_rows
 def open_orders(self,account):
  self.verify_account(account)
  return self.pending
 def quote(self,symbol,asset):
  assert asset=="EQUITY"
  return {"symbol":symbol,"quote_time":datetime.now(timezone.utc).isoformat(),
          "bid":"9.99","ask":"10","last":"9.995"}
 def stock_snapshot(self,symbol):
  return {"symbol":symbol,"time":datetime.now(timezone.utc).isoformat(),
          "price":"9.995"}
 def preview(self,account,payload):
  self.preview_calls+=1
  return {"success":True}
 def place(self,account,payload):
  self.posts.append(payload)
  self.details.append({"client_order_id":payload["client_order_id"],
      "order_id":"official-sdk-order-1","status":"SUBMITTED",
      "account_id":account,"filled_quantity":"0"})
  return {"accepted":True}
 def order_detail(self,account,identity):
  rows=[r for r in self.details if r["client_order_id"]==identity]
  return {"orders":rows}

class WebullV2CashStockTests(TestCase):
 def setUp(self):
  self.signed=FakeSignedWebull()
  self.policy={"enabled":True,"trade_stocks":True,"stock_account":"acct001"}
  self.risk={"max_order_usd":"25","max_position_pct":"5",
    "max_daily_loss_usd":"15","max_open_positions":3}
  self.clock=lambda:datetime.now(timezone.utc)
  self.adapter=WebullStockLiveAdapter(self.signed,"acct001",self.policy,
    self.risk,{},clock=self.clock)
 def intent(self,side=OrderSide.BUY,qty="1",price="10.05"):
  return OrderIntent("webull_v2_1","acct001","stock_m5","F",
      AssetClass.STOCK,side,D(qty),D(price),NOW)
 def test_authenticated_cash_stock_account_with_no_managed_inventory(self):
  acct=self.adapter.account("acct001")
  self.assertEqual(acct.broker,"webull")
  self.assertEqual(acct.cash,D("500"))
  self.assertEqual(acct.equity,D("500"))
  self.assertEqual(acct.positions,{})
  self.assertEqual(acct.market_exposure,D("0"))
  self.assertFalse(acct.capability.fractional)
 def test_missing_reserve_evidence_never_funds_a_v2_buy(self):
  from unittest.mock import patch
  old=self.signed.balance
  def uncertain(account):
   row=old(account)
   row["account_currency_assets"][0].pop("frozen_amount")
   return row
  self.signed.balance=uncertain
  self.assertEqual(self.adapter.account("acct001").cash,D("0"))
  with patch("webull_signals.core_stock_session",return_value=True):
   with self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(self.intent())
  self.assertEqual(self.signed.posts,[])

 def test_signed_quote_only_inside_core_session(self):
  from unittest.mock import patch
  # The broker session may be closed when tests run; inject validated gate
  with patch("webull_signals.core_stock_session",return_value=True):
   snapshot=self.adapter.quote("F")
  self.assertEqual(snapshot.source,"webull_signed")
  self.assertEqual(snapshot.ask,D("10"))
  self.assertEqual(snapshot.last,D("9.995"))
 def test_no_real_post_until_preview_and_broker_account_limits_pass(self):
  from unittest.mock import patch
  with patch("webull_signals.core_stock_session",return_value=True):
   out=self.adapter.submit(self.intent())
  self.assertEqual(out.state,"BROKER_ACCEPTED")
  self.assertEqual(self.signed.preview_calls,1)
  self.assertEqual(len(self.signed.posts),1)
  self.assertEqual(self.signed.posts[0]["client_order_id"],
                   client_order_id("webull_v2_1","acct001"))
 def test_spend_cap_cannot_be_raised_by_caller_or_ratio(self):
  from unittest.mock import patch
  with patch("webull_signals.core_stock_session",return_value=True):
   with self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(self.intent(qty="4"))
  self.assertEqual(self.signed.posts,[])
 def test_open_broker_orders_block_even_valid_v2_signal(self):
  from unittest.mock import patch
  self.signed.pending=[{"order_id":"other"}]
  with patch("webull_signals.core_stock_session",return_value=True):
   with self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(self.intent())
  self.assertEqual(self.signed.posts,[])
 def test_v2_sell_requires_verified_bot_and_broker_inventory(self):
  from unittest.mock import patch
  self.signed.position_rows=[{"symbol":"F","instrument_type":"EQUITY","quantity":"2"}]
  with patch("webull_signals.core_stock_session",return_value=True):
   with self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(self.intent(side=OrderSide.SELL,qty="1",price="9.95"))
  self.assertEqual(self.signed.posts,[])
 def test_missing_holding_or_cross_account_blocks(self):
  with self.assertRaises(WebullLiveBlocked):
   self.adapter.account("different")
  self.signed.position_rows=[{"symbol":"F","instrument_type":"CRYPTO","quantity":"1"}]
  with self.assertRaises(WebullLiveBlocked):
   self.adapter.account("acct001")
 def test_unauthorized_stock_class_and_margin_without_optin_rejected(self):
  self.signed.kind="INDIVIDUAL_MARGIN"
  with self.assertRaises(WebullLiveBlocked):
   self.adapter.account("acct001")
 def test_negative_pnl_blocks_without_post(self):
  from unittest.mock import patch
  orig=self.signed.balance
  def loss(account):
   data=orig(account)
   data["total_day_profit_loss"]="-100"
   return data
  self.signed.balance=loss
  with patch("webull_signals.core_stock_session",return_value=True):
   with self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(self.intent())
  self.assertEqual(self.signed.posts,[])

if __name__=="__main__":main()
