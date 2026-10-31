import tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from paper_market_data import recent_quote,append_new_quotes,poll
from unified_runtime import paper_environment
from ai_review import OllamaReviewer

class PaperFeedTests(unittest.TestCase):
 def test_paper_only_ollama_endpoint(self):
  original={"AI_PROVIDER":"ollama","AI_OLLAMA_URL":"http://192.168.1.43:11434","AI_MODEL":"qwen3.5:4b"}
  result=paper_environment(original)
  self.assertEqual(original["AI_OLLAMA_URL"],"http://192.168.1.43:11434")
  self.assertEqual(result["AI_OLLAMA_URL"],"http://192.168.1.43:11434/api/generate")
  self.assertIn("BTCUSD",result["PAPER_SYMBOLS"])
  self.assertEqual(result["AI_REVIEW_TIMEOUT_SECONDS"],"18")
  self.assertTrue(OllamaReviewer(result["AI_OLLAMA_URL"],result["AI_MODEL"]))
 def test_missing_endpoint_does_not_crash_worker(self):
  result=paper_environment({"AI_PROVIDER":"none","AI_OLLAMA_URL":"","AI_MODEL":"qwen3.5:4b"})
  self.assertEqual(result["AI_MODEL"],"")
  self.assertTrue(OllamaReviewer(result["AI_OLLAMA_URL"],result["AI_MODEL"]))
 def test_closed_crypto_bar_uses_original_timestamp(self):
  now=datetime(2026,10,31,20,tzinfo=timezone.utc)
  def fetch(url):
   return {"error":[],"result":{"XXBTZUSD":[
    [int((now-timedelta(minutes=2)).timestamp()),"1","2","3","101","4"],
    [int(now.timestamp()),"1","2","3","999","4"]],"last":99}}
  v=recent_quote("BTCUSD",now,getter=fetch)
  self.assertEqual(v["price"],101)
  self.assertEqual(v["timestamp"],(now-timedelta(minutes=2)).isoformat())
 def test_equity_stale_rejected(self):
  now=datetime(2026,10,31,20,tzinfo=timezone.utc)
  def fetch(url):
   return {"chart":{"result":[{"timestamp":[int((now-timedelta(hours=1)).timestamp())],
      "indicators":{"quote":[{"close":[550]}]}}]}}
  with self.assertRaises(ValueError):recent_quote("SPY",now,getter=fetch)
 def test_csv_deduplicates_and_keeps_same_account_feed(self):
  now=datetime(2026,10,31,20,tzinfo=timezone.utc)
  row={"timestamp":now.isoformat(),"symbol":"BTCUSD","price":100.}
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"prices.csv"
   self.assertEqual(append_new_quotes(path,[row]),1)
   self.assertEqual(append_new_quotes(path,[row]),0)
   self.assertEqual(poll(path,{"BTCUSD"},now,quote=lambda symbol,now:row)["added"],0)
   self.assertEqual(len(path.read_text().splitlines()),2)
if __name__=="__main__":unittest.main()
