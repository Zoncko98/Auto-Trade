"""Schwab fail-closed restart and recovery tests; no broker or live orders."""
import json,os,stat,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import live_worker,unified_runtime
from live_order_safety import LiveBlocked

class SafeLiveRestart(unittest.TestCase):
 def doc(self,dir,orders=None,halted=False):
  root=Path(dir)/"live";root.mkdir(exist_ok=True)
  path=root/"orders.json"
  path.write_text(json.dumps({"version":1,"halted":halted,"orders":orders if orders is not None else []}))
  return path
 def test_only_completed_journal_can_relaunch_worker(self):
  with tempfile.TemporaryDirectory() as t:
   self.assertFalse(unified_runtime.live_journal_safe_for_restart(t)[0])
   p=self.doc(t,[{"state":"FILLED"},{"state":"CANCELED"},{"state":"REJECTED"}])
   self.assertTrue(unified_runtime.live_journal_safe_for_restart(t)[0])
   self.doc(t,[{"state":"FILLED"},{"state":"ACCEPTED"}])
   self.assertEqual(unified_runtime.live_journal_safe_for_restart(t),
                    (False,"BROKER_ORDER_RECONCILIATION_REQUIRED"))
   self.doc(t,[],True)
   self.assertFalse(unified_runtime.live_journal_safe_for_restart(t)[0])
   p.write_text("{garbled")
   self.assertFalse(unified_runtime.live_journal_safe_for_restart(t)[0])
 def test_supervisor_status_is_owner_only_and_deduplicated(self):
  with tempfile.TemporaryDirectory() as t,patch.object(unified_runtime,"STATE",Path(t)):
   unified_runtime.live_supervisor_event("RECOVERING","ALL_BROKER_ORDERS_TERMINAL",1,2)
   p=Path(t)/"live"/"supervisor_status.json"
   self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
   before=p.stat().st_mtime_ns
   unified_runtime.live_supervisor_event("RECOVERING","ALL_BROKER_ORDERS_TERMINAL",1,2)
   self.assertEqual(p.stat().st_mtime_ns,before)
   data=json.loads(p.read_text())
   self.assertEqual(data["state"],"RECOVERING")
   self.assertEqual(data["recovery_attempts_last_hour"],1)

class RecoverableBlock(unittest.TestCase):
 class StopScan(Exception):pass
 def invoke(self,journal):
  with tempfile.TemporaryDirectory() as t,patch.object(live_worker,"STATE_DIR",Path(t)),patch.object(
       live_worker,"JOURNAL",Path(t)/"orders.json"),patch.dict(os.environ,
       {"LIVE_MODE":"AUTONOMOUS","LIVE_TRADING":"true","LIVE_ACCOUNT_HASH":"demo"}),patch.object(
       sys,"argv",["live_worker","--run"]),patch.object(live_worker,"broker",return_value=MagicMock()),patch.object(
       live_worker,"confirm_account",return_value=None),patch.object(
       live_worker.OrderLedger,"open",return_value=journal),patch.object(
       live_worker,"operator_mode",return_value="running"),patch.object(
       live_worker,"attempt",side_effect=LiveBlocked("Market candles missing or stale")) as scan,patch.object(
       live_worker,"write_heartbeat") as beat,patch.object(
       live_worker.time,"sleep",side_effect=self.StopScan):
   try:
    live_worker.main()
   except self.StopScan:
    return "RETRIED",scan.call_count,[c.args for c in beat.call_args_list]
   except LiveBlocked:
    return "BLOCKED",scan.call_count,[c.args for c in beat.call_args_list]
   raise AssertionError("unexpected worker exit")
 def test_transient_preorder_market_failure_keeps_monitoring_without_orders(self):
  journal=MagicMock()
  journal.data={"halted":False,"orders":[]}
  mode,calls,heartbeats=self.invoke(journal)
  self.assertEqual(mode,"RETRIED")
  self.assertEqual(calls,1)
  self.assertIn((False,"running"),heartbeats)
  self.assertEqual(journal.data["orders"],[])
 def test_ambiguous_broker_order_stops_recovery(self):
  journal=MagicMock()
  journal.data={"halted":False,"orders":[{"state":"ACCEPTED"}]}
  mode,calls,heartbeats=self.invoke(journal)
  self.assertEqual(mode,"BLOCKED")
  self.assertEqual(calls,1)
if __name__=="__main__":unittest.main()
