"""Stock tick-size and real V1 raw Schwab writer lock fence tests."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from trader_v2.models import (Account,Capability,AssetClass,AuthState,
 Candidate,OrderSide,MarketSnapshot,RiskPolicy)
from trader_v2.risk import evaluate_risk
from trader_v2.live_pipeline import LivePipeline,WriterHandoff
from trader_v2.writer_ownership import _paths
from trader_v2.store import EventStore
from trader_v2.contracts import BrokerExecution
import json

NOW=datetime.now(timezone.utc).replace(microsecond=0)
RAW="Original/Schwab+Hash="
ALIAS="schwab_alias_id"

class FakeSignedStockBroker:
 provider_id="schwab"
 writer_scope_account=RAW
 def __init__(self):self.sent=0;self.last=None
 def account(self,aid):
  assert aid==ALIAS
  return Account(aid,"schwab",Capability(
    frozenset({AssetClass.STOCK}),fractional=False,
    price_increment=D(".01"),quantity_increment=D("1")),
    D("20"),D("100"),{"F":D("1")},AuthState.CONNECTED,True,D("10"))
 def submit(self,intent):
  self.sent+=1
  self.last=BrokerExecution(intent.key,"FILLED","signed-123",
      intent.quantity,intent.limit_price,D("0"))
  return self.last
 def find_order(self,key):
  return self.last if self.last and self.last.key==key else None

class StockTickAndRawLockTests(TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.broker=FakeSignedStockBroker()
  self.account=self.broker.account(ALIAS)
  self.quote=MarketSnapshot("F",AssetClass.STOCK,"schwab_signed",
    NOW,NOW,D("10"),D("10.01"),D("10"),True)
  self.policy=RiskPolicy(max_order_notional=D("20"),max_total_exposure=D("50"),
    max_position_fraction=D(".5"),max_entries_per_day=1,
    max_exit_orders_per_day=3,ai_mode="REQUIRED")
  self.candidate=Candidate("stock_m5","v2",ALIAS,"F",AssetClass.STOCK,
    OrderSide.SELL,NOW,{"technical":"confirmed downward cross"})
  lock,record,digest=_paths(self.root,"schwab",RAW)
  record.write_text(json.dumps({"schema":1,"broker":"schwab",
     "account_digest":digest,"owner":"V2","generation":"generation_1234"}))
  record.chmod(0o600)
  self.record=record
  self.store=EventStore(self.root/"v2/order.sqlite3")
  self.proof=lambda:WriterHandoff("schwab",ALIAS,"generation_1234",
    NOW,NOW+timedelta(seconds=100),True,True,True,True,True,True,True)
  self.pipe=LivePipeline(self.broker,self.store,self.proof,ownership_root=self.root)
 def test_broker_cents_tick_for_stock_buy_and_sell(self):
  buy=Candidate("stock_m5","v2",ALIAS,"F",AssetClass.STOCK,
    OrderSide.BUY,NOW,{"technical":"upward cross"})
  account=Account(ALIAS,"schwab",self.account.capability,
      D("100"),D("100"),{},AuthState.CONNECTED,True,D("0"))
  buy_result=evaluate_risk(account,buy,self.quote,self.policy,now=NOW)
  self.assertEqual(buy_result.code,"PASS")
  self.assertEqual(buy_result.limit_price,D("10.07"))
  sell_result=evaluate_risk(self.account,self.candidate,self.quote,self.policy,now=NOW)
  self.assertEqual(sell_result.code,"PASS")
  self.assertEqual(sell_result.limit_price,D("9.95"))
 def test_required_ai_must_not_veto_verified_protective_sell(self):
  result=self.pipe.evaluate(self.candidate,self.quote,self.policy,
      now=NOW,entries_today=999,daily_realized_loss=D("100"))
  self.assertEqual(result.code,"FILLED")
  self.assertEqual(self.broker.sent,1)
 def test_exclusive_raw_schwab_v1_lock_blocks_if_untransferred(self):
  data=json.loads(self.record.read_text())
  data["owner"]="V1"
  self.record.write_text(json.dumps(data));self.record.chmod(0o600)
  result=self.pipe.evaluate(self.candidate,self.quote,self.policy,now=NOW)
  self.assertEqual(result.reason,"ACCOUNT_WRITER_OWNERSHIP_UNVERIFIED")
  self.assertEqual(self.broker.sent,0)
 def test_alias_owner_record_cannot_override_raw_v1_lock(self):
  from trader_v2.writer_ownership import _paths
  _,alias_record,digest=_paths(self.root,"schwab",ALIAS)
  alias_record.write_text(json.dumps({"schema":1,"broker":"schwab",
      "account_digest":digest,"owner":"V2","generation":"generation_1234"}))
  alias_record.chmod(0o600)
  data=json.loads(self.record.read_text());data["owner"]="V1"
  self.record.write_text(json.dumps(data));self.record.chmod(0o600)
  result=self.pipe.evaluate(self.candidate,self.quote,self.policy,now=NOW)
  self.assertEqual(result.reason,"ACCOUNT_WRITER_OWNERSHIP_UNVERIFIED")
  self.assertEqual(self.broker.sent,0)
 def test_sell_exit_daily_cap_still_enforced(self):
  self.policy=RiskPolicy(max_order_notional=D("20"),
    max_total_exposure=D("50"),max_position_fraction=D(".5"),
    max_exit_orders_per_day=1,ai_mode="REQUIRED")
  result=self.pipe.evaluate(self.candidate,self.quote,self.policy,
    now=NOW,exits_today=1)
  self.assertEqual(result.code,"BLOCKED")
  self.assertEqual(self.broker.sent,0)

if __name__=="__main__":main()
