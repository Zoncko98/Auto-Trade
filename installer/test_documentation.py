"""Ensure GitHub documentation navigation never contains dead local links."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MarkdownLinks(unittest.TestCase):
    def test_repository_navigation_links(self):
        pages=[ROOT/"README.md",ROOT/"INSTALL.md",ROOT/"CHANGELOG.md"]
        pages+=list((ROOT/"docs").rglob("*.md"))
        self.assertGreaterEqual(len(pages),16)
        missing=[]
        for page in pages:
            text=page.read_text(encoding="utf-8")
            for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)",text):
                url=match.group(1).split("#",1)[0]
                if not url or url.startswith(("https://","http://","mailto:")):
                    continue
                if not (page.parent/url).exists():
                    missing.append(f"{page.relative_to(ROOT)} => {url}")
            self.assertEqual(text.count(chr(96)*3)%2,0,f"Unbalanced code fences: {page}")
        self.assertEqual(missing,[])

if __name__=="__main__":
    unittest.main()
