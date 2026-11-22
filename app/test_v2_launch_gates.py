"""TrueNAS broker launch gate refuses source freshness/authority shortcuts."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import json
from trader_v2.launch_gates import launch_status,all_launch_status

NOW=datetime(2026,11,21,23,52,tzinfo=timezone.utc)

class LaunchGateTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def save(self,broker,**overrides):
        p=self.root/"v2"/"broker_migration"/(broker+".json")
        p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        base={"broker":broker,"checked_at":NOW.isoformat(),
            "mode":"AUTHENTICATED_SIGNED_READ_ONLY" if broker=="robinhood_crypto" else "AUTHENTICATED_WEBULL_READ_ONLY",
            "account_verified":True,"holdings_verified":True,
            "broker_history_verified":True,"local_journal_matched":True,
            "broker_open_order_count":0,"local_unresolved_count":0,
            "pairs_checked":2,"quote_timestamp_verified_symbols":1,"signed_last_trade_verified_symbols":1,
            "independent_trade_crosscheck_symbols":1,
            "broker_account_verified":True,"broker_positions_verified":False,
            "settlement_contract_version":2,
            "broker_open_orders_verified":True,"signed_historical_fills_verified":True}
        base.update(overrides)
        p.write_text(json.dumps(base))
        p.chmod(0o600)
        return p

    def test_no_broker_source_never_grants_and_never_writes(self):
        before=list(self.root.rglob("*"))
        result=all_launch_status(self.root,now=NOW)
        self.assertEqual(result["ready_accounts"],0)
        self.assertEqual(len(result["accounts"]),3)
        self.assertTrue(all(not r["live_v2_order_authority"] for r in result["accounts"]))
        self.assertEqual(list(self.root.rglob("*")),before)

    @patch("trader_v2.launch_gates.mapping")
    def test_even_all_signed_probe_flags_cannot_claim_live_without_funding_session_and_worker(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        file=self.save("robinhood_crypto")
        untouched=file.read_bytes()
        result=launch_status(self.root,"robinhood_crypto",now=NOW)
        self.assertTrue(result["signed_observation_fresh"])
        checks={x["name"]:x["verified"] for x in result["gates"]}
        self.assertTrue(checks["SIGNED_ACCOUNT"])
        self.assertTrue(checks["SIGNED_HOLDINGS"])
        self.assertTrue(checks["NO_OPEN_OR_UNRESOLVED_ORDERS"])
        self.assertTrue(checks["V1_SAVED_NUMERIC_RISK"])
        for name in ("SIGNED_SETTLED_FUNDING","SIGNED_MARKET_SESSION",
                     "V1_AI_AND_EXIT_PARITY","V1_WORKER_STOPPED",
                     "V2_SUPERVISOR_AND_RECONCILIATION",
                     "EXCLUSIVE_WRITER_OWNERSHIP"):
            self.assertFalse(checks[name])
        self.assertEqual(result["state"],"BLOCKED")
        self.assertFalse(result["broker_order_submitted"])
        self.assertEqual(untouched,file.read_bytes())

    def test_stale_or_wrong_broker_identity_untrusted(self):
        self.save("robinhood_crypto")
        late=launch_status(self.root,"robinhood_crypto",now=NOW+timedelta(hours=1))
        self.assertEqual(late["first_blocker"],"SIGNED_BROKER_PREFLIGHT_STALE_OR_MISSING")
        path=self.save("robinhood_crypto")
        wrong_source=json.loads(path.read_text())
        wrong_source["broker"]="webull"
        path.write_text(json.dumps(wrong_source))
        wrong=launch_status(self.root,"robinhood_crypto",now=NOW)
        self.assertFalse(wrong["signed_observation_fresh"])

    @patch("trader_v2.launch_gates.mapping")
    def test_webull_verified_settled_cash_never_grants_writer_handoff(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        self.save("webull",broker_positions_verified=True,
                  broker_position_inventory_reconciled=True,
                  settled_cash_verified=True)
        result=launch_status(self.root,"webull",now=NOW)
        checks={row["name"]:row["verified"] for row in result["gates"]}
        self.assertTrue(checks["SIGNED_SETTLED_FUNDING"])
        self.assertFalse(checks["SIGNED_MARKET_SESSION"])
        self.assertFalse(checks["EXCLUSIVE_WRITER_OWNERSHIP"])
        self.assertFalse(result["live_v2_order_authority"])
        self.assertEqual(result["state"],"BLOCKED")

    @patch("trader_v2.launch_gates.mapping")
    def test_webull_structural_positions_without_inventory_match_stay_blocked(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        self.save("webull",broker_positions_verified=True,
                  broker_position_inventory_reconciled=False)
        row=launch_status(self.root,"webull",now=NOW)
        self.assertIn("SIGNED_PORTFOLIO_RECONCILIATION_REQUIRED",row["blockers"])
        self.assertFalse(row["live_v2_order_authority"])

    @patch("trader_v2.launch_gates.mapping")
    def test_open_orders_or_string_zero_are_not_clear(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        self.save("robinhood_crypto",broker_open_order_count="0")
        row=launch_status(self.root,"robinhood_crypto",now=NOW)
        self.assertIn("BROKER_OR_LOCAL_PENDING_ORDERS",row["blockers"])
        self.save("robinhood_crypto",broker_open_order_count=2)
        row=launch_status(self.root,"robinhood_crypto",now=NOW)
        self.assertIn("BROKER_OR_LOCAL_PENDING_ORDERS",row["blockers"])

    @patch("trader_v2.launch_gates.mapping")
    def test_webull_signed_positions_response_is_not_reconciled_inventory(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        self.save("webull")
        row=launch_status(self.root,"webull",now=NOW)
        self.assertIn("SIGNED_PORTFOLIO_RECONCILIATION_REQUIRED",row["blockers"])
        self.assertIn("SIGNED_EXECUTABLE_QUOTE_NOT_VERIFIED",row["blockers"])
        self.assertFalse(row["live_v2_order_authority"])

    @patch("trader_v2.launch_gates.mapping")
    def test_timestamp_alone_cannot_authorize_execution(self,mapping):
        mapping.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
        self.save("robinhood_crypto",
                  quote_timestamp_verified_symbols=2,
                  signed_last_trade_verified_symbols=0,
                  independent_trade_crosscheck_symbols=0)
        row=launch_status(self.root,"robinhood_crypto",now=NOW)
        gates={g["name"]:g["verified"] for g in row["gates"]}
        self.assertFalse(gates["EXECUTABLE_BROKER_QUOTE"])
        self.assertIn("SIGNED_EXECUTABLE_QUOTE_NOT_VERIFIED",row["blockers"])
        self.save("robinhood_crypto",
                  quote_timestamp_verified_symbols=2,
                  signed_last_trade_verified_symbols=1,
                  independent_trade_crosscheck_symbols=0)
        row=launch_status(self.root,"robinhood_crypto",now=NOW)
        gates={g["name"]:g["verified"] for g in row["gates"]}
        self.assertTrue(gates["EXECUTABLE_BROKER_QUOTE"])

    def test_unreadable_or_unknown_source_stays_blocked(self):
        bad=self.save("robinhood_crypto")
        bad.chmod(0o644)
        self.assertFalse(launch_status(self.root,"robinhood_crypto",now=NOW)["signed_observation_fresh"])
        with self.assertRaises(ValueError):
            launch_status(self.root,"alpaca",now=NOW)

if __name__=="__main__":
    main()
