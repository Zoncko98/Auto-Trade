"""Offline tests for the portable TrueNAS setup (never read real credentials)."""
import os, pathlib, tempfile, unittest
import sys
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import setup

class Validation(unittest.TestCase):
    def test_private_ollama_endpoint(self):
        self.assertEqual(setup.local_address("http://192.168.1.21:11434"),"http://192.168.1.21:11434")
        for url in ("http://8.8.8.8:11434","https://user:pass@192.168.1.21:11434",
                    "http://192.168.1.21:11434/something","not-a-url"):
            with self.assertRaises(ValueError):setup.local_address(url)

    def test_https_external_ai(self):
        self.assertEqual(setup.cloud_url("https://api.openai.com"),"https://api.openai.com")
        with self.assertRaises(ValueError):setup.cloud_url("http://api.example.com")

    def test_dry_run_ollama(self):
        with tempfile.TemporaryDirectory() as td:
            result=setup.create_layout(td,"192.168.1.43",8765,"A"*25,
                 {"provider":"ollama","url":"http://192.168.1.21:11434","model":"qwen3.5:4b"},dry_run=True)
            self.assertEqual(result["ai"]["AI_PROVIDER"],"local")
            self.assertFalse(list(pathlib.Path(td).iterdir()))

    def test_cloud_key_never_exposed_from_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            result=setup.create_layout(td,"192.168.1.43",8765,"A"*25,
                {"provider":"openai-compatible","base_url":"https://api.openai.com",
                 "model":"gpt-4o-mini","key":"example-test-key-123456","path":"/v1/chat/completions"},dry_run=True)
            self.assertIn("AI_API_KEY",result["ai"])
            self.assertFalse(list(pathlib.Path(td).iterdir()))

    def test_schwab_redirect_validation(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                setup.create_layout(td,"192.168.1.43",8765,"A"*25,
                    {"provider":"none"},{"app_key":"examplekey","app_secret":"examplesecret","callback":"https://external.example:8182"},dry_run=True)

    def test_private_file_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"private.env"
            setup.private_write(path,{"EXAMPLE":"synthetic-value-1234","OPTIONAL":""})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):setup.private_write(path,{"EXAMPLE":"new-value"})

if __name__=="__main__":unittest.main()
