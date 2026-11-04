"""Regression coverage for safe recovery from Schwab DNS/connect failures.

No broker credentials, real API calls or order submissions are used.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import live_worker
from live_order_safety import LiveBlocked


class FakeConnectError(Exception):
    pass


class FakeConnectTimeout(Exception):
    pass


class SchwabDnsRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.ledger=types.SimpleNamespace(data={"halted":False,"orders":[]})
        self.fake_httpx=types.ModuleType("httpx")
        self.fake_httpx.ConnectError=FakeConnectError
        self.fake_httpx.ConnectTimeout=FakeConnectTimeout

    def test_no_ambiguous_order_intent_guard(self):
        good=[{"state":"FILLED"},{"state":"CANCELED"}]
        for rows,halted,expected in (
            ([],False,True),(good,False,True),
            ([{"state":"SUBMITTING"}],False,False),
            ([{"state":"ACCEPTED"}],False,False),
            (good,True,False),
            ([{"bad":1}],False,False),
            (["not a record"],False,False),
        ):
            self.ledger.data={"halted":halted,"orders":rows}
            self.assertEqual(live_worker.no_ambiguous_order_intent(self.ledger),
                             expected,(rows,halted))
        self.ledger.data={"orders":[]}
        self.assertFalse(live_worker.no_ambiguous_order_intent(self.ledger))
        self.ledger.data={"halted":False,"orders":"malformed"}
        self.assertFalse(live_worker.no_ambiguous_order_intent(self.ledger))

    def run_worker_mock(self,args,confirm_effect=None,attempt_effect=None):
        context=[
            patch.dict(sys.modules,{"httpx":self.fake_httpx}),
            patch.dict(os.environ,{"LIVE_MODE":"AUTONOMOUS",
                                   "LIVE_TRADING":"true",
                                   "LIVE_ACCOUNT_HASH":"fake-safe-test-hash"}),
            patch.object(sys,"argv",["live_worker.py",args]),
            patch.object(live_worker,"STATE_DIR",self.folder),
            patch.object(live_worker,"JOURNAL",self.folder/"orders.json"),
            patch.object(live_worker,"broker",return_value=object()),
            patch.object(live_worker,"operator_mode",return_value="running"),
            patch.object(live_worker,"write_heartbeat"),
            patch.object(live_worker.time,"sleep"),
            patch.object(live_worker.OrderLedger,"open",return_value=self.ledger),
            patch.object(live_worker,"confirm_account",side_effect=confirm_effect),
            patch.object(live_worker,"attempt",side_effect=attempt_effect),
        ]
        started=[p.__enter__() for p in context]
        self.addCleanup(lambda: [p.__exit__(None,None,None) for p in reversed(context)])
        return {"sleep":started[8],"confirm":started[10],"attempt":started[11],
                "heartbeat":started[7]}

    def test_dns_failure_before_order_retries_after_heartbeat_backoff(self):
        mocks=self.run_worker_mock("--run",attempt_effect=[
            FakeConnectError("DNS temporary failure"),LiveBlocked("test stop after retry")])
        with self.assertRaisesRegex(LiveBlocked,"test stop after retry"):
            live_worker.main()
        self.assertEqual(mocks["attempt"].call_count,2)
        self.assertEqual(mocks["sleep"].call_count,6)
        self.assertEqual(mocks["heartbeat"].call_count,8)
        self.assertEqual([c.args[0] for c in mocks["heartbeat"].call_args_list],
                         [True]+[False]*6+[True])

    def test_pending_order_forbids_network_retry(self):
        self.ledger.data={"halted":False,"orders":[{"state":"SUBMITTING"}]}
        mocks=self.run_worker_mock("--run",attempt_effect=FakeConnectError("DNS outage"))
        with self.assertRaisesRegex(LiveBlocked,"unresolved order intent"):
            live_worker.main()
        self.assertEqual(mocks["attempt"].call_count,1)
        mocks["sleep"].assert_not_called()

    def test_persistent_halt_forbids_network_retry(self):
        self.ledger.data={"halted":True,"orders":[]}
        mocks=self.run_worker_mock("--run",attempt_effect=FakeConnectError("DNS outage"))
        with self.assertRaisesRegex(LiveBlocked,"unresolved order intent"):
            live_worker.main()
        self.assertEqual(mocks["attempt"].call_count,1)
        mocks["sleep"].assert_not_called()

    def test_account_verification_connect_error_retries_without_orders(self):
        mocks=self.run_worker_mock("--run",
            confirm_effect=[FakeConnectTimeout("DNS"),None],
            attempt_effect=LiveBlocked("test exit before any order"))
        with self.assertRaisesRegex(LiveBlocked,"test exit before any order"):
            live_worker.main()
        self.assertEqual(mocks["confirm"].call_count,2)
        self.assertEqual(mocks["attempt"].call_count,1)
        self.assertEqual(mocks["sleep"].call_count,6)
        self.assertTrue(all(c.args[0] is False
            for c in mocks["heartbeat"].call_args_list[:6]))

    def test_read_only_check_fails_closed_on_dns_error(self):
        mocks=self.run_worker_mock("--check",confirm_effect=FakeConnectError("DNS"))
        with self.assertRaisesRegex(LiveBlocked,"temporarily unavailable"):
            live_worker.main()
        mocks["sleep"].assert_not_called()
        mocks["attempt"].assert_not_called()

    def test_non_transient_exception_never_retries(self):
        mocks=self.run_worker_mock("--run",attempt_effect=ValueError("unrecognized failure"))
        with self.assertRaisesRegex(ValueError,"unrecognized failure"):
            live_worker.main()
        mocks["sleep"].assert_not_called()
        self.assertEqual(mocks["attempt"].call_count,1)


if __name__=="__main__":
    unittest.main()
