"""V2 signed migration evidence expires; a stale cached probe cannot mint authority."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json
from trader_v2.status import summary

class ProbeFreshnessTests(TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.probe=self.root/"v2/broker_migration/robinhood_crypto.json"
  self.probe.parent.mkdir(mode=0o700,parents=True)
  self.probe.parent.chmod(0o700)
 def save(self,dt):
  data={"checked_at":dt.isoformat(),"broker":"robinhood_crypto",
        "account_verified":True,"holdings_verified":True,
        "v2_live_order_authority":False,"cutover_ready":False,
        "first_blocker":"V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED"}
  self.probe.write_text(json.dumps(data))
  self.probe.chmod(0o600)
 def test_fresh_signed_probe_displayed_without_live_authority(self):
  self.save(datetime.now(timezone.utc))
  data=summary(self.root)["robinhood_signed_migration_probe"]
  self.assertTrue(data["report_fresh"])
  self.assertTrue(data["account_verified"])
  self.assertFalse(data["cutover_ready"])
 def test_stale_probe_never_claims_verified_account(self):
  self.save(datetime.now(timezone.utc)-timedelta(hours=1))
  data=summary(self.root)["robinhood_signed_migration_probe"]
  self.assertFalse(data["report_fresh"])
  self.assertEqual(data["first_blocker"],"SIGNED_BROKER_PROBE_STALE_OR_UNAVAILABLE")
  self.assertNotIn("account_verified",data)
 def test_future_probe_cannot_be_fresh(self):
  self.save(datetime.now(timezone.utc)+timedelta(hours=1))
  data=summary(self.root)["robinhood_signed_migration_probe"]
  self.assertFalse(data["report_fresh"])
 def test_no_signed_probe_never_arms(self):
  data=summary(self.root)["robinhood_signed_migration_probe"]
  self.assertFalse(data["cutover_ready"])
  self.assertFalse(data["v2_live_order_authority"])
if __name__=="__main__":main()
