"""Static regression checks: installed app version is shown in the sidebar."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

class SidebarInstalledVersionTests(unittest.TestCase):
    def test_footer_replaces_old_worker_disclaimer(self):
        html=(ROOT/"web/index.html").read_text(encoding="utf-8")
        self.assertIn('id="sidebar-app-version"',html)
        self.assertNotIn("Only the Schwab worker can place real orders. The dashboard never submits a trade.",html)
        self.assertEqual(html.count('id="sidebar-app-version"'),1)
    def test_footer_fetches_actual_installed_version_after_login(self):
        script=(ROOT/"web/app.js").read_text(encoding="utf-8")
        self.assertIn('request("/api/profile").then(profile=>{',script)
        self.assertIn('"Auto Trader · v"+version',script)
        self.assertIn('label.textContent="Auto Trader · Version unavailable"',script)

if __name__=="__main__":unittest.main()
