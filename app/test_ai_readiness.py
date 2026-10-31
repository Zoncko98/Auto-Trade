import unittest
from ai_readiness import model_size_billions,summary
class Tests(unittest.TestCase):
 def test_four_b(self):
  x=summary({"ai_provider":"ollama","ai_model":"qwen3.5:4b"})
  self.assertTrue(x["size_claim_meets_minimum"])
  self.assertFalse(x["capability_tested"])
 def test_small(self):
  self.assertFalse(summary({"ai_provider":"ollama","ai_model":"tiny:1.5b"})["size_claim_meets_minimum"])
 def test_unknown(self):
  self.assertIsNone(model_size_billions("custom-model"))
 def test_cloud(self):
  self.assertEqual(summary({"ai_provider":"chatgpt-oauth"})["status"],"needs_runtime_verification")
 def test_no_ai(self):
  self.assertEqual(summary({})["status"],"not_configured")
 def test_authoritative_metadata(self):
  import json
  from ai_readiness import verify_ollama_model
  class Reply:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):return json.dumps({"details":{"parameter_size":"4.7B"}}).encode()
  x=verify_ollama_model("http://192.168.1.2:11434","demo:4b",opener=lambda req,timeout:Reply())
  self.assertEqual(x["status"],"metadata_verified")
  self.assertTrue(x["meets_minimum"])
  self.assertFalse(x["capability_tested"])
 def test_unknown_metadata_fails_closed(self):
  from ai_readiness import verify_ollama_model
  x=verify_ollama_model("http://192.168.1.2:11434","demo",opener=lambda req,timeout:(_ for _ in ()).throw(OSError()))
  self.assertFalse(x["meets_minimum"])
if __name__=="__main__": unittest.main()
