"""Legacy broker endpoints refuse duplicate writes after V2 ownership transfer."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
import json
from trader_v2.writer_ownership import _paths
from robinhood_order_pass import submit_approved,submit_sell_approved,OrderPassBlocked
from robinhood_order_journal import OrderJournal
from webull_journal import WebullJournal
from webull_worker import _order,WebullBlocked

class LegacyWriterTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def transfer_fixture(self,broker,account):
        # Simulated V2 ownership for an isolated test only, not migration API.
        _,path,digest=_paths(self.root,broker,account)
        path.write_text(json.dumps({
            "schema":1,"broker":broker,"account_digest":digest,
            "owner":"V2","generation":"test-handoff-1"}))
        path.chmod(0o600)
        return path
    def test_robinhood_buy_owner_v2_denies_before_intent_and_broker_post(self):
        self.transfer_fixture("robinhood_crypto","acc1")
        broker=Mock()
        prepared={"account":"acc1","symbol":"BTC-USD",
                  "quantity":"0.1","limit_price":"10"}
        with patch("robinhood_order_pass.review_order",return_value=prepared):
            with self.assertRaisesRegex(OrderPassBlocked,"OWNERSHIP"):
                submit_approved(self.root,broker,{"account":"acc1"},None)
        broker.submit_order.assert_not_called()
        self.assertEqual(OrderJournal(self.root).load()["orders"],[])
    def test_robinhood_sell_owner_v2_denies_before_intent_and_broker_post(self):
        self.transfer_fixture("robinhood_crypto","acc1")
        broker=Mock()
        prepared={"account":"acc1","symbol":"BTC-USD",
                  "quantity":"0.1","limit_price":"10"}
        with patch("robinhood_order_pass.review_sell",return_value=prepared):
            with self.assertRaisesRegex(OrderPassBlocked,"OWNERSHIP"):
                submit_sell_approved(self.root,broker,{"account":"acc1"},None)
        broker.submit_order.assert_not_called()
        self.assertEqual(OrderJournal(self.root).load()["orders"],[])
    def test_robinhood_default_v1_owner_still_submits_once(self):
        broker=Mock()
        broker.submit_order.return_value={"id":"accepted-id"}
        prepared={"account":"acc1","symbol":"BTC-USD",
                  "quantity":"0.1","limit_price":"10"}
        with patch("robinhood_order_pass.review_order",return_value=prepared):
            result=submit_approved(self.root,broker,{"account":"acc1"},None)
        self.assertTrue(result["broker_acknowledged"])
        broker.submit_order.assert_called_once()
        self.assertEqual(OrderJournal(self.root).pending()[0]["status"],
                         "submitted_unconfirmed")
    def test_webull_owner_v2_blocks_before_intent_and_place(self):
        self.transfer_fixture("webull","stock1")
        broker=Mock()
        broker.quote.return_value={"symbol":"F","bid":"9.99",
                                  "ask":"10","quote_time":int(datetime.now(timezone.utc).timestamp()*1000)}
        broker.preview.return_value={"success":True}
        risk={"saved":True}
        signal={"at":datetime.now(timezone.utc).isoformat(),"symbol":"F",
                "asset":"EQUITY","ask":"10","bid":"9.99",
                "technical_approved":True,"ai_approved":True}
        journal=WebullJournal(self.root)
        with patch("webull_worker._live_gate",return_value={}),patch(
               "webull_worker._quote",return_value=(D("9.99"),D("10"),D("0.01"))):
            with self.assertRaisesRegex(WebullBlocked,"OWNERSHIP"):
                _order(self.root,broker,{"enabled":True},risk,journal,
                    "stock1","F","EQUITY","BUY",signal,D("1"),D("10"),"test")
        broker.place.assert_not_called()
        self.assertEqual(journal.recent(),[])
    def test_webull_default_v1_owner_still_places_after_valid_checks(self):
        broker=Mock()
        broker.quote.return_value={"symbol":"F","bid":"9.99",
                                  "ask":"10","quote_time":int(datetime.now(timezone.utc).timestamp()*1000)}
        broker.preview.return_value={"success":True}
        broker.place.return_value={"orders":[{"status":"SUBMITTED"}]}
        signal={"at":datetime.now(timezone.utc).isoformat(),"symbol":"F",
                "asset":"EQUITY","ask":"10","bid":"9.99",
                "technical_approved":True,"ai_approved":True}
        journal=WebullJournal(self.root)
        with patch("webull_worker._live_gate",return_value={}),patch(
               "webull_worker._quote",return_value=(D("9.99"),D("10"),D("0.01"))):
            result=_order(self.root,broker,{"enabled":True},{"saved":True},journal,
                    "stock1","F","EQUITY","BUY",signal,D("1"),D("10"),"test")
        self.assertEqual(result["state"],"BROKER_ACKNOWLEDGED_UNFILLED")
        broker.place.assert_called_once()
        self.assertEqual(journal.recent()[0]["status"],"SUBMITTED_UNCONFIRMED")

if __name__=="__main__":main()
