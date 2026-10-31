"""Forecast discovery, strict endpoint validation, research response and errors."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import io,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from forecast_connection import (ForecastConnectionError,validate_url,resolve_url,
                                 fetch,probe,connection_status,research_doc)
class Resp:
    status=200
    def __init__(self,value):self.value=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def read(self,n):return self.value[:n]
class ForecastConnectionTests(TestCase):
    def test_discovers_separate_port_on_same_ollama_host(self):
        data={"ai_provider":"ollama","ollama_url":"http://192.168.1.21:11434",
              "forecast_url":""}
        self.assertEqual(resolve_url(data),("http://192.168.1.21:8766","ollama-host-autodiscovery"))
        data["forecast_url"]="http://192.168.1.42:8766"
        self.assertEqual(resolve_url(data),("http://192.168.1.42:8766","manual"))
    def test_disallows_public_or_credentialed_urls(self):
        for url in ("http://8.8.8.8:8766","https://example.com:8766",
                    "http://192.168.1.21:11434/api/generate",
                    "http://localhost:8766",
                    "http://192.168.1.21:8766?secret=abc",
                    "http://user:pass@192.168.1.21:8766",
                    "http://0.0.0.0:8766",
                    "file:///etc/passwd"):
            with self.subTest(url=url),self.assertRaises(ForecastConnectionError):
                validate_url(url)
    def test_research_endpoint_must_be_read_only(self):
        with self.assertRaises(ForecastConnectionError):
            fetch("http://192.168.1.21:8766","/api/refresh")
    def test_explicit_probe_recognizes_research_identity(self):
        opened=[]
        def opener(request,timeout):
            opened.append((request.full_url,timeout))
            return Resp({"status":{"phase":"ready","last_refresh":"2026-10-31T05:30:00Z"},
                         "version":1,"mode":"research_only"})
        found=probe("http://192.168.1.21:8766",opener)
        self.assertTrue(found["connected"])
        self.assertEqual(opened[0][0],"http://192.168.1.21:8766/health")
        self.assertEqual(found["phase"],"ready")
    def test_other_service_rejected(self):
        with self.assertRaises(ForecastConnectionError):
            probe("http://192.168.1.21:8766",lambda req,timeout:Resp({"status":"ok"}))
    def test_missing_settings_are_explained(self):
        doc=connection_status({"ai_provider":"none","forecast_url":"","ollama_url":""})
        self.assertFalse(doc["connected"])
        self.assertEqual(doc["source"],"not_configured")
    def test_research_data_works_and_initializing_is_not_crash(self):
        settings={"forecast_url":"http://192.168.1.21:8766"}
        mock=lambda req,timeout:Resp({"candidates":[{"ticker":"SOFI"}]})
        doc=research_doc(settings,"/api/forecast",mock)
        self.assertEqual(doc["candidates"][0]["ticker"],"SOFI")
        self.assertEqual(research_doc(settings,"/api/forecast",
            lambda req,timeout:Resp({"status":"pending","message":"Initializing"}))["status"],"pending")
