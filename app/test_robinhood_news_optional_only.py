"""No-news Robinhood entries: technical-only authorization, AI unchanged, risk intact."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from robinhood_worker import run_once,ai_review_category,revalidate_buy_signal
from robinhood_order_journal import OrderJournal
from robinhood_order_pass import review_order,OrderPassBlocked

class Broker:
    def __init__(self):
        self.orders_sent=[]
    def list_accounts(self):
        return [{"account_number":"acct","status":"active",
           "is_api_tradable":True,"buying_power":"20",
           "buying_power_currency":"USD"}]
    def quote(self,symbol):
        return {"results":[{"symbol":symbol,"bid":"9.99","ask":"10.00"}]}
    def trading_pairs(self):
        return [{"symbol":"BTC-USD","asset_code":"BTC",
            "quote_code":"USD","is_api_tradable":True,
            "min_order_amount":"1","asset_increment":"0.001",
            "max_order_size":"100"}]
    def orders(self,account):return []
    def positions(self,account):return []
    def submit_order(self,account,intent):
        self.orders_sent.append(dict(intent))
        return {"id":"mock-broker-order-id"}

class NewsOptionalTests(unittest.TestCase):
    def setup_state(self,root,enabled=True,rising=True):
        folder=Path(root)/"robinhood";folder.mkdir()
        (folder/"risk_policy.json").write_text(json.dumps({
            "account":"acct","enabled":enabled,"max_order_usd":"5",
            "max_total_exposure_usd":"35","max_daily_loss_usd":"5",
            "max_open_positions":3,"verified_broker_minimum_usd":"1",
            "max_single_asset_exposure_pct":"60","min_add_interval_minutes":30}))
        now=datetime.now(timezone.utc)
        prices=["9.88","9.92","9.95"] if rising else ["10.15","10.12","10.05"]
        (folder/"quote_history.json").write_text(json.dumps([
            {"symbol":"BTC-USD","mid":mid,
             "at":(now-timedelta(seconds=age)).isoformat()}
            for mid,age in zip(prices,[410,270,135])]))
    def simulate(self,ai_return,enabled=True,rising=True):
        broker=Broker()
        with tempfile.TemporaryDirectory() as root:
            self.setup_state(root,enabled=enabled,rising=rising)
            with patch("ai_research.approve_entry",return_value=ai_return),\
                 patch("ai_research.research_evidence",return_value={}),\
                 patch("local_ai_gateway.installed_models",return_value=["qwen3.5:9b"]),\
                 patch("robinhood_crypto_execution.RobinhoodCryptoTradingAdapter.from_state_authorized",return_value=broker):
                result=run_once(root,broker)
            pending=OrderJournal(root).pending()
        return result,broker.orders_sent,pending
    def test_missing_news_allows_qualified_technical_entry_with_no_ai_approval(self):
        result,orders,pending=self.simulate((False,
            "AI research unavailable: No headlines explicitly tied to this crypto asset"))
        self.assertEqual(result["ai_review_status"],"TECHNICAL_ONLY_NEWS_OPTIONAL")
        self.assertEqual(result["ai_model"],"NOT_INVOKED")
        self.assertEqual(result["ai_candidate_reviews"][0]["review_type"],"TECHNICAL_ONLY_NO_AI")
        self.assertEqual(result["ai_candidate_reviews"][0]["news_status"],"NO_RELEVANT_HEADLINES")
        self.assertIn("technical-only approval",result["execution_reason"])
        self.assertEqual(result["execution_status"],"ORDER_ACCEPTED")
        self.assertEqual(len(orders),1)
        self.assertEqual(orders[0]["side"],"buy")
        self.assertEqual(len(pending),1)
    def test_no_independently_timestamped_headlines_qualifies_as_no_news(self):
        result,orders,_=self.simulate((False,
            "AI research unavailable: No independently timestamped news"))
        self.assertEqual(result["ai_review_status"],"TECHNICAL_ONLY_NEWS_OPTIONAL")
        self.assertEqual(len(orders),1)
    def test_news_feed_failure_does_not_bypass_gate(self):
        result,orders,_=self.simulate((False,
            "AI research unavailable: Recent news unavailable"))
        self.assertEqual(result["ai_review_status"],"NEWS_FEED_UNAVAILABLE")
        self.assertEqual(orders,[])
    def test_explicit_ai_veto_still_blocks(self):
        result,orders,_=self.simulate((False,
            "AI news gate NO TRADE; sentiment=-2, impact=2; catalyst=Market collapse"))
        self.assertEqual(result["ai_review_status"],"AI_NO_TRADE")
        self.assertEqual(orders,[])
    def test_ai_transport_failure_still_blocks(self):
        result,orders,_=self.simulate((False,
            "AI research unavailable: Local model timed out after 150 seconds"))
        self.assertEqual(result["ai_review_status"],"AI_UNAVAILABLE")
        self.assertEqual(orders,[])
    def test_invalid_technical_signal_cannot_use_no_news(self):
        result,orders,_=self.simulate((False,
            "AI research unavailable: No independently timestamped news"),rising=False)
        self.assertEqual(orders,[])
        self.assertEqual(result["ai_review_status"],"NOT_INVOKED_NO_TECHNICAL_CANDIDATE")
    def test_policy_disabled_blocks_even_if_no_news(self):
        result,orders,_=self.simulate((False,
            "AI research unavailable: No independently timestamped news"),enabled=False)
        self.assertEqual(orders,[])
        self.assertIn("BLOCKED",result["execution_status"])
    def test_a_forged_technical_only_flag_is_not_sufficient(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            self.setup_state(root)
            with self.assertRaisesRegex(OrderPassBlocked,"proof incomplete"):
                review_order(root,Broker(),{"account":"acct"},
                    {"symbol":"BTC-USD","at":now.isoformat(),"technical_approved":True,
                     "ai_approved":False,"news_optional_technical_approved":True,
                     "news_evidence_status":"NO_RELEVANT_HEADLINES"},now)
    def test_a_stale_no_news_entry_is_rejected(self):
        now=datetime.now(timezone.utc)
        signal={"symbol":"BTC-USD","at":(now-timedelta(seconds=130)).isoformat(),
            "technical_approved":True,"ai_approved":False,
            "news_optional_technical_approved":True,
            "news_evidence_status":"NO_RELEVANT_HEADLINES",
            "signal":"MOMENTUM_CANDIDATE","trend_up":True,
            "momentum_pct":0.8,"spread_pct":0.1,
            "history_span_seconds":420,"history_points":5}
        with tempfile.TemporaryDirectory() as root:
            self.setup_state(root)
            with self.assertRaisesRegex(OrderPassBlocked,"stale"):
                review_order(root,Broker(),{"account":"acct"},signal,now)
    def test_news_optional_path_does_not_create_ai_approval(self):
        self.assertEqual(ai_review_category(True,
            "TECHNICAL_ONLY_NEWS_OPTIONAL: no headlines"),"TECHNICAL_ONLY_NEWS_OPTIONAL")
    def test_revalidation_preserves_no_news_provenance(self):
        now=datetime.now(timezone.utc)
        signal={"symbol":"BTC-USD","at":(now-timedelta(seconds=1)).isoformat(),
            "technical_approved":True,"ai_approved":False,
            "news_optional_technical_approved":True,
            "news_evidence_status":"NO_RELEVANT_HEADLINES"}
        out=revalidate_buy_signal("/no/history/needed",Broker(),signal,now)
        self.assertIs(out,signal)
        self.assertFalse(out["ai_approved"])

if __name__=="__main__":unittest.main()
