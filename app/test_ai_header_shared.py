"""Unit tests: header reports effective worker model, not integration fallback."""
import json
import tempfile
import unittest
from pathlib import Path
from ai_readiness import effective_selected_model,verify_ollama_model


class SharedAIModelHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        (self.state/"live").mkdir()
        self.cfg={"ai_provider":"ollama","ai_model":"deepseek-r1:8b",
                  "ollama_url":"http://192.168.1.21:11434"}

    def selection(self,payload):
        target=self.state/"live"/"model_selection.json"
        target.write_text(json.dumps(payload))
        target.chmod(0o600)

    def test_fallback_to_config_when_no_shared_selection(self):
        self.assertEqual(effective_selected_model(self.cfg,self.state),"deepseek-r1:8b")

    def test_shared_selection_overrides_config_default(self):
        self.selection({"version":1,"model":"qwen3.5:4b"})
        self.assertEqual(effective_selected_model(self.cfg,self.state),"qwen3.5:4b")

    def test_invalid_selection_fails_closed_not_to_wrong_model(self):
        for payload in (
            {"version":99,"model":"qwen3.5:4b"},
            {"version":1,"model":"-bad"},
            {"version":1,"model":"bad<script>"},
            {"version":1,"model":""},
            {"version":1},
        ):
            self.selection(payload)
            self.assertEqual(effective_selected_model(self.cfg,self.state),"",payload)

    def test_invalid_json_fails_closed(self):
        target=self.state/"live"/"model_selection.json"
        target.write_text("{bad")
        self.assertEqual(effective_selected_model(self.cfg,self.state),"")

    def test_other_provider_reports_its_own_model_not_ollama_name(self):
        cfg={"ai_provider":"chatgpt-oauth","ai_model":"wrong-default",
             "oauth_model":"gpt-test"}
        self.selection({"version":1,"model":"qwen3.5:4b"})
        self.assertEqual(effective_selected_model(cfg,self.state),"gpt-test")
        cfg["ai_provider"]="none"
        self.assertEqual(effective_selected_model(cfg,self.state),"")

    def test_metadata_verified_is_not_claim_of_inference(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):
                return json.dumps({"models":[{"name":"qwen3.5:4b",
                    "details":{"parameter_size":"4.2B"}}]}).encode()
        model=self.cfg["ai_model"]
        self.selection({"version":1,"model":"qwen3.5:4b"})
        r=verify_ollama_model(self.cfg["ollama_url"],effective_selected_model(self.cfg,self.state),
            opener=lambda req,timeout:Response())
        self.assertEqual(r["model"],"qwen3.5:4b")
        self.assertTrue(r["connection_tested"])
        self.assertFalse(r["capability_tested"])


if __name__=="__main__":unittest.main()
