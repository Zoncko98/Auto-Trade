"""Schwab V2 account alias and cash-only signed adapter tests, no live HTTP."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from trader_v2.schwab_stock_live_adapter import (
    SchwabStockLiveAdapter,SchwabLiveBlocked,account_alias,_receipt)
from trader_v2.live_pipeline import LiveMigrationRejected
from trader_v2.models import AssetClass,OrderSide,OrderIntent
import json

NOW=datetime.now(timezone.utc)
RAW="Th+is/Test=Hash"

class Reply:
 def __init__(self,status=200,data=None):
  self.status_code=status
  self._data=data
 def json(self):return self._data

class FakeSchwab:
 def __init__(self):
  self.posts=[]
  self.open_orders=[]
  self.price=D("10")
 def place_order(self,account,order):
  self.posts.append((account,order))
  return Reply(201)
 def get_quote(self,symbol):
  return Reply(200,{symbol:{"quote":{
    "bidPrice":9.99,"askPrice":10,
    "quoteTime":int(datetime.now(timezone.utc).timestamp()*1000),
    "lastPrice":9.995}}})
 def get_orders_for_account(self,account,max_results=100):
  return Reply(200,self.open_orders)
 def get_order(self,oid,account):
  return Reply(200,{"orderId":oid,"status":"WORKING","filledQuantity":0})

def signed_snapshot():
 return {"securitiesAccount":{
    "type":"CASH","positions":[],
    "currentBalances":{"cashBalance":200,"totalCash":200,"liquidationValue":200}}}

class SchwabV2AdapterTests(TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  folder=self.root/"live";folder.mkdir(mode=0o700)
  p=folder/"orders.json";p.write_text(json.dumps({"orders":[]}));p.chmod(0o600)
  self.client=FakeSchwab()
  self.alias=account_alias(RAW)
  self.adapter=SchwabStockLiveAdapter(self.client,RAW,state_dir=self.root,
        managed_positions={},operator_authorized=True,
        clock=lambda:datetime.now(timezone.utc),order_builder=lambda *args:{"TEST_ORDER":True},
        order_id_extractor=lambda response:"12345")
  self.acc=patch("live_worker.confirm_account",return_value=signed_snapshot())
  self.session=patch("live_worker.market_is_normal",return_value=True)
  self.acc.start();self.session.start()
  self.addCleanup(self.acc.stop);self.addCleanup(self.session.stop)
 def intent(self,side=OrderSide.BUY,qty="1",price="10.05"):
  return OrderIntent("schwab_v2_one",self.alias,"v2_stock","F",
        AssetClass.STOCK,side,D(qty),D(price),NOW)
 def test_canonical_alias_cannot_be_raw_sha_but_lock_scope_is_unmodified_v1_hash(self):
  self.assertNotEqual(self.alias,RAW)
  self.assertEqual(self.adapter.writer_scope_account,RAW)
  self.assertTrue(self.alias.startswith("schwab_"))
  self.assertEqual(account_alias(RAW),self.alias)
  self.assertNotEqual(account_alias("different"),self.alias)
 def test_signed_account_contains_no_external_sellable_inventory(self):
  item=self.adapter.account(self.alias)
  self.assertEqual(item.positions,{})
  self.assertEqual(item.cash,D("200"))
  self.assertEqual(item.equity,D("200"))
  self.assertEqual(item.account_id,self.alias)
  self.assertTrue(item.trading_enabled)
 def test_market_quote_and_session_are_broker_confirmed(self):
  quote=self.adapter.quote("F")
  self.assertEqual(quote.source,"schwab_signed")
  self.assertEqual(quote.last,D("9.995"))
  self.assertTrue(quote.market_open)
 def test_signed_broker_order_ack_is_not_fill(self):
  receipt=self.adapter.submit(self.intent())
  self.assertEqual(receipt.state,"BROKER_ACCEPTED")
  self.assertEqual(receipt.filled_quantity,D("0"))
  self.assertEqual(len(self.client.posts),1)
  self.assertEqual(self.client.posts[0][0],RAW)
 def test_disarmed_or_invalid_raw_account_never_posts(self):
  bad=SchwabStockLiveAdapter(self.client,RAW,state_dir=self.root,
            operator_authorized=False,clock=lambda:NOW)
  with self.assertRaises(LiveMigrationRejected):
   bad.submit(self.intent())
  self.assertEqual(self.client.posts,[])
  with self.assertRaises(SchwabLiveBlocked):
   account_alias("../../bad")
 def test_external_open_order_blocks(self):
  self.client.open_orders=[{"status":"WORKING","orderId":99}]
  with self.assertRaises(LiveMigrationRejected):
   self.adapter.submit(self.intent())
  self.assertEqual(self.client.posts,[])
 def test_fractional_stock_or_noncent_limit_refused(self):
  for item in (self.intent(qty="1.2"),self.intent(price="10.055")):
   with self.subTest(item=item),self.assertRaises(LiveMigrationRejected):
    self.adapter.submit(item)
  self.assertEqual(self.client.posts,[])
 def test_sell_without_managed_bot_lots_refused(self):
  with self.assertRaises(LiveMigrationRejected):
   self.adapter.submit(self.intent(side=OrderSide.SELL,price="9.95"))
  self.assertEqual(self.client.posts,[])
 def test_explicit_signed_fee_required_for_schwab_fill(self):
  raw={"orderId":12345,"status":"FILLED","filledQuantity":1,
       "orderActivityCollection":[{"executionLegs":[{
          "quantity":1,"price":10.1}]}]}
  with self.assertRaises(SchwabLiveBlocked):
   _receipt("schwab_v2_one",raw,12345)
  raw["orderActivityCollection"][0]["fees"]="0"
  result=_receipt("schwab_v2_one",raw,12345)
  self.assertEqual(result.state,"FILLED")
  self.assertEqual(result.average_price,D("10.1"))
  self.assertEqual(result.fees,D("0"))

if __name__=="__main__":main()
