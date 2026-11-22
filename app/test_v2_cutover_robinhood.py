"""Test one-account cutover coordination without network or real orders."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from trader_v2.cutover_robinhood import attempt,CutoverBlocked
from trader_v2.live_executor import SIGNED_GATES

class AtomicRobinhoodCutoverTests(TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.approved_digest=sha256(b"robinhood_crypto|rh1").hexdigest()
  self.policy=patch("robinhood_policy.read_policy",
      return_value={"enabled":True,"account":"rh1"}).start()
  self.owner=patch("trader_v2.cutover_robinhood.inspect_ownership",
      return_value={"owner":"V1","generation":None}).start()
  self.exec=patch("trader_v2.cutover_robinhood.executor_status",
      return_value={"registered":True}).start()
  self.preflight=patch("trader_v2.cutover_robinhood._preflight",
      return_value=["ETH-USD"]).start()
  self.signed=patch("trader_v2.cutover_robinhood._check_signed",
      return_value=({},None)).start()
  self.launch=patch("trader_v2.cutover_robinhood.launch_status",
      return_value={"gates":[{"name":k,"verified":True}
          for k in SIGNED_GATES]}).start()
  self.running=True
  self.stopped=patch("trader_v2.cutover_robinhood.signed_v1_worker_stopped",
      side_effect=lambda:not self.running).start()
  self.transferred=patch("trader_v2.cutover_robinhood.transfer_writer",
      return_value={"owner":"V2","generation":"newgen"}).start()
  @contextmanager
  def writer(*args,**kwargs):
   yield {"owner":"V1","generation":None}
  self.scope=patch("trader_v2.cutover_robinhood.account_writer_scope",
       side_effect=writer).start()
  self.addCleanup(patch.stopall)
 def stop(self):
  self.running=False
 def test_unapproved_cutover_never_quiesces_or_transfers(self):
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=False,approved_account_digest=self.approved_digest)
  self.assertEqual(out["reason"],"EXPLICIT_CUTOVER_APPROVAL_REQUIRED")
  self.assertTrue(self.running)
  self.transferred.assert_not_called()
  self.assertEqual(out["state"],"BLOCKED")
 def test_approval_does_not_apply_to_a_different_account(self):
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=True,approved_account_digest="0"*64)
  self.assertEqual(out["reason"],"CUTOVER_APPROVED_ACCOUNT_NOT_SELECTED")
  self.assertTrue(self.running)
  self.transferred.assert_not_called()

 def test_missing_replacement_never_interrupts_current_worker(self):
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=False,
              operator_approved=True,approved_account_digest=self.approved_digest)
  self.assertEqual(out["reason"],"V2_COORDINATOR_NOT_RUNNING")
  self.assertTrue(self.running)
  self.transferred.assert_not_called()
 def test_missing_signed_held_lot_evidence_stops_nothing(self):
  self.preflight.side_effect=CutoverBlocked("LEGACY_MANAGED_LOTS_REQUIRE_ADOPTION")
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=True,approved_account_digest=self.approved_digest)
  self.assertEqual(out["reason"],"LEGACY_MANAGED_LOTS_REQUIRE_ADOPTION")
  self.assertTrue(self.running)
  self.transferred.assert_not_called()
 def test_signed_readout_failure_after_stop_never_transfers(self):
  self.signed.side_effect=[({},None),CutoverBlocked("SIGNED_ACCOUNT_UNAVAILABLE")]
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=True,approved_account_digest=self.approved_digest)
  self.assertEqual(out["state"],"BLOCKED")
  self.assertEqual(out["reason"],"SIGNED_ACCOUNT_UNAVAILABLE")
  self.assertFalse(self.running)
  self.transferred.assert_not_called()
  # Caller parent restarts the original worker while its owner is V1.
 def test_actual_writer_lock_and_broker_recheck_before_transfer(self):
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=True,approved_account_digest=self.approved_digest)
  self.assertEqual(out["state"],"TRANSFERRED")
  self.assertFalse(self.running)
  self.assertEqual(self.signed.call_count,2)
  self.assertEqual(self.preflight.call_count,2)
  self.scope.assert_called_once()
  args,kwargs=self.transferred.call_args
  proof=kwargs["proof"]
  self.assertTrue(proof.old_worker_stopped)
  self.assertTrue(proof.operator_confirmed)
  self.assertTrue(proof.valid("robinhood_crypto","rh1","V1","V2",proof.checked_at))
  doc=json.loads((self.root/"v2/cutover_robinhood/health.json").read_text())
  self.assertEqual(doc["state"],"TRANSFERRED")
  self.assertNotIn("rh1",str(doc))
  self.assertEqual((self.root/"v2/cutover_robinhood/health.json").stat().st_mode&0o077,0)
 def test_changed_owner_generation_never_transfers(self):
  @contextmanager
  def changed(*args,**kwargs):
   yield {"generation":"other"}
  self.scope.side_effect=changed
  out=attempt(self.root,stop_v1=self.stop,live_worker_ready=True,
              operator_approved=True,approved_account_digest=self.approved_digest)
  self.assertEqual(out["reason"],"V1_OWNER_GENERATION_CHANGED")
  self.assertTrue(self.running)
  self.transferred.assert_not_called()
