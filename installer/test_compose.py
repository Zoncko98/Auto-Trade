"""Validate source deployment Compose in a temporary directory; no Docker daemon required."""
import pathlib,subprocess,tempfile,unittest,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which("docker"),"Docker Compose not available on this host")
class ComposeConfig(unittest.TestCase):
    def test_config_without_real_credentials(self):
        with tempfile.TemporaryDirectory() as path:
            root=pathlib.Path(path)
            (root/"config").mkdir()
            for filename in ("dashboard.env","live.env","paper.env","schwab.env"):
                (root/"config"/filename).write_text("SYNTHETIC_TEST=not-a-credential\n")
            env=root/"compose.env"
            env.write_text("AUTOTRADER_DATA_DIR="+path+"\n"+
                "NAS_BIND_IP=127.0.0.1\nDASHBOARD_HOST_PORT=18765\n"+
                "AI_OLLAMA_URL=http://192.168.1.21:11434\n"+
                "FORECAST_API_URL=http://192.168.1.21:8766\n")
            run=subprocess.run(["docker","compose","--env-file",str(env),
                   "-f",str(ROOT/"deploy"/"docker-compose.yml"),"config","--quiet"],
                   text=True,capture_output=True,timeout=25)
            self.assertEqual(run.returncode,0,run.stderr[-700:])
if __name__=="__main__":unittest.main()
