import unittest
from unified_runtime import build_env,paper_environment
class SharedAIConfigurationTests(unittest.TestCase):
 def test_live_and_paper_ollama_configuration_identical(self):
  cfg={"paper_capital":100,"ai_provider":"ollama",
       "ollama_url":"http://192.168.1.21:11434","ai_model":"qwen3.5:4b"}
  live=build_env(cfg,{})
  paper=paper_environment(live)
  for key in ("AI_PROVIDER","LOCAL_AI_URL","LOCAL_AI_MODEL"):
   self.assertEqual(live[key],paper[key])
  self.assertEqual(paper["AI_PROVIDER"],"local")
