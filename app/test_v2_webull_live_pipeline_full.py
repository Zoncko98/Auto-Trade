"""V2 signed Webull full offline lifecycle: AI -> risk -> 1 broker POST -> GET fill."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import json
from trader_v2.models import (AssetClass,OrderSide,Candidate,AIReview,AIState,RiskPolicy)
from trader_v2.live_pipeline import LivePipeline,WriterHandoff
from trader_v2.writer_ownership import account_writer_scope,_paths,WriterOwnershipError
from trader_v2.store import EventStore
from trader_v2.webull_stock_live_adapter import WebullStockLiveAdapter
from trader_v2.live_position_projection import reconstruct
from test_v2_webull_stock_live_adapter import FakeSignedWebull

NOW=datetime.now(timezone.utc).replace(microsecond=0)

class ApprovedReviewer:
 def __init__(self,now):self.now=now
 def review(self,candidate,quote):
  return AIReview(AIState.PASS,candidate.symbol,self.now,
                  self.now+timedelta(seconds=60),"signed-test-model","Valid model schema")

class WebullLiveFullLifecycleTests(TestCase):
 def setUp(self):
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name)
  self.signed=FakeSignedWebull()
  self.adapter=WebullStockLiveAdapter(self.signed,"acct001",
   {"enabled":True,"trade_stocks":True,"stock_account":"acct001"},
   {"max_order_usd":"25","max_position_pct":"5",
    "max_daily_loss_usd":"15","max_open_positions":3},{},clock=lambda:datetime.now(timezone.utc))
  self.store=EventStore(self.base/"v2/events.sqlite3")
  self.proof=lambda:WriterHandoff("webull","acct001","v2-generation-1",
    self.now,self.now+timedelta(seconds=60),True,True,True,True,True,True,True)
  _,ownership,digest=_paths(self.base,"webull","acct001")
  ownership.write_text(json.dumps({"schema":1,"broker":"webull",
    "account_digest":digest,"owner":"V2","generation":"v2-generation-1"}))
  ownership.chmod(0o600)
  self.owner_file=ownership
  self.pipeline=LivePipeline(self.adapter,self.store,self.proof,
    ownership_root=self.base,reviewer=ApprovedReviewer(self.now))
  self.candidate=Candidate("stock_sma","migrate-2","acct001","F",
    AssetClass.STOCK,OrderSide.BUY,self.now,{"evidence":"confirmed cross"})
  self.risk=RiskPolicy(max_order_notional=D("25"),
    max_total_exposure=D("125"),max_position_fraction=D(".05"),
    max_daily_loss=D("15"),max_snapshot_age_seconds=60,
    ai_mode="REQUIRED")
  self.patch_session=patch("webull_signals.core_stock_session",return_value=True)
  self.patch_session.start();self.addCleanup(self.patch_session.stop)
 def evaluate(self):
  quote=self.adapter.quote("F",now=datetime.now(timezone.utc))
  return self.pipeline.evaluate(self.candidate,quote,self.risk,now=datetime.now(timezone.utc))
 def test_approved_candidate_posts_once_journals_signed_broker_ack_and_fill(self):
  out=self.evaluate()
  self.assertEqual(out.code,"BROKER_ACCEPTED")
  self.assertEqual(len(self.signed.posts),1)
  original=self.store.get(out.intent_key)
  self.assertEqual(original["state"],"BROKER_ACCEPTED")
  again=self.evaluate()
  self.assertEqual(again.code,"BROKER_ACCEPTED")
  self.assertEqual(len(self.signed.posts),1)
  # Signed broker receipt is the sole source of fills and fees.
  saved=self.signed.details[0]
  saved.update({"status":"FILLED","filled_quantity":original["document"] and "2",
      "filled_price":"10.05","fee_charged":"0.03",
      "filled_time_at":self.now.isoformat()})
  reconciled=self.pipeline.reconcile(out.intent_key)
  self.assertEqual(reconciled.code,"FILLED")
  self.assertEqual(len(self.signed.posts),1)
  portfolio=reconstruct(self.base,"acct001")
  self.assertEqual(portfolio["verified_v2_inventory"]["F"]["quantity"],"2")
  self.assertEqual(D(portfolio["verified_v2_inventory"]["F"]["cost_basis"]),
                   D("10.065"))
 def test_broker_owner_generation_mismatch_never_posts(self):
  data=json.loads(self.owner_file.read_text())
  data["owner"]="V1"
  self.owner_file.write_text(json.dumps(data));self.owner_file.chmod(0o600)
  out=self.evaluate()
  self.assertEqual(out.reason,"ACCOUNT_WRITER_OWNERSHIP_UNVERIFIED")
  self.assertEqual(self.signed.posts,[])
 def test_v1_cannot_submit_under_v2_ownership(self):
  with self.assertRaises(WriterOwnershipError):
   with account_writer_scope(self.base,"webull","acct001",owner="V1"):
    pass
 def test_valid_approval_but_ai_invalid_blocks_no_broker_post(self):
  class BadReviewer:
   def review(self,candidate,quote):
    return AIReview(AIState.PASS,"MSFT",self.now,
     self.now+timedelta(seconds=30),"invalid","Wrong symbol")
  self.pipeline.reviewer=BadReviewer()
  out=self.evaluate()
  self.assertEqual(out.reason,"AI_UNAVAILABLE")
  self.assertEqual(self.signed.posts,[])

if __name__=="__main__":main()
