"""Synthetic NAS-only/selected-provider forecast regression tests."""
import json,math,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from built_in_forecast import analyze,build,history,MarketHistoryUnavailable
from forecast_engine import connection
from forecast_ai_review import review,ReviewUnavailable

NOW=datetime(2026,10,31,12,tzinfo=timezone.utc)
def bars(price=10,vol=350000,n=160):
    start=NOW.date()-timedelta(days=n+1)
    return [{"date":(start+timedelta(days=i)).isoformat(),
      "close":float(price*(1+(i/n)*0.09)),
      "volume":float(vol)} for i in range(n+2)]

class Resp:
    def __init__(self,payload):self.payload=json.dumps(payload).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.payload[:n]

class BuiltInForecastTests(unittest.TestCase):
    def test_screen_ranking_and_deterministic_risk_levels(self):
        good=bars()
        got=analyze("F",good,"Synthetic daily chart",NOW)
        self.assertEqual(got["ticker"],"F")
        self.assertTrue(got["technical"]["above_sma20"])
        self.assertIsNone(got["historical_volatility_scenario"]["calibrated_probability"])
        self.assertEqual(got["entry_scenario"]["execution_authorized"],False)
        self.assertIsNone(analyze("F",bars(price=3),"Synthetic",NOW))
        self.assertIsNone(analyze("F",bars(vol=500),"Synthetic",NOW))
        self.assertIsNone(analyze("F",good[:-10],"Synthetic",NOW))
    def test_no_ai_provider_needed_for_market_analysis(self):
        def fake_history(sym):
            return bars(),"Synthetic observed data"
        out=build(now=NOW,fetcher=fake_history,config={"ai_provider":"none"},universe=("F","T"))
        self.assertEqual(out["engine"],"built_in")
        self.assertEqual(out["symbols_with_data"],2)
        self.assertEqual(len(out["candidates"]),2)
        self.assertFalse(out["live_order_integration"])
        self.assertTrue(all(x["ai_review_status"]=="not_configured" for x in out["candidates"]))
    def test_optional_review_can_never_modify_ranking(self):
        with patch("ai_research.fetch_headlines",return_value=[{
            "title":"Synthetic dated headline","source":"Test Publisher",
            "published_at":"2026-10-31T10:00:00+00:00"}]):
            config={"ai_provider":"chatgpt-oauth"}
            f=lambda ticker: (bars(),"Synthetic")
            base=build(now=NOW,fetcher=f,config=config,universe=("F",))
            doc=build(now=NOW,fetcher=f,config=config,universe=("F",),
                reviewer=lambda ticker,news,cfg,secrets:{
                    "provider":"chatgpt-oauth","sentiment":2,
                    "impact":2,"catalyst":"Test","downside_risk":"Test"})
        a=base["candidates"][0];b=doc["candidates"][0]
        self.assertEqual(a["ranking_score"],b["ranking_score"])
        self.assertEqual(a["reference_close"],b["reference_close"])
        self.assertEqual(b["ai_review_status"],"completed")
    def test_auto_nas_only_never_requires_specialized_ml(self):
        status=connection({"forecast_mode":"auto","forecast_url":"","ollama_url":"",
            "ai_provider":"gemini-oauth","forecast_ai_review":True})
        self.assertTrue(status["built_in_available"])
        self.assertEqual(status["mode"],"built_in")
        self.assertEqual(status["ai_provider"],"gemini-oauth")
    def test_bounded_ollama_json_review(self):
        headlines=[{"title":"Public synthetic headline","source":"Reporter",
                    "published_at":"2026-10-31T10:00:00Z"}]
        cfg={"ai_provider":"ollama","ollama_url":"http://192.168.1.100:11434",
            "ai_model":"qwen3.5:4b"}
        def opener(req,timeout):
            request=json.loads(req.data)
            self.assertEqual(request["messages"][1]["role"],"user")
            self.assertNotIn("account",request["messages"][1]["content"])
            return Resp({"message":{"content":json.dumps({
                "sentiment":1,"impact":1,"catalyst":"Synthetic",
                "downside_risk":"Synthetic"})}})
        doc=review("SOFI",headlines,cfg,{},opener=opener)
        self.assertEqual(doc["provider"],"ollama")
        self.assertIsNone(doc["calibrated_win_probability"])
    def test_oauth_provider_uses_selected_model_and_companion(self):
        cfg={"ai_provider":"gemini-oauth","oauth_bridge_url":"http://192.168.1.100:8767",
            "oauth_model":"gemini-2.5-flash"}
        headlines=[{"title":"Synthetic","source":"Reporter","published_at":"2026-10-31"}]
        def opener(req,timeout):
            self.assertTrue(req.get_header("Authorization").startswith("Bearer "))
            body=json.loads(req.data)
            self.assertEqual(body["provider"],"gemini-oauth")
            return Resp({"provider":"gemini-oauth","ticker":"SOFI","sentiment":0,
             "impact":0,"catalyst":"None","downside_risk":"Unclear"})
        out=review("SOFI",headlines,cfg,{"oauth_bridge_token":"long-test-bridge-token-example-123"},opener)
        self.assertEqual(out["model"],"gemini-2.5-flash")
    def test_rejects_untrusted_market_numbers_from_provider(self):
        bad=[{"title":"Synthetic","source":"Reporter","published_at":"2026-10-31"}]
        cfg={"ai_provider":"ollama","ollama_url":"http://192.168.1.100:11434","ai_model":"qwen3.5:4b"}
        with self.assertRaises(ReviewUnavailable):
            review("SOFI",bad,cfg,{},lambda req,timeout:Resp({"message":{"content":'{"sentiment":5}'}}))

if __name__=="__main__":unittest.main()
