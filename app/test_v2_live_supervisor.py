"""Read-only V2 supervisor cannot activate broker writers."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
from trader_v2.live_supervisor import assess,write_status,public_status
from trader_v2.launch_gates import BROKERS

NOW=datetime(2026,11,22,4,0,tzinfo=timezone.utc)

class SupervisorTests(TestCase):
    def setUp(self):
        self.t=TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
    def test_initial_read_only_observation(self):
        before=list(self.root.iterdir())
        status=assess(self.root,now=NOW)
        self.assertEqual(before,list(self.root.iterdir()))
        self.assertEqual(status["supervisor_state"],"READ_ONLY_STANDBY")
        self.assertFalse(status["v2_live_order_authority"])
        self.assertFalse(status["replacement_live_worker_registered"])
        self.assertEqual(status["v2_orders_submitted"],0)
        self.assertEqual({x["broker"] for x in status["accounts"]},set(BROKERS))
        self.assertTrue(all(not x["cutover_ready"] for x in status["accounts"]))
    def test_private_status_only_and_offline_on_expiry(self):
        write_status(self.root,now=NOW)
        path=self.root/"v2/live_supervisor/health.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode&0o077,0)
        self.assertEqual(path.parent.stat().st_mode&0o077,0)
        public=public_status(self.root,now=NOW)
        self.assertEqual(public["state"],"READ_ONLY_STANDBY")
        self.assertFalse(public["v2_live_order_authority"])
        self.assertEqual(public["cutover_accounts"],0)
        self.assertEqual(public_status(self.root,now=NOW+timedelta(minutes=4))["state"],"OFFLINE_OR_STALE")
    def test_tampered_report_cannot_enable_live_execution(self):
        write_status(self.root,now=NOW)
        p=self.root/"v2/live_supervisor/health.json"
        doc=json.loads(p.read_text())
        doc["v2_live_order_authority"]=True
        p.write_text(json.dumps(doc))
        self.assertEqual(public_status(self.root,now=NOW)["state"],"OFFLINE_OR_STALE")
        doc["v2_live_order_authority"]=False
        doc["accounts"][0]["verified_gate_count"]=99
        p.write_text(json.dumps(doc))
        self.assertEqual(public_status(self.root,now=NOW)["state"],"INVALID_REPORT")
    def test_signed_inherited_counts_are_redacted_not_account_metadata(self):
        from trader_v2.v1_order_inheritance import InheritedOrderLimits
        inherited=InheritedOrderLimits("robinhood_crypto","private-account",2,1,
                   frozenset({"BTC-USD"}),False,True,True)
        with patch("robinhood_policy.read_policy",
                   return_value={"account":"private-account"}),patch(
             "trader_v2.live_supervisor.read_inherited",return_value=inherited):
            doc=write_status(self.root,now=NOW)
        row=next(x for x in doc["accounts"] if x["broker"]=="robinhood_crypto")
        self.assertEqual(row["inherited_v1_limits"]["state"],"SIGNED_V1_LIMITS_INHERITED")
        public=public_status(self.root,now=NOW)
        record=next(x for x in public["accounts"] if x["broker"]=="robinhood_crypto")
        self.assertTrue(record["v1_daily_limits_inherited"])
        self.assertEqual((record["v1_entries_today"],record["v1_exits_today"]),(2,1))
        self.assertNotIn("private-account",str(public))
        self.assertFalse(record.get("v2_live_order_authority",False))

    def test_no_broker_signed_proof_never_reports_positive_v1_counts(self):
        public=write_status(self.root,now=NOW)
        for item in public["accounts"]:
            self.assertEqual(item["inherited_v1_limits"]["state"],
                             "V1_DAILY_LIMITS_NOT_VERIFIED")
            self.assertIsNone(item["inherited_v1_limits"]["entries_today"])

    def test_recent_v1_heartbeat_is_not_writer_handoff(self):
        live=self.root/"live"
        live.mkdir(mode=0o700)
        f=live/"worker_heartbeat.json"
        f.write_text(json.dumps({"at":NOW.isoformat(),"armed":True,"mode":"running"}))
        f.chmod(0o600)
        doc=assess(self.root,now=NOW)
        row=next(x for x in doc["accounts"] if x["broker"]=="schwab")
        self.assertEqual(row["v1_worker"]["state"],"RECENT_V1_TELEMETRY")
        self.assertFalse(row["v2_live_order_authority"])
        self.assertFalse(row["cutover_ready"])
