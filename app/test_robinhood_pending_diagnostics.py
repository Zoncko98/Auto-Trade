import tempfile,unittest
from datetime import datetime,timezone
from broker_workspace import _pending_order_diagnostics,resolve_robinhood_orphan
from robinhood_order_journal import OrderJournal

class FakeClient:
    def __init__(self,orders): self._orders=orders
    def orders(self,account): return list(self._orders)

class PendingDiagnosticsTests(unittest.TestCase):
    def test_pending_intent_exposes_safe_broker_match(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-1","PEPE-USD","100","0.00001")
            rows=_pending_order_diagnostics(root,FakeClient([{
                "id":"broker-1","client_order_id":"client-1","state":"open",
                "created_at":"2026-11-03T04:30:00Z",
                "updated_at":"2026-11-03T04:31:00Z",
                "filled_asset_quantity":"0","average_price":None
            }]))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["symbol"],"PEPE-USD")
            self.assertEqual(rows[0]["side"],"buy")
            self.assertTrue(rows[0]["broker_matched"])
            self.assertEqual(rows[0]["broker_state"],"open")
            self.assertEqual(rows[0]["broker_order_id"],"broker-1")
            self.assertIsInstance(rows[0]["age_seconds"],int)
            self.assertNotIn("account",rows[0])

    def test_pending_intent_reports_no_match_without_clearing(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-2","BTC-USD","0.001","50000")
            rows=_pending_order_diagnostics(root,FakeClient([]))
            self.assertEqual(rows[0]["broker_matched"],False)
            self.assertIn("No matching Robinhood order",rows[0]["broker_lookup_detail"])
            self.assertEqual(len(journal.pending()),1)

    def test_guarded_manual_resolution_requires_repeated_misses_and_fresh_no_match(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-orphan","PENGU-USD","721","0.0069283")
            doc=journal.load()
            doc["orders"][0]["reconcile_miss_count"]=17
            journal._save(doc)
            result=resolve_robinhood_orphan(
                root,{"client_order_id":"client-orphan"},client=FakeClient([]))
            self.assertTrue(result["resolved"])
            self.assertFalse(journal.pending())
            row=journal.load()["orders"][0]
            self.assertEqual(row["status"],"rejected")
            self.assertIn("fresh Robinhood history check",row["submission_error"])

    def test_manual_resolution_refuses_when_broker_now_matches(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-live","PEPE-USD","100","0.00001")
            doc=journal.load()
            doc["orders"][0]["reconcile_miss_count"]=12
            journal._save(doc)
            broker=FakeClient([{"id":"broker-live","client_order_id":"client-live",
                                "state":"open","created_at":"2026-11-03T04:30:00Z"}])
            with self.assertRaisesRegex(ValueError,"Robinhood now reports this order"):
                resolve_robinhood_orphan(
                    root,{"client_order_id":"client-live"},client=broker)
            self.assertEqual(len(journal.pending()),1)

    def test_manual_resolution_refuses_before_ten_misses(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-new","BTC-USD","0.001","50000")
            with self.assertRaisesRegex(ValueError,"At least 10"):
                resolve_robinhood_orphan(
                    root,{"client_order_id":"client-new"},client=FakeClient([]))
            self.assertEqual(len(journal.pending()),1)

    def test_new_intent_records_utc_created_at(self):
        with tempfile.TemporaryDirectory() as root:
            journal=OrderJournal(root)
            journal.record_intent("acct","client-3","ETH-USD","0.01","3000")
            created=journal.pending()[0]["created_at"]
            parsed=datetime.fromisoformat(created)
            self.assertIsNotNone(parsed.tzinfo)
            self.assertLess(abs((datetime.now(timezone.utc)-parsed).total_seconds()),5)

if __name__=="__main__": unittest.main()
