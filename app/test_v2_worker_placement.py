"""V2 account writer ownership must control every legacy worker restart."""
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from trader_v2.worker_placement import v1_worker_placement

class ParentOwnershipPlacementTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_schwab_original_writer_remains_healthy_when_v1_owns_account(self):
        with patch("trader_v2.worker_placement.inspect_ownership",
                   return_value={"owner":"V1"}) as owner:
            decision=v1_worker_placement(self.root,"schwab",
                          config={"live_account_hash":"hash-123"})
        self.assertTrue(decision.may_run)
        self.assertEqual(decision.reason,"V1_EXCLUSIVE_WRITER")
        owner.assert_called_once_with(self.root,"schwab","hash-123")
    def test_schwab_v2_owner_prevents_v1_restart_without_reenabling_v2(self):
        with patch("trader_v2.worker_placement.inspect_ownership",
                   return_value={"owner":"V2"}):
            decision=v1_worker_placement(self.root,"schwab",
                          config={"live_account_hash":"hash-123"})
        self.assertFalse(decision.may_run)
        self.assertEqual(decision.reason,"V2_ACCOUNT_OWNER_NO_V1_RESTART")
        self.assertEqual(decision.v2_scopes,1)
    def test_schwab_missing_ownership_proof_refuses_to_spawn(self):
        with patch("trader_v2.worker_placement.inspect_ownership",
                   side_effect=ValueError("malformed owner")):
            decision=v1_worker_placement(self.root,"schwab",
                          config={"live_account_hash":"hash-123"})
        self.assertFalse(decision.may_run)
        self.assertEqual(decision.reason,"V1_WRITER_OWNERSHIP_UNVERIFIED")
    def test_webull_mixed_stock_v2_and_crypto_v1_keeps_other_scope(self):
        policy={"enabled":True,"trade_stocks":True,"stock_account":"wb-stock",
                "trade_crypto":True,"crypto_account":"wb-crypto"}
        def owner(root,broker,account):
            return {"owner":"V2" if account=="wb-stock" else "V1"}
        with patch("webull_trade_config.read",return_value=policy),patch(
                   "trader_v2.worker_placement.inspect_ownership",
                   side_effect=owner):
            decision=v1_worker_placement(self.root,"webull")
        self.assertTrue(decision.may_run)
        self.assertEqual(decision.reason,"V1_OTHER_ACCOUNT_ONLY")
        self.assertEqual((decision.v1_scopes,decision.v2_scopes),(1,1))
    def test_webull_all_selected_scopes_v2_means_no_v1_worker(self):
        policy={"enabled":True,"trade_stocks":True,"stock_account":"wb-stock",
                "trade_crypto":False,"crypto_account":""}
        with patch("webull_trade_config.read",return_value=policy),patch(
                   "trader_v2.worker_placement.inspect_ownership",
                   return_value={"owner":"V2"}):
            decision=v1_worker_placement(self.root,"webull")
        self.assertFalse(decision.may_run)
        self.assertEqual(decision.reason,"V2_ACCOUNT_OWNER_NO_V1_RESTART")
    def test_webull_invalid_policy_is_fail_closed(self):
        with patch("webull_trade_config.read",side_effect=ValueError("bad")):
            decision=v1_worker_placement(self.root,"webull")
        self.assertFalse(decision.may_run)
        self.assertEqual(decision.reason,"V1_SELECTED_ACCOUNT_UNVERIFIED")
    def test_robinhood_v2_owner_prevents_v1_worker_restarting(self):
        with patch("robinhood_policy.read_policy",return_value={"account":"RH-A"}),patch(
                   "trader_v2.worker_placement.inspect_ownership",
                   return_value={"owner":"V2"}):
            decision=v1_worker_placement(self.root,"robinhood_crypto")
        self.assertFalse(decision.may_run)
    def test_no_selected_robinhood_account_preserves_read_only_monitoring(self):
        with patch("robinhood_policy.read_policy",return_value={"account":None}):
            decision=v1_worker_placement(self.root,"robinhood_crypto")
        self.assertTrue(decision.may_run)
        self.assertEqual(decision.reason,"V1_MONITOR_ONLY_NO_SELECTED_ACCOUNT")
    def test_ownership_unknown_refuses_partial_mixed_webull_worker(self):
        policy={"enabled":True,"trade_stocks":True,"stock_account":"one",
                "trade_crypto":True,"crypto_account":"two"}
        with patch("webull_trade_config.read",return_value=policy),patch(
                   "trader_v2.worker_placement.inspect_ownership",
                   side_effect=[{"owner":"V1"},{"owner":"UNKNOWN"}]):
            decision=v1_worker_placement(self.root,"webull")
        self.assertFalse(decision.may_run)
        self.assertEqual(decision.reason,"V1_WRITER_OWNERSHIP_UNVERIFIED")
    def test_existing_v1_account_writer_lock_cannot_be_forged_by_a_worker(self):
        from trader_v2.writer_ownership import account_writer_scope, WriterOwnershipError
        # First create a real, private ownership record via the tested V2
        # transfer lock, then ensure a V1 order writer can't enter.
        from trader_v2.writer_ownership import _paths
        import json
        lock,record,digest=_paths(self.root,"schwab","hash-A")
        record.write_text(json.dumps({"schema":1,"broker":"schwab",
            "account_digest":digest,"owner":"V2","generation":"signed-generation"}))
        record.chmod(0o600)
        decision=v1_worker_placement(self.root,"schwab",
                          config={"live_account_hash":"hash-A"})
        self.assertFalse(decision.may_run)
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,"schwab","hash-A",owner="V1"):
                pass
