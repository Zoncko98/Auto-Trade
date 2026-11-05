"""Check source version metadata and public screenshot references are coherent."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ReleaseMetadataTests(unittest.TestCase):
    def test_semver_source_files_match(self):
        base = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        app = (ROOT / "app" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(base, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(base, app)
        self.assertTrue((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").startswith(f"## v{base} "))
        self.assertIn(f"**v{base}**", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn(f"## v{base} ", (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"))

    def test_readme_screenshot_files_are_real_jpegs(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for name in ("workspace-overview.jpg", "sign-in.jpg"):
            p = ROOT / "docs" / "images" / name
            self.assertIn(f"docs/images/{name}", readme)
            self.assertGreater(p.stat().st_size, 20_000)
            self.assertEqual(p.read_bytes()[:3], b"\xff\xd8\xff")
        self.assertIn("redacted", readme.lower())

if __name__ == "__main__":
    unittest.main()
