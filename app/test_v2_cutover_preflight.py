"""V2 per-broker read-only migration preflight contract tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
from unittest import TestCase,main
import json,os
from trader_v2.cutover_preflight import preflight

class CutoverTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.market={
          "schwab":{"state":"NO_FRESH_QUOTE"},
          "webull":{"state":"QUOTE_UNVERIFIED"},
          "robinhood_crypto":{"state":"FRESH_EXTERNAL_SIGNAL_ONLY"},
          "paper":{"state":"RECORDED_CANDLES_ONLY"},
        }
    def write(self,name,doc):
        file=self.root/name
        file.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        file.write_text(json.dumps(doc),encoding="utf8")
        file.chmod(0o600)
        return file
    def rows(self,auth="CONNECTED",online=True):
        return [{"broker":b,"auth":auth,"worker_state":"ONLINE" if online else "OFFLINE",
          "read_verified":online,"permission_armed":True} for b in ("schwab","webull","robinhood_crypto","paper")]
    def test_missing_state_never_creates_any_files_or_live_authority(self):
        before=set(self.root.rglob("*"))
        result=preflight(self.root,self.rows(),self.market)
        self.assertEqual(before,set(self.root.rglob("*")))
        self.assertFalse(result["live_order_authority"])
        self.assertFalse(result["automatic_cutover_allowed"])
        self.assertEqual(len(result["accounts"]),4)
        self.assertTrue(all(a["ready_for_v2_live"] is False for a in result["accounts"]))
    def test_schwab_connected_but_v1_worker_active_prevents_cutover(self):
        self.write("live/risk_settings.json",{"version":1,"settings":{
          "max_order_usd":20,"max_daily_loss":5,"max_open_positions":3,
          "strategy_capital_usd":100,"max_orders_per_day":3}})
        self.write("live/orders.json",{"version":1,"halted":False,
          "orders":[{"state":"FILLED"},{"state":"CANCELED"}]})
        r=preflight(self.root,self.rows(),self.market)["accounts"][0]
        self.assertEqual(r["authentication"],"CONNECTED")
        self.assertTrue(r["account_verified"])
        self.assertTrue(r["v1_writer_active"])
        self.assertEqual(r["first_blocker"],"V1_ORDER_WRITER_MUST_BE_PAUSED_FOR_CUTOVER")
        self.assertEqual(r["journal"]["records"],2)
        self.assertEqual(r["journal"]["unresolved"],0)
        self.assertEqual(r["risk"]["limits"]["max_order_usd"],"20")
        self.assertFalse(r["executable_quote_verified"])
        self.assertFalse(r["risk_envelope"]["ready_to_submit"])
        self.assertIsNone(r["risk_envelope"]["preliminary_budget_usd"])
    def test_unresolved_intent_halts_schwab_migration_even_online(self):
        self.write("live/orders.json",{"version":1,"halted":False,
          "orders":[{"state":"FILLED"},{"state":"SUBMITTING"}]})
        r=preflight(self.root,self.rows(),self.market)["accounts"][0]
        self.assertEqual(r["journal"]["unresolved"],1)
        self.assertEqual(r["first_blocker"],"RECONCILIATION_REQUIRED")
    def test_halted_journal_does_not_get_interpreted_as_ready(self):
        self.write("live/orders.json",{"version":1,"halted":True,"orders":[]})
        r=preflight(self.root,self.rows(),self.market)["accounts"][0]
        self.assertEqual(r["journal"]["state"],"HALTED_OR_OVERSIZED")
        self.assertEqual(r["first_blocker"],"RECONCILIATION_REQUIRED")
    def test_revoked_token_priority_remains_broker_auth(self):
        r=preflight(self.root,self.rows(auth="REAUTH_REQUIRED",online=False),self.market)["accounts"][0]
        self.assertEqual(r["first_blocker"],"BROKER_REAUTH_REQUIRED")
        self.assertFalse(r["v1_writer_active"])
    def test_unknown_journal_never_mints_order_completion(self):
        r=preflight(self.root,self.rows(),self.market)["accounts"][0]
        self.assertEqual(r["journal"]["state"],"JOURNAL_UNVERIFIED")
        self.assertIsNone(r["journal"]["unresolved"])
        self.assertEqual(r["first_blocker"],"ORDER_JOURNAL_VERIFICATION_REQUIRED")
    def test_webull_and_robinhood_risk_is_account_specific(self):
        self.write("webull/risk_plan.json",{"settings":{
            "max_order_usd":"25.00","max_open_positions":3,
            "max_total_exposure_usd":"60"}})
        self.write("robinhood/risk_policy.json",{
            "max_order_usd":"13.50","max_daily_loss_usd":"5",
            "max_open_positions":4,"max_total_exposure_usd":"75.00"})
        self.write("webull/worker_status.json",{"reconciliation":{"state":"VERIFIED"}})
        self.write("robinhood/worker_status.json",{"broker_order_history_status":"VERIFIED"})
        result=preflight(self.root,self.rows(),self.market)["accounts"]
        webull,rh=result[1:3]
        self.assertEqual(webull["risk"]["limits"]["max_order_usd"],"25.00")
        self.assertEqual(rh["risk"]["limits"]["max_order_usd"],"13.50")
        self.assertNotEqual(webull["journal"]["state"],"LOCAL_TERMINAL_ONLY")
        self.assertFalse(webull["journal"]["broker_reconciliation_verified"])
        self.assertFalse(rh["journal"]["broker_reconciliation_verified"])
        self.assertEqual(rh["journal"]["state"],"BROKER_HISTORY_OBSERVED_V2_UNVERIFIED")
        self.assertFalse(rh["live_order_authority"])
    def test_invalid_or_public_risk_data_is_not_read_as_a_limit(self):
        f=self.write("robinhood/risk_policy.json",{"max_order_usd":"NaN"})
        r=preflight(self.root,self.rows(),self.market)["accounts"][2]
        self.assertEqual(r["risk"]["state"],"RISK_POLICY_INVALID")
        f.chmod(0o644)
        r=preflight(self.root,self.rows(),self.market)["accounts"][2]
        self.assertEqual(r["risk"]["state"],"RISK_POLICY_UNAVAILABLE")
    def test_simulated_account_does_not_inherit_any_live_authority(self):
        r=preflight(self.root,self.rows(),self.market)["accounts"][3]
        self.assertEqual(r["stage"],"SIMULATED_ONLY")
        self.assertEqual(r["first_blocker"],"NO_LIVE_ADAPTER_BY_DESIGN")
        self.assertFalse(r["v1_writer_active"])
    def test_untrusted_broker_code_cannot_insert_live_ready(self):
        rows=self.rows()
        rows.append({"broker":"arbitrary","auth":"CONNECTED","worker_state":"ONLINE",
                     "read_verified":True})
        result=preflight(self.root,rows,self.market)
        self.assertEqual([x["broker"] for x in result["accounts"]],
                         ["schwab","webull","robinhood_crypto","paper"])
        self.assertTrue(all(not x["ready_for_v2_live"] for x in result["accounts"]))

if __name__=="__main__":main()
