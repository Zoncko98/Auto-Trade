"""Cloud AI adapter tests: no external provider calls are made."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_models import (
    CloudReviewRouter, _model_request, _parse_model_decision,
    default_cloud_config, read_cloud_config, read_cloud_keys,
    set_cloud_key, validate_cloud_config, valid_azure_endpoint,
)


class CloudConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_default_cloud_is_disabled(self):
        c=read_cloud_config(self.root/"no-file.json")
        self.assertFalse(c["enabled"])
        self.assertEqual(c["mode"],"single")

    def test_secret_storage_roundtrip(self):
        f=self.root/"secrets.json"
        self.assertTrue(set_cloud_key(f,"openai","sk-test-fake-key-value"))
        self.assertEqual(read_cloud_keys(f)["openai"],"sk-test-fake-key-value")
        self.assertEqual(f.stat().st_mode & 0o777,0o600)
        self.assertFalse(set_cloud_key(f,"openai",None))
        self.assertFalse(read_cloud_keys(f))

    def test_api_key_never_leaks_into_config(self):
        cfg=default_cloud_config()
        self.assertNotIn("api_key",json.dumps(cfg))
        self.assertEqual(validate_cloud_config(cfg)["enabled"],False)

    def test_reject_missing_pricing_or_models(self):
        cfg=default_cloud_config()
        cfg["enabled"]=True
        cfg["providers"]["openai"]["enabled"]=True
        with self.assertRaises(ValueError):
            validate_cloud_config(cfg)

    def test_reject_insufficient_voters(self):
        cfg=default_cloud_config()
        cfg["enabled"]=True
        cfg["mode"]="consensus"
        cfg["required_approvals"]=2
        cfg["providers"]["openai"].update({
            "enabled":True, "model":"test-model",
            "input_usd_per_million":0.25,
            "output_usd_per_million":2.0,
        })
        with self.assertRaises(ValueError):
            validate_cloud_config(cfg)

    def test_azure_restricted_domain(self):
        self.assertEqual(
            valid_azure_endpoint("https://resource.openai.azure.com/openai/v1/chat/completions"),
            "https://resource.openai.azure.com/openai/v1/chat/completions")
        for value in [
            "https://evil.com/openai/v1/chat/completions",
            "http://resource.openai.azure.com/openai/v1/chat/completions",
            "https://resource.openai.azure.com.evil.com/openai/v1/chat/completions",
            "https://user:pass@resource.openai.azure.com/openai/v1/chat/completions",
        ]:
            with self.assertRaises(ValueError):
                valid_azure_endpoint(value)

    def test_invalid_model_decisions_fail_closed(self):
        approved,reason,flags=_parse_model_decision(json.dumps({
            "decision":"APPROVE","reason":"Test approval","risk_flags":[]}))
        self.assertTrue(approved)
        approved,reason,flags=_parse_model_decision(json.dumps({
            "decision":"APPROVE","reason":"Flagged","risk_flags":["insufficient_data"]}))
        self.assertFalse(approved)
        for result in ["not-json","{}",'{"decision":"YES"}',json.dumps({
            "decision":"APPROVE","reason":"a","risk_flags":[],"order_size":100000,
        })]:
            with self.assertRaises((ValueError,json.JSONDecodeError)):
                _parse_model_decision(result)

    def test_openai_adapter_extracts_valid_json(self):
        reply={"status":"completed","output":[{
            "content":[{"type":"output_text",
                "text":json.dumps({"decision":"APPROVE","reason":"mock","risk_flags":[]})}]
        }],"usage":{"input_tokens":90,"output_tokens":20}}
        with patch("cloud_models._http_json",return_value=reply) as call:
            result=_model_request("openai","test-model","fake-key","",{
                "symbol":"SPY","price":10.0,"trade_type":"PAPER_BUY"})
        self.assertTrue(result["approved"])
        self.assertEqual(result["input_tokens"],90)
        self.assertEqual(call.call_args.args[0],"https://api.openai.com/v1/responses")
        self.assertFalse(call.call_args.args[2]["store"])

    def test_gemini_adapter_extracts_valid_json(self):
        reply={"candidates":[{"finishReason":"STOP","content":{"parts":[{
            "text":json.dumps({"decision":"REJECT","reason":"uncertain","risk_flags":["risk"]})}]}}],
            "usageMetadata":{"promptTokenCount":14,"candidatesTokenCount":7}}
        with patch("cloud_models._http_json",return_value=reply):
            result=_model_request("gemini","gemini-example","fake-key","",{
                "symbol":"SPY","price":10})
        self.assertFalse(result["approved"])
        self.assertEqual(result["output_tokens"],7)

    def test_anthropic_adapter_extracts_valid_json(self):
        reply={"stop_reason":"end_turn","content":[{"type":"text",
            "text":json.dumps({"decision":"APPROVE","reason":"mock","risk_flags":[]})}],
            "usage":{"input_tokens":10,"output_tokens":12}}
        with patch("cloud_models._http_json",return_value=reply):
            result=_model_request("anthropic","claude-test","fake-key","",{
                "symbol":"SPY","price":10})
        self.assertTrue(result["approved"])

    def test_conservative_consensus(self):
        c=default_cloud_config()
        c["enabled"]=True
        c["mode"]="consensus"
        c["required_approvals"]=2
        for provider in ("openai","gemini"):
            c["providers"][provider].update({
                "enabled":True,"model":"test-model",
                "input_usd_per_million":0.1,"output_usd_per_million":0.1})
            set_cloud_key(self.root/"cloud_keys.json",provider,"fake-key-value-1234")
        from dashboard_control import write_atomic
        write_atomic(self.root/"cloud_config.json",validate_cloud_config(c))
        router=CloudReviewRouter(self.root)
        with patch("cloud_models._model_request",return_value={
            "approved":True,"reason":"mock","flags":(),
            "input_tokens":10,"output_tokens":3}):
            result=router.review({"symbol":"SPY","price":10})
        self.assertTrue(result.approved)
        self.assertEqual(len(result.provider_details),2)
        with patch("cloud_models._model_request",side_effect=[
            {"approved":True,"reason":"mock","flags":(),
             "input_tokens":10,"output_tokens":3},
            {"approved":False,"reason":"risk","flags":("uncertain",),
             "input_tokens":10,"output_tokens":3},
        ]):
            result=router.review({"symbol":"SPY","price":10})
        self.assertFalse(result.approved)
        self.assertIn("ai_veto",result.risk_flags)

    def test_daily_cap_stops_unbounded_inference(self):
        c=default_cloud_config()
        c["enabled"]=True
        c["max_daily_calls"]=1
        c["providers"]["openai"].update({
            "enabled":True,"model":"test-model",
            "input_usd_per_million":0.1,"output_usd_per_million":0.1})
        set_cloud_key(self.root/"cloud_keys.json","openai","fake-key-value-1234")
        from dashboard_control import write_atomic
        write_atomic(self.root/"cloud_config.json",validate_cloud_config(c))
        router=CloudReviewRouter(self.root)
        with patch("cloud_models._model_request",return_value={
            "approved":True,"reason":"mock","flags":(),
            "input_tokens":10,"output_tokens":3}) as model:
            self.assertTrue(router.review({"symbol":"SPY","price":10}).approved)
            self.assertFalse(router.review({"symbol":"SPY","price":11}).approved)
            self.assertEqual(model.call_count,1)


if __name__=="__main__":
    unittest.main(verbosity=2)
