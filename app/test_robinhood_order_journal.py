import tempfile,unittest
from robinhood_order_journal import OrderJournal,UnreconciledOrder

class JournalTests(unittest.TestCase):
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
