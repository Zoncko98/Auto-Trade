"""V2 legacy order journals are strictly observational and untrusted as broker proof."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import sqlite3
import unittest

from trader_v2.legacy_journal_audit import observe_legacy_journal
from trader_v2.cutover_preflight import preflight


class LegacyJournalEvidence(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.accounts=[
            {"broker":name,"auth":"CONNECTED","worker_state":"ONLINE",
             "read_verified":True,"permission_armed":True}
            for name in ("schwab","webull","robinhood_crypto","paper")
        ]
        self.market={name:{"state":"FRESH_EXTERNAL_SIGNAL_ONLY"}
                     for name in ("schwab","webull","robinhood_crypto","paper")}

    def _robin(self, orders):
        path=self.root/"robinhood/order_intents.json"
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        path.write_text(json.dumps({"version":1,"orders":orders}))
        path.chmod(0o600)
        return path

    def _webull(self, rows=None):
        path=self.root/"webull/orders.sqlite3"
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE orders(
               client_id TEXT, account TEXT, symbol TEXT, asset TEXT,
               side TEXT, quantity TEXT, limit_price TEXT,
               status TEXT, created_at TEXT, checked_at TEXT,
               filled_qty TEXT, filled_price TEXT, fee TEXT, fill_at TEXT,
               broker_id TEXT, broker_status TEXT, error_category TEXT,
               rationale TEXT)""")
            for i,row in enumerate(rows or []):
                base=["abcd"+str(i),"acct-A","AAPL","EQUITY","BUY","2","10",
                      "FILLED","2026-11-21T13:00:00+00:00",None,
                      "2","10","0.01","2026-11-21T13:00:05+00:00",
                      "broker-1","FILLED",None,"test"]
                for key,value in row.items():
                    names=["client_id","account","symbol","asset","side","quantity",
                        "limit_price","status","created_at","checked_at","filled_qty",
                        "filled_price","fee","fill_at","broker_id","broker_status",
                        "error_category","rationale"]
                    base[names.index(key)]=value
                db.execute("INSERT INTO orders VALUES("+",".join("?" for _ in base)+")",base)
        path.chmod(0o600)
        return path

    def _rh_order(self, **updates):
        row={"account":"crypto-A","client_order_id":"rh-123","symbol":"BTC-USD",
             "side":"buy","quantity":"0.05","limit_price":"100",
             "status":"filled","filled_quantity":"0.05",
             "average_fill_price":"98","fee_charged":"0.05",
             "broker_order_id":"broker-42"}
        row.update(updates)
        return row

    def test_missing_does_not_create_a_journal(self):
        before=set(self.root.rglob("*"))
        for broker in ("webull","robinhood_crypto"):
            data=observe_legacy_journal(self.root,broker)
            self.assertEqual(data["state"],"JOURNAL_EVIDENCE_UNAVAILABLE")
            self.assertIsNone(data["local_unresolved_count"])
            self.assertFalse(data["broker_reconciliation_verified"])
        self.assertEqual(set(self.root.rglob("*")),before)

    def test_webull_valid_terminal_records_are_only_local_evidence(self):
        path=self._webull([{}])
        original=path.stat().st_mtime_ns
        data=observe_legacy_journal(self.root,"webull")
        self.assertEqual(data["state"],"LOCAL_TERMINAL_RECORDS_ONLY")
        self.assertEqual(data["local_filled_count"],1)
        self.assertEqual(data["local_unresolved_count"],0)
        self.assertEqual(data["local_record_count"],1)
        self.assertEqual(data["accounts_observed"],1)
        self.assertFalse(data["broker_reconciliation_verified"])
        self.assertEqual(path.stat().st_mtime_ns,original)

    def test_webull_partial_terminal_cannot_clears_cutover(self):
        self._webull([{"status":"PARTIAL_TERMINAL","filled_qty":"1"}])
        evidence=observe_legacy_journal(self.root,"webull")
        self.assertEqual(evidence["local_unresolved_count"],1)
        item=preflight(self.root,self.accounts,self.market)["accounts"][1]
        self.assertEqual(item["first_blocker"],"RECONCILIATION_REQUIRED")
        self.assertFalse(item["ready_for_v2_live"])
        self.assertEqual(item["journal"]["local_evidence"]["local_unresolved_count"],1)

    def test_webull_missing_filled_details_blocks_cutover(self):
        self._webull([{"fee":None,"broker_id":None}])
        evidence=observe_legacy_journal(self.root,"webull")
        self.assertEqual(evidence["state"],"LOCAL_FILL_EVIDENCE_INCOMPLETE")
        self.assertGreater(evidence["incomplete_fill_details"],0)
        item=preflight(self.root,self.accounts,self.market)["accounts"][1]
        self.assertEqual(item["first_blocker"],"LOCAL_JOURNAL_VERIFICATION_REQUIRED")

    def test_webull_cross_account_records_not_bound_to_one_account(self):
        self._webull([{},{"account":"acct-B"}])
        evidence=observe_legacy_journal(self.root,"webull")
        self.assertEqual(evidence["accounts_observed"],2)
        self.assertEqual(evidence["account_scope"],"ALL_LOCAL_V1_ACCOUNTS_NOT_V2_BOUND")
        self.assertFalse(evidence["ready_for_v2_live"])

    def test_webull_duplicate_order_id_fails_closed(self):
        self._webull([{},{"client_id":"abcd0"}])
        evidence=observe_legacy_journal(self.root,"webull")
        self.assertEqual(evidence["state"],"JOURNAL_EVIDENCE_UNAVAILABLE")

    def test_webull_corrupt_sqlite_schema_is_not_created_or_migrated(self):
        path=self.root/"webull/orders.sqlite3"
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        path.write_bytes(b"not SQLite")
        path.chmod(0o600)
        evidence=observe_legacy_journal(self.root,"webull")
        self.assertEqual(evidence["state"],"JOURNAL_EVIDENCE_UNAVAILABLE")
        self.assertEqual(path.read_bytes(),b"not SQLite")

    def test_private_webull_file_and_robinhood_symlink(self):
        wb=self._webull([{}])
        wb.chmod(0o644)
        self.assertEqual(observe_legacy_journal(self.root,"webull")["state"],
                         "JOURNAL_EVIDENCE_UNAVAILABLE")
        rh=self._robin([self._rh_order()])
        original=rh.with_suffix(".private")
        rh.rename(original)
        rh.symlink_to(original)
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")["state"],
                         "JOURNAL_EVIDENCE_UNAVAILABLE")

    def test_robinhood_valid_terminal_record_is_not_signed_broker_proof(self):
        self._robin([self._rh_order()])
        result=observe_legacy_journal(self.root,"robinhood_crypto")
        self.assertEqual(result["state"],"LOCAL_TERMINAL_RECORDS_ONLY")
        self.assertEqual(result["local_filled_count"],1)
        self.assertEqual(result["local_unresolved_count"],0)
        self.assertFalse(result["broker_positions_verified"])
        self.assertFalse(result["settled_cash_verified"])
        self.assertFalse(result["broker_reconciliation_verified"])
        self.assertFalse(result["v2_order_authorized"])

    def test_robinhood_undetermined_order_blocks_live_cutover(self):
        self._robin([self._rh_order(status="submitted_unconfirmed",
                                  filled_quantity=None,average_fill_price=None)])
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")[
                          "local_unresolved_count"],1)
        item=preflight(self.root,self.accounts,self.market)["accounts"][2]
        self.assertEqual(item["first_blocker"],"RECONCILIATION_REQUIRED")

    def test_robinhood_filled_without_quantity_not_broker_reconciled(self):
        self._robin([self._rh_order(filled_quantity=None)])
        item=preflight(self.root,self.accounts,self.market)["accounts"][2]
        self.assertEqual(item["journal"]["local_evidence"]["state"],
                         "LOCAL_FILL_EVIDENCE_INCOMPLETE")
        self.assertEqual(item["first_blocker"],"LOCAL_JOURNAL_VERIFICATION_REQUIRED")

    def test_robinhood_duplicate_client_id_or_state_invalid(self):
        self._robin([self._rh_order(),self._rh_order()])
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")[
            "state"],"JOURNAL_EVIDENCE_UNAVAILABLE")
        self._robin([self._rh_order(status="my_fake_filled")])
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")[
            "state"],"JOURNAL_EVIDENCE_UNAVAILABLE")

    def test_robinhood_external_reduction_not_counted_as_bot_fill(self):
        self._robin([self._rh_order(status="externally_reconciled",
                                  side="external_reduction")])
        data=observe_legacy_journal(self.root,"robinhood_crypto")
        self.assertEqual(data["local_filled_count"],0)
        self.assertEqual(data["local_unresolved_count"],0)

    def test_robinhood_rejects_corrupt_or_exposed_document(self):
        p=self._robin([self._rh_order()])
        p.chmod(0o644)
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")[
            "state"],"JOURNAL_EVIDENCE_UNAVAILABLE")
        p.chmod(0o600)
        p.write_text("{}")
        self.assertEqual(observe_legacy_journal(self.root,"robinhood_crypto")[
            "state"],"JOURNAL_EVIDENCE_UNAVAILABLE")

    def test_status_report_never_creates_new_broker_journals(self):
        before=set(self.root.rglob("*"))
        doc=preflight(self.root,self.accounts,self.market)
        self.assertEqual(set(self.root.rglob("*")),before)
        self.assertFalse(doc["live_order_authority"])
        self.assertFalse(doc["automatic_cutover_allowed"])
        self.assertEqual(len(doc["accounts"]),4)


if __name__=="__main__":
    unittest.main()
