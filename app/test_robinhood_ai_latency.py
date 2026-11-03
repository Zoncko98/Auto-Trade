"""Robinhood AI model routing, response timing, and fail-closed stale-entry review."""
import json,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from local_ai_gateway import _classifier_model,classify_local_news,LocalAIUnavailable
from robinhood_worker import ai_review_category,revalidate_buy_signal
from robinhood_order_pass import OrderPassBlocked

class Response:
    def __init__(self,value):self.value=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,size):return self.value

class TextModelRoutingTests(unittest.TestCase):
    def test_vision_selection_uses_installed_text_classifier(self):
        with patch.dict(os.environ,{},clear=True),patch("local_ai_gateway.installed_models",return_value=["qwen3-vl:8b","qwen3.5:9b"]):
            self.assertEqual(_classifier_model("qwen3-vl:8b"),("qwen3.5:9b","verified_text_fallback"))
    def test_nonvision_keeps_selected_model(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(_classifier_model("deepseek-r1:8b"),("deepseek-r1:8b","selected"))
    def test_missing_text_fallback_fails_closed(self):
        with patch.dict(os.environ,{},clear=True),patch("local_ai_gateway.installed_models",return_value=["qwen3-vl:8b"]):
            with self.assertRaisesRegex(LocalAIUnavailable,"not installed"):
                _classifier_model("qwen3-vl:8b")
    def test_classifier_uses_proven_model_and_warm_keepalive(self):
        posts=[]
        def opener(req,timeout):
            if req.full_url.endswith("/api/tags"):
                return Response({"models":[{"name":"qwen3.5:9b"},{"name":"qwen3-vl:8b"}]})
            assert req.full_url.endswith("/api/chat")
            body=json.loads(req.data)
            posts.append(body)
            return Response({"message":{"content":json.dumps({
                "sentiment":1,"impact":1,"catalyst":"valid headline",
                "downside_risk":"market risk"})}})
        headline={"title":"Bitcoin blockchain release","source":"Publisher",
                  "published_at":"2026-11-03T12:00:00+00:00"}
        with patch("local_ai_gateway._settings",return_value=("http://127.0.0.1:11434","qwen3-vl:8b")):
            result=classify_local_news("BTC-USD",[headline],opener=opener)
        self.assertEqual(result["model"],"local:qwen3.5:9b")
        self.assertEqual(result["classifier_model_source"],"verified_text_fallback")
        self.assertEqual(posts[0]["model"],"qwen3.5:9b")
        self.assertEqual(posts[0]["keep_alive"],"5m")
        self.assertEqual(posts[0]["stream"],False)
        self.assertGreaterEqual(result["inference_seconds"],0)
    def test_empty_model_response_fails_closed(self):
        def opener(req,timeout):
            return Response({"message":{"content":""}})
        headline={"title":"Bitcoin blockchain release","source":"Publisher",
                  "published_at":"2026-11-03T12:00:00+00:00"}
        with patch("local_ai_gateway._settings",return_value=("http://127.0.0.1:11434","qwen3.5:9b")):
            with self.assertRaisesRegex(LocalAIUnavailable,"no classification JSON"):
                classify_local_news("BTC-USD",[headline],opener=opener)

class AIOutcomeTests(unittest.TestCase):
    def test_news_is_not_ai_veto(self):
        self.assertEqual(ai_review_category(False,"AI research unavailable: No headlines explicitly tied to this crypto asset"),
                         "NEWS_EVIDENCE_MISSING")
        self.assertEqual(ai_review_category(False,"AI research unavailable: No independently timestamped news"),
                         "NEWS_EVIDENCE_MISSING")
    def test_ai_and_service_outcomes_distinct(self):
        self.assertEqual(ai_review_category(False,"AI news gate NO TRADE; sentiment=-1"),"AI_NO_TRADE")
        self.assertEqual(ai_review_category(False,"AI research unavailable: Local model returned no classification JSON"),
                         "AI_UNAVAILABLE")
        self.assertEqual(ai_review_category(True,"some reason"),"PASS")

class FreshSignalTests(unittest.TestCase):
    class Broker:
        def __init__(self,bid="9.99",ask="10.00"):self.bid=bid;self.ask=ask
        def quote(self,symbol):return {"results":[{"symbol":symbol,"bid":self.bid,"ask":self.ask}]}
    def prices(self,root,now,values):
        path=Path(root)/"robinhood";path.mkdir(exist_ok=True)
        rows=[{"symbol":"BTC-USD","mid":v,"at":(now-timedelta(seconds=t)).isoformat()}
            for v,t in zip(values,(400,260,130))]
        (path/"quote_history.json").write_text(json.dumps(rows))
    def test_fast_ai_keeps_recent_approved_signal(self):
        now=datetime.now(timezone.utc)
        original={"symbol":"BTC-USD","at":(now-timedelta(seconds=25)).isoformat(),
                  "mid":"9.98","ai_approved":True}
        self.assertIs(revalidate_buy_signal("/does-not-need-history",self.Broker(),original,now),original)
    def test_slow_ai_requires_fresh_broker_technical_confirmation(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            self.prices(root,now,["9.85","9.90","9.94"])
            original={"symbol":"BTC-USD","at":(now-timedelta(seconds=110)).isoformat(),
                "mid":"9.995","source":"ROBINHOOD_POLL_FALLBACK","ai_approved":True}
            result=revalidate_buy_signal(root,self.Broker(),original,now)
            self.assertTrue(result["technical_approved"])
            self.assertTrue(result["ai_approved"])
            self.assertTrue(result["ai_revalidated"])
            self.assertEqual(result["at"],now.isoformat())
    def test_slow_ai_cannot_retimestamp_unqualified_signal(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            self.prices(root,now,["10.20","10.15","10.08"])
            original={"symbol":"BTC-USD","at":(now-timedelta(seconds=110)).isoformat(),
                "mid":"10.12","source":"ROBINHOOD_POLL_FALLBACK","ai_approved":True}
            with self.assertRaisesRegex(OrderPassBlocked,"Signal expired during AI review"):
                revalidate_buy_signal(root,self.Broker(),original,now)
    def test_slow_ai_rejects_large_price_drift_even_with_rising_trend(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            self.prices(root,now,["9.85","9.90","9.94"])
            original={"symbol":"BTC-USD","at":(now-timedelta(seconds=110)).isoformat(),
                "mid":"9.60","source":"ROBINHOOD_POLL_FALLBACK","ai_approved":True}
            with self.assertRaisesRegex(OrderPassBlocked,"price drift"):
                revalidate_buy_signal(root,self.Broker(),original,now)

if __name__=="__main__":unittest.main()
