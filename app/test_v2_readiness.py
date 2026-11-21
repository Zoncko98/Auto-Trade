"""V2 account readiness uses only authenticated, verified read-only observations."""
from pathlib import Path
import unittest
from trader_v2.readiness import explain,GATES

class ReadinessExplainerTests(unittest.TestCase):
    def row(self, broker="webull", **kw):
        x={"broker":broker,"auth":"CONNECTED","worker_state":"ONLINE",
           "read_verified":True,"permission_armed":True,
           "reason_code":"AUTHENTICATED_WORKER_ACCOUNT_AND_BALANCE"}
        x.update(kw)
        return x
    def test_revoked_schwab_is_actionable_and_not_claimed_ready(self):
        row=self.row("schwab",auth="REAUTH_REQUIRED",worker_state="OFFLINE",
                     read_verified=False,permission_armed=True)
        e=explain([row],{"schwab":{"state":"NO_FRESH_QUOTE"}})[0]
        self.assertEqual(e["first_issue"],"SCHWAB_REAUTH_REQUIRED")
        self.assertEqual(e["classification"],"BLOCKED")
        self.assertEqual(e["gates"]["operator_permission"],"CONFIGURED")
        self.assertIn("Reconnect Schwab",e["user_action"])
        self.assertEqual(e["execution_path"],"V2_READ_ONLY_NO_ORDER_AUTHORITY")
        self.assertEqual(e["gates"]["technical_signal"],"NOT_VERIFIED")
    def test_connected_broker_is_not_claimed_order_ready(self):
        e=explain([self.row()],{"webull":{"state":"QUOTE_UNVERIFIED"}})[0]
        self.assertEqual(e["first_issue"],"V2_MARKET_EXECUTION_UNVERIFIED")
        self.assertEqual(e["classification"],"NOT_VERIFIED")
        self.assertEqual(e["gates"]["authentication"],"PASS")
        self.assertEqual(e["gates"]["order_reconciliation"],"NOT_VERIFIED")
    def test_external_crypto_quotes_are_not_executable(self):
        e=explain([self.row("robinhood_crypto")],
                  {"robinhood_crypto":{"state":"FRESH_EXTERNAL_SIGNAL_ONLY",
                                       "symbols":46}})[0]
        self.assertEqual(e["first_issue"],"V2_DATA_ONLY")
        self.assertEqual(e["gates"]["market_data"],"OBSERVED_NON_EXECUTABLE")
        self.assertIsNone(e["last_verified_scan"])
    def test_disarmed_policy_remains_blocked(self):
        e=explain([self.row(permission_armed=False)],
                  {"webull":{"state":"FRESH_READ_ONLY"}})[0]
        self.assertEqual(e["first_issue"],"BROKER_NOT_ARMED")
        self.assertEqual(e["gates"]["operator_permission"],"BLOCKED")
    def test_paper_does_not_infer_live_permission(self):
        e=explain([self.row("paper",worker_state="PAPER_ONLY",
                            permission_armed=False)],{"paper":{"state":"RECORDED_CANDLES_ONLY"}})[0]
        self.assertEqual(e["gates"]["operator_permission"],"NOT_VERIFIED")
        self.assertEqual(e["first_issue"],"V2_MARKET_EXECUTION_UNVERIFIED")
    def test_invalid_rows_cannot_inject_labels(self):
        rows=[self.row("webull"),self.row("webull"),self.row("strange"),{},
              {"broker":["not hashable"]}]
        # Invalid source structures are ignored with bounded output.
        self.assertEqual(len(explain(rows,{})),1)
    def test_fixed_gate_names(self):
        result=explain([self.row()],{})[0]
        self.assertEqual(set(result["gates"]),set(GATES))
        self.assertEqual(result["gates"]["ai_review"],"NOT_VERIFIED")
        self.assertEqual(result["gates"]["risk"],"NOT_VERIFIED")
