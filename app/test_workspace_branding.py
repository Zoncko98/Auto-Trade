"""Brand asset provenance and missing-balance guardrails (no real trading)."""
import unittest
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parent.parent

class BrandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active=None
        self.tiles={}
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="button" and "data-workspace" in d:
            self.active=d["data-workspace"]
            self.tiles[self.active]={"images":[],"svgs":0}
        elif self.active is not None:
            if tag=="img":self.tiles[self.active]["images"].append(d.get("src"))
            if tag=="svg":self.tiles[self.active]["svgs"]+=1
    def handle_endtag(self,tag):
        if tag=="button":self.active=None

class WorkspaceBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"web/index.html").read_text(encoding="utf-8")
        cls.js=(ROOT/"web/app.js").read_text(encoding="utf-8")
        cls.css=(ROOT/"web/workspace.css").read_text(encoding="utf-8")
        cls.parser=BrandingParser()
        cls.parser.feed(cls.html)
    def test_paper_wallet_and_no_letter_markers(self):
        for name in ("paper","live","webull","robinhood_crypto","interactive_brokers"):
            self.assertEqual(self.parser.tiles[name]["svgs"],1,name)
            self.assertFalse(self.parser.tiles[name]["images"],name)
        self.assertIn("workspace-tile-icon paper-icon",self.html)
        self.assertNotIn('aria-hidden="true">W</span>',self.html)
        self.assertNotIn('aria-hidden="true">IB</span>',self.html)
    def test_only_verified_external_brand_kit_asset_is_bundled(self):
        alpaca=ROOT/"web/assets/brands/alpaca-official-light.png"
        self.assertEqual(alpaca.read_bytes()[:8],b"\x89PNG\r\n\x1a\n")
        self.assertLess(alpaca.stat().st_size,50000)
        self.assertEqual(self.parser.tiles["alpaca"]["images"],
            ["/assets/brands/alpaca-official-light.png"])
        self.assertEqual(sorted(x.name for x in alpaca.parent.iterdir()),
            ["alpaca-official-light.png"])
    def test_balances_are_never_faked_or_inferred_from_token(self):
        self.assertEqual(self.html.count('id="workspace-schwab-balance"'),1)
        self.assertEqual(self.html.count('id="workspace-paper-balance"'),1)
        self.assertIn('age<=300000',self.js)
        self.assertIn('live?.worker_online===true',self.js)
        self.assertIn('typeof value!=="number"',self.js)
        self.assertIn('clearWorkspaceBalances();',self.js)
    def test_logos_have_independent_permission_notes(self):
        doc=(ROOT/"docs/guides/workspace-tiles.md").read_text(encoding="utf-8")
        self.assertIn("Schwab's [terms]",doc)
        self.assertIn("official external-use brand kit",doc)
        self.assertIn("neutral",doc)
        self.assertIn("does not imply endorsement",doc)
    def test_disabled_tile_logos_are_desaturated(self):
        self.assertIn(".workspace-tile.is-coming-soon .workspace-brand-logo",self.css)
        self.assertIn("filter:grayscale(1)",self.css)
        self.assertIn("pointer-events:none",self.css)

if __name__=="__main__":
    unittest.main()
