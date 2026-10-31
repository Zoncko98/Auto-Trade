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
                self.assertIn("aria-pressed",tiles[name]["attrs"])
        self.assertEqual(tiles["live"]["attrs"]["aria-pressed"],"true")
        self.assertEqual(tiles["paper"]["attrs"]["aria-pressed"],"false")
    def test_unimplemented_providers_are_grey_disabled_coming_soon(self):
        for name in ("webull","robinhood_crypto","alpaca","interactive_brokers"):
            with self.subTest(name=name):
                tile=self.parsed.tiles[name]
                self.assertIn("disabled",tile["attrs"])
                self.assertIn("is-coming-soon",tile["attrs"]["class"])
                self.assertIn("COMING SOON","".join(tile["text"]))
                self.assertIn("coming soon",tile["attrs"]["aria-label"].lower())
        self.assertIn(".workspace-tile.is-coming-soon",self.css)
        self.assertIn("cursor: not-allowed",self.css)
    def test_old_dropdown_replaced_and_navigation_kept(self):
        self.assertNotIn('id="workspace-select"',self.html)
        self.assertNotIn('$("workspace-select")',self.js)
        self.assertIn('id="live-nav-group"',self.html)
        self.assertIn('id="paper-nav-group"',self.html)
        self.assertIn('showView(tile.dataset.workspace==="paper"?"overview":"live")',self.js)
        self.assertIn('if(!AVAILABLE_WORKSPACES.includes(workspace))return false;',self.js)
        self.assertIn('tile.classList.toggle("is-active",selected)',self.js)
        self.assertIn('tile.setAttribute("aria-pressed",String(selected))',self.js)
    def test_read_only_connected_status_does_not_authorize_trading(self):
        self.assertIn('request("/api/brokers")',self.js)
        self.assertIn('"AUTH SAVED":"CONNECT ACCOUNT"',self.js)
        self.assertIn('Schwab workspace remains navigable',self.js)
        self.assertNotIn("submit_order(",self.js)
    def test_mobile_and_keyboard_accessibility(self):
        self.assertEqual(self.parsed.labels,["stylesheet"])
        self.assertIn('"/workspace.css": ("workspace.css", "text/css; charset=utf-8")',self.server)
        self.assertIn("focus-visible",self.css)
        self.assertIn("@media (max-width: 760px)",self.css)
        self.assertIn("prefers-reduced-motion",self.css)
        self.assertIn('aria-label="Choose trading workspace"',self.html)

if __name__=="__main__":
    unittest.main()
