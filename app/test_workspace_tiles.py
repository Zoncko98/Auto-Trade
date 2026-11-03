"""Regression tests for broker workspace selection tiles (no network or orders)."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

class TileParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tiles={}
        self.active=None
        self.labels=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="button" and "data-workspace" in a:
            self.active=a["data-workspace"]
            self.tiles[self.active]={"attrs":a,"text":[]}
        if tag=="link" and a.get("href")=="/workspace.css":
            self.labels.append("stylesheet")
    def handle_data(self,text):
        if self.active:self.tiles[self.active]["text"].append(text)
    def handle_endtag(self,tag):
        if tag=="button":self.active=None

class WorkspaceTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"web/index.html").read_text(encoding="utf-8")
        cls.js=(ROOT/"web/app.js").read_text(encoding="utf-8")
        cls.css=(ROOT/"web/workspace.css").read_text(encoding="utf-8")
        cls.server=(ROOT/"app/dashboard_server.py").read_text(encoding="utf-8")
        cls.parsed=TileParser()
        cls.parsed.feed(cls.html)
    def test_two_supported_profiles_are_clickable(self):
        tiles=self.parsed.tiles
        self.assertEqual(set(tiles),{"live","paper","webull","robinhood_crypto",
                                      "alpaca","interactive_brokers"})
        for name in ("live","paper"):
            with self.subTest(name=name):
                self.assertNotIn("disabled",tiles[name]["attrs"])
                self.assertIn("workspace-tile-featured",tiles[name]["attrs"]["class"])
        self.assertEqual(self.html.count('id="view-workspaces"'),1)
        self.assertIn('id="view-live"',self.html)
        self.assertIn('id="sidebar-account-context"',self.html)
        self.assertIn('class="workspace-tile-grid"',self.html)
        self.assertIn('class="workspace-upcoming-grid"',self.html)
        self.assertIn('id="breadcrumb-divider"',self.html)
        self.assertNotIn('aria-pressed="true"',self.html)

    def test_unimplemented_providers_are_grey_disabled_coming_soon(self):
        for name in ("alpaca","interactive_brokers"):
            with self.subTest(name=name):
                tile=self.parsed.tiles[name]
                self.assertIn("disabled",tile["attrs"])
                self.assertIn("is-coming-soon",tile["attrs"]["class"])
                self.assertIn("COMING SOON","".join(tile["text"]))
                self.assertIn("coming soon",tile["attrs"]["aria-label"].lower())
        self.assertIn(".workspace-tile.is-coming-soon",self.css)
        self.assertIn("cursor:not-allowed",self.css)
    def test_webull_connection_tile_open(self):
        tile=self.parsed.tiles["webull"]
        self.assertNotIn("disabled",tile["attrs"])
        self.assertNotIn("is-coming-soon",tile["attrs"]["class"])
        self.assertIn("CHECKING CONNECTION","".join(tile["text"]))
        self.assertIn('id="workspace-webull-status"',self.html)
        self.assertIn("function updateWebullTile(data)",self.js)
        self.assertIn("webullAccountVerified(data)",self.js)
        self.assertIn("webull",self.js)
    def test_landing_view_and_nested_account_navigation(self):
        self.assertNotIn('id="workspace-select"',self.html)
        self.assertNotIn('$("workspace-select")',self.js)
        self.assertIn('let activeView = "workspaces";',self.js)
        self.assertIn('showView("workspaces");',self.js)
        self.assertIn('id="live-nav-group" class="workspace-menu hidden"',self.html)
        self.assertIn('id="paper-nav-group" class="workspace-menu hidden"',self.html)
        self.assertIn('tile.dataset.workspace==="robinhood_crypto"?"robinhood":',self.js)
        self.assertIn('tile.dataset.workspace==="webull"?"webull":"live"',self.js)
        self.assertIn('if(!AVAILABLE_WORKSPACES.includes(workspace))return false;',self.js)
        self.assertIn('rhViews.includes(view)?"robinhood_crypto":webullViews.includes(view)?"webull":null;',self.js)
        self.assertIn('view==="workspaces"',self.js)
        self.assertIn('id="view-live"',self.html)
        self.assertIn('id="view-overview"',self.html)

    def test_robinhood_workspace_enabled_and_safe(self):
        tile=self.parsed.tiles["robinhood_crypto"]
        self.assertNotIn("disabled",tile["attrs"])
        self.assertNotIn("is-coming-soon",tile["attrs"]["class"])
        self.assertIn('id="view-robinhood"',self.html)
        self.assertIn('loadRobinhoodWorkspace()',self.js)
        self.assertIn('request("/api/robinhood/status")',self.js)
        self.assertIn('Robinhood API account verified',self.js)
        self.assertNotIn('submit_order(',self.js)

    def test_read_only_connected_status_does_not_authorize_trading(self):
        self.assertIn('request("/api/brokers")',self.js)
        self.assertIn('"AUTH SAVED":"NEEDS CONNECTION"',self.js)
        self.assertIn('Schwab workspace remains navigable',self.js)
        self.assertNotIn("submit_order(",self.js)
    def test_mobile_and_keyboard_accessibility(self):
        self.assertEqual(self.parsed.labels,["stylesheet"])
        self.assertIn('"/workspace.css": ("workspace.css", "text/css; charset=utf-8")',self.server)
        self.assertIn("focus-visible",self.css)
        self.assertTrue("@media(max-width:760px)" in self.css or "@media (max-width: 760px)" in self.css)
        self.assertIn("prefers-reduced-motion",self.css)
        self.assertIn('aria-label="Open a trading account"',self.html)

if __name__=="__main__":
    unittest.main()
