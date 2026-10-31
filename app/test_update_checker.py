"""Release-tag parsing; do not mistake beta/pre-release tags for stable upgrades."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from check_updates import latest_release
from update_status import semver,update_information

class UpdateTests(unittest.TestCase):
    def test_latest_stable_only(self):
        listing="\n".join([
            "aaaa refs/tags/v1.0.0",
            "bbbb refs/tags/v0.9.0-beta",
            "cccc refs/tags/v1.0.2",
            "dddd refs/tags/v1.1.0-dev",
            "eeee refs/tags/v1.0.1",
            "ffff refs/heads/main"])
        self.assertEqual(latest_release(listing),"1.0.2")
    def test_semver(self):
        self.assertEqual(semver("v1.0.2"),(1,0,2))
        self.assertIsNone(semver("v1.0.2-beta"))
    def test_not_checked_yet(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result=update_information(tmp,Path(__file__).resolve().parent)
            self.assertFalse(result["update_available"])
            self.assertEqual(result["status"],"not_checked")
if __name__=="__main__":unittest.main()
