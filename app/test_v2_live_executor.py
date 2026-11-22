"""TrueNAS V2 executor: owner, broker proof, order and restart boundaries."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from trader_v2.live_executor import (
    account_cycle,write_status,public_status,SIGNED_GATES)
from trader_v2.live_pipeline import WriterHandoff
from trader_v2.v1_order_inheritance import InheritedOrderLimits

NOW=datetime(2026,11,22,15,0,tzinfo=timezone.utc)
ACCOUNT="rh1"
class Scanner:
 def __init__(self):self.runs=0
 def run_once(self):
  self.runs+=1
  return {"broker":"robinhood_crypto","state":"NO_VALIDATED_V2_SIGNAL",
          "broker_order_filled":False}

class ExecutorTests(TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.scanner=Scanner()
  self.rules=patch("robinhood_policy.read_policy",
         return_value={"enabled":True,"account":ACCOUNT}).start()
  self.addCleanup(patch.stopall)
 def grant(self,broker,account):
  return WriterHandoff(broker,account,"gen123",
      NOW,NOW+timedelta(seconds=60),True,True,True,True,True,True,True)
 def ready(self):
  return {"gates":[{"name":k,"verified":True} for k in SIGNED_GATES]}
 def inherited(self):
  return InheritedOrderLimits("robinhood_crypto",ACCOUNT,0,0,
       frozenset(),False,True,True)
 def test_v1_keeps_writer_never_constructs_broker_adapter(self):
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V1","generation":None}):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
      grant_provider=self.grant,scanner_factory=lambda *args:self.scanner,
      strategy_parity=lambda *args:True)
  self.assertEqual(result["reason"],"V1_RETAINS_ORDER_WRITER")
  self.assertEqual(self.scanner.runs,0)
 def test_no_operator_arm_does_not_load_broker(self):
  with patch("robinhood_policy.read_policy",
       return_value={"enabled":False,"account":ACCOUNT}):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW)
  self.assertEqual(result["reason"],"ACCOUNT_NOT_ARMED_OR_SELECTED")
 def test_existing_v2_owner_but_missing_broker_cash_or_quote_blocks(self):
  gates=self.ready()
  for gate in gates["gates"]:
   if gate["name"]=="SIGNED_SETTLED_FUNDING":gate["verified"]=False
  with patch("trader_v2.live_executor.inspect_ownership",
            return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=gates):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       grant_provider=self.grant,scanner_factory=lambda *args:self.scanner,
       strategy_parity=lambda *args:True)
  self.assertEqual(result["reason"],"SIGNED_BROKER_ACCOUNT_PREFLIGHT_BLOCKED")
  self.assertEqual(self.scanner.runs,0)
 def test_signed_history_cannot_default_to_zero(self):
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=self.ready()),patch(
       "trader_v2.live_executor.read_inherited",side_effect=ValueError("no signed history")):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       grant_provider=self.grant,scanner_factory=lambda *args:self.scanner,
       strategy_parity=lambda *args:True)
  self.assertEqual(result["reason"],"ACCOUNT_EXECUTION_NOT_VERIFIED")
  self.assertEqual(self.scanner.runs,0)
 def test_hardcoded_or_user_boolean_cannot_replace_strategy_parity(self):
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=self.ready()),patch(
       "trader_v2.live_executor.read_inherited",return_value=self.inherited()):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       grant_provider=self.grant,scanner_factory=lambda *args:self.scanner)
  self.assertEqual(result["reason"],"V1_STRATEGY_AND_EXIT_PARITY_REQUIRED")
  self.assertEqual(self.scanner.runs,0)
 def test_no_trusted_grant_or_adapter_refuses_scan(self):
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=self.ready()),patch(
       "trader_v2.live_executor.read_inherited",return_value=self.inherited()):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       strategy_parity=lambda *args:True)
  self.assertEqual(result["reason"],"TRUSTED_BROKER_EXECUTOR_NOT_WIRED")
  self.assertEqual(self.scanner.runs,0)
 def test_wrong_handoff_generation_blocks_scan(self):
  def wrong(b,a):
   return WriterHandoff(b,a,"oldgen",NOW,NOW+timedelta(seconds=60),
                 True,True,True,True,True,True,True)
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=self.ready()),patch(
       "trader_v2.live_executor.read_inherited",return_value=self.inherited()):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       grant_provider=wrong,scanner_factory=lambda *args:self.scanner,
       strategy_parity=lambda *args:True)
  self.assertEqual(result["reason"],"V2_HANDOFF_PROOF_INVALID")
  self.assertEqual(self.scanner.runs,0)
 def test_independent_signed_grant_can_invoke_shared_scan(self):
  with patch("trader_v2.live_executor.inspect_ownership",
          return_value={"owner":"V2","generation":"gen123"}),patch(
       "trader_v2.live_executor.launch_status",return_value=self.ready()),patch(
       "trader_v2.live_executor.read_inherited",return_value=self.inherited()):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW,
       grant_provider=self.grant,scanner_factory=lambda *args:self.scanner,
       strategy_parity=lambda *args:True)
  self.assertEqual(result["state"],"SCANNED")
  self.assertEqual(self.scanner.runs,1)
  self.assertNotIn(ACCOUNT,str(result))
 def test_no_private_account_leak_even_if_broker_exception_contains_secret(self):
  with patch("trader_v2.live_executor.inspect_ownership",
         side_effect=ValueError("raw-key-do-not-report")):
   result=account_cycle(self.root,"robinhood_crypto",now=NOW)
  self.assertEqual(result["reason"],"ACCOUNT_EXECUTION_NOT_VERIFIED")
  self.assertNotIn("raw-key-do-not-report",str(result))
 def test_registered_process_is_not_order_authority(self):
  doc=write_status(self.root,now=NOW)
  self.assertEqual(doc["mode"],"REGISTERED_GATED_EXECUTION_COORDINATOR")
  self.assertTrue(all(item["state"]=="BLOCKED" for item in doc["accounts"]))
  safe=public_status(self.root,now=NOW)
  self.assertTrue(safe["registered"])
  self.assertEqual(len(safe["accounts"]),3)
  self.assertFalse(public_status(self.root,now=NOW+timedelta(minutes=3))["registered"])
  self.assertNotIn(ACCOUNT,str(safe))
 def test_forged_status_refuses_live_health(self):
  write_status(self.root,now=NOW)
  path=self.root/"v2/live_executor/health.json"
  doc=json.loads(path.read_text())
  doc["accounts"][0]["reason"]="BROKER_FILLED_NO_RECEIPT"
  path.write_text(json.dumps(doc))
  self.assertFalse(public_status(self.root,now=NOW)["registered"])
 def test_private_status_permissions(self):
  write_status(self.root,now=NOW)
  target=self.root/"v2/live_executor/health.json"
  self.assertEqual(target.stat().st_mode&0o077,0)
  self.assertEqual(target.parent.stat().st_mode&0o077,0)
