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
if __name__=="__main__": unittest.main()
