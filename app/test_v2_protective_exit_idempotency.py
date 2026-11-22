"""A fresh quote cannot mint a second order for the same signed bot lot."""
from datetime import datetime,timezone,timedelta
from unittest import TestCase
from trader_v2.engine import candidate_key
from trader_v2.models import Candidate,OrderSide,AssetClass

NOW=datetime(2026,11,23,16,0,tzinfo=timezone.utc)

class ManagedLotIntentIdentityTests(TestCase):
    def candidate(self,when,fingerprint,reason="STOP_LOSS"):
        return Candidate("v1_exit_protection","compat-1","acct",
           "BTC-USD",AssetClass.CRYPTO,OrderSide.SELL,when,{
            "reason":reason,"managed_lot_fingerprint":fingerprint})
    def test_new_signed_quote_does_not_reset_same_protective_order_intent(self):
        initial=self.candidate(NOW,"a"*64)
        later=self.candidate(NOW+timedelta(seconds=20),"a"*64,"TAKE_PROFIT")
        self.assertEqual(candidate_key(initial),candidate_key(later))
    def test_different_signed_lot_requires_new_intent_identity(self):
        a=candidate_key(self.candidate(NOW,"a"*64))
        b=candidate_key(self.candidate(NOW,"b"*64))
        self.assertNotEqual(a,b)
    def test_unknown_lot_or_invalid_identity_does_not_generate_order(self):
        for identifier in ("", "a"*60, "BAD"*21+"x",None):
            with self.subTest(id=str(identifier)[:12]):
                with self.assertRaises(ValueError):
                    candidate_key(self.candidate(NOW,identifier))
    def test_new_entry_id_remains_time_specific(self):
        def entry(at):
            return Candidate("stock_sma","baseline-1","acct",
               "AAPL",AssetClass.STOCK,OrderSide.BUY,at,{"indicator":"SMA"})
        self.assertNotEqual(candidate_key(entry(NOW)),
                            candidate_key(entry(NOW+timedelta(seconds=20))))
