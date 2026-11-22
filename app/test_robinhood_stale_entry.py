"""Signed original-order cancellation, single attempt, no skipped fills."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from robinhood_order_journal import OrderJournal
from robinhood_stale_entry import reconcile_stale_entry
from trader_v2.writer_ownership import _paths

NOW=datetime(2026,11,23,16,tzinfo=timezone.utc)
CID="123e4567-e89b-42d3-a456-426614174000"
OID="123e4567-e89b-42d3-a456-426614174001"
ACCOUNT="rh1"

class Broker:
 def __init__(self):self.calls=[];self.fail=False
 def cancel_order(self,account,oid):
  self.calls.append((account,oid))
  if self.fail:raise TimeoutError("unknown write outcome")
  return {"state":"pending"}

class StaleEntryTests(TestCase):
 def setUp(self):
  self.t=TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name)
  self.journal=OrderJournal(self.root)
  self.journal.record_intent(ACCOUNT,CID,"BTC-USD","0.001","50000","buy")
  self.journal.mark_submission_ack(CID,{"id":OID,"state":"open"})
  doc=self.journal.load()
  doc["orders"][0]["created_at"]=(NOW-timedelta(minutes=150)).isoformat()
  self.journal._save(doc)
  self.policy={"enabled":True,"account":ACCOUNT,"stale_entry_cancel_minutes":120}
  self.signed={"id":OID,"client_order_id":CID,"account_number":ACCOUNT,
               "side":"buy","symbol":"BTC-USD","state":"open",
               "filled_asset_quantity":"0","executions":[]}
  self.broker=Broker()
 def check(self,orders=None,policy=None):
  return reconcile_stale_entry(self.root,self.journal,policy or self.policy,
     ACCOUNT,orders if orders is not None else [self.signed],
     now=NOW,trader_factory=lambda state,policy:self.broker)
 def test_exact_signed_zero_fill_only_one_cancel_then_terminal(self):
  outcome=self.check()
  self.assertEqual(outcome["state"],"STALE_BUY_CANCEL_REQUESTED_AWAIT_BROKER")
  self.assertTrue(outcome["cancel_submitted"])
  self.assertEqual(self.broker.calls,[(ACCOUNT,OID)])
  self.assertEqual(self.journal.pending()[0]["status"],"cancel_requested")
  self.assertEqual(self.check()["state"],"STALE_BUY_CANCEL_ALREADY_REQUESTED")
  self.assertEqual(len(self.broker.calls),1)
  self.journal.reconcile(ACCOUNT,[dict(self.signed,state="canceled")])
  self.assertEqual(self.journal.pending(),[])
 def test_cancel_transport_timeout_does_not_repeat(self):
  self.broker.fail=True
  self.assertEqual(self.check()["state"],"STALE_BUY_CANCEL_OUTCOME_UNCERTAIN")
  self.broker.fail=False
  self.assertEqual(self.check()["state"],"STALE_BUY_CANCEL_ALREADY_REQUESTED")
  self.assertEqual(len(self.broker.calls),1)
 def test_partial_fill_or_missing_receipt_is_not_cancelled(self):
  for filled,executions in (("0.01",[]),(None,[]),
       ("0",[{"quantity":"0.0001","effective_price":"50000"}])):
   with self.subTest(filled=filled):
    row=dict(self.signed,filled_asset_quantity=filled,executions=executions)
    self.assertEqual(self.check([row])["state"],"STALE_BUY_ZERO_FILL_NOT_CONFIRMED")
    self.assertEqual(self.broker.calls,[])
 def test_mismatch_account_id_side_or_state_refuses_write(self):
  replacements=[{"id":"123e4567-e89b-42d3-a456-426614174002"},
     {"client_order_id":"123e4567-e89b-42d3-a456-426614174002"},
     {"account_number":"other"},{"side":"sell"},{"state":"partially_filled"}]
  for diff in replacements:
   with self.subTest(diff=diff):
    self.assertFalse(self.check([dict(self.signed,**diff)])["cancel_submitted"])
    self.assertFalse(self.broker.calls)
 def test_policy_off_and_zero_limit_do_not_cancel(self):
  self.policy["stale_entry_cancel_minutes"]=0
  self.assertEqual(self.check()["state"],"STALE_BUY_AUTO_CANCEL_DISABLED")
  self.policy["enabled"]=False
  self.assertEqual(self.check()["state"],"STALE_BUY_ACCOUNT_NOT_AUTHORIZED")
  self.assertFalse(self.broker.calls)
 def test_order_young_or_missing_broker_id_refused(self):
  doc=self.journal.load()
  doc["orders"][0]["created_at"]=(NOW-timedelta(minutes=5)).isoformat()
  self.journal._save(doc)
  self.assertEqual(self.check()["state"],"STALE_BUY_STILL_WITHIN_LIMIT")
  doc["orders"][0]["created_at"]=(NOW-timedelta(minutes=150)).isoformat()
  doc["orders"][0]["broker_order_id"]=None
  self.journal._save(doc)
  self.assertEqual(self.check()["state"],"STALE_BUY_ORIGINAL_BROKER_ORDER_ID_UNVERIFIED")
  self.assertFalse(self.broker.calls)
 def test_v2_owner_refuses_v1_cancel_and_preserves_intent(self):
  _,record,digest=_paths(self.root,"robinhood_crypto",ACCOUNT)
  record.write_text(json.dumps({"schema":1,"broker":"robinhood_crypto",
      "account_digest":digest,"owner":"V2","generation":"gen123"}))
  record.chmod(0o600)
  self.assertEqual(self.check()["state"],"STALE_BUY_CANCEL_NOT_AUTHORIZED")
  self.assertEqual(self.journal.pending()[0]["status"],"submitted_unconfirmed")
  self.assertFalse(self.broker.calls)
 def test_multiple_outstanding_orders_block_autocancel(self):
  doc=self.journal.load()
  doc["orders"].append(dict(doc["orders"][0],
       client_order_id="123e4567-e89b-42d3-a456-426614174099"))
  self.journal._save(doc)
  self.assertEqual(self.check()["state"],"MULTIPLE_UNRESOLVED_ORDERS")
  self.assertFalse(self.broker.calls)

 def test_repeated_signed_open_after_cancel_does_not_retry(self):
  first=self.check()
  self.assertTrue(first["cancel_submitted"])
  self.journal.reconcile(ACCOUNT,[self.signed])
  self.assertIsNotNone(self.journal.pending()[0].get("cancel_requested_at"))
  self.assertEqual(self.check()["state"],"STALE_BUY_CANCEL_ALREADY_REQUESTED")
  self.assertEqual(len(self.broker.calls),1)
