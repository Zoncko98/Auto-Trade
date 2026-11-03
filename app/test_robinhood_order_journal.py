import tempfile,unittest
from datetime import datetime,timezone,timedelta
from robinhood_order_journal import OrderJournal,UnreconciledOrder

class JournalTests(unittest.TestCase):
 def test_legacy_orphan_requires_time_and_repeated_authoritative_misses(self):
  with tempfile.TemporaryDirectory() as root:
   j=OrderJournal(root)
   j.record_intent("account1","uuid-old","PENGU-USD","721","0.0069283")
   doc=j.load()
   doc["orders"][0]["created_at"]=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()
   j._save(doc)
   for _ in range(9):
    self.assertFalse(j.reconcile("account1",[]))
    self.assertEqual(len(j.pending()),1)
   self.assertTrue(j.reconcile("account1",[]))
   self.assertFalse(j.pending())
   row=j.load()["orders"][0]
   self.assertEqual(row["status"],"rejected")
   self.assertEqual(row["reconcile_miss_count"],10)
   self.assertIn("No Robinhood order found",row["submission_error"])
 def test_intent_persists_and_blocks_duplicates(self):
  with tempfile.TemporaryDirectory() as root:
   j=OrderJournal(root)
   j.record_intent("account1","uuid1","BTC-USD","0.001","50000")
   self.assertEqual(len(OrderJournal(root).pending()),1)
   with self.assertRaises(UnreconciledOrder):
    j.record_intent("account1","uuid2","BTC-USD","0.001","50000")
   self.assertFalse(j.reconcile("account1",[]))
   self.assertTrue(j.reconcile("account1",[{"client_order_id":"uuid1","state":"filled","filled_asset_quantity":"0.001",
     "average_price":"50000","fee_charged":"0.01","updated_at":"2026-11-03T00:00:00Z"}]))
   self.assertFalse(j.pending())
   pos=j.positions()["BTC-USD"]
   self.assertEqual(str(pos["quantity"]),"0.001")
   self.assertTrue(pos["cost_basis_verified"])
