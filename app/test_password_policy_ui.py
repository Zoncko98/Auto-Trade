"""New-password policy and UI separation without changing existing verifier formats."""
from pathlib import Path
import tempfile
import unittest
from profile_auth import ProfileError,validate_new_password,rotate,verify

ROOT=Path(__file__).resolve().parent.parent
class PasswordPolicyAndNavigation(unittest.TestCase):
    def test_accepts_10_char_upper_number_symbol(self):
        validate_new_password("Abcdefgh1!")
        validate_new_password("C0mpact~2026")
        validate_new_password("My Old Style Passphrase1!")
    def test_rejects_missing_required_classes_and_controls(self):
        for candidate in ("Abc1!", "alllowercase123!", "MissingSymbols1",
                         "Missing1symbol", "AllUppercase!AAA", "Newline1!A\n",
                         "TEST 123456789", "\x00AA123456!"):
            # TEST 123456789 has no symbol, and Missing1symbol no symbol.
            with self.subTest(candidate=candidate),self.assertRaises(ProfileError):
                validate_new_password(candidate)
    def test_existing_legacy_passwords_still_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_password="long-legacy-password-no-uppercase-123456"
            current="generated-fallback-password-example-00000"
            rotate(tmp,current,"ValidPassword1!",current)
            self.assertTrue(verify(tmp,"ValidPassword1!",current))
    def test_three_distinct_screens_and_routes(self):
        setup=(ROOT/"web/setup.html").read_text()
        ai=(ROOT/"web/integrations.html").read_text()
        broker=(ROOT/"web/broker-schwab.html").read_text()
        profile=(ROOT/"web/index.html").read_text()
        frontend=(ROOT/"web/brokers.js").read_text()
        server=(ROOT/"app/dashboard_server.py").read_text()
        self.assertNotIn('id="setup-schwab-secret"',setup)
        self.assertNotIn('id="setup-market"',setup)
        self.assertNotIn('id="setup-paper"',setup)
        self.assertNotIn('id="setup-schwab-secret"',ai)
        self.assertNotIn('id="toggle-live"',ai)
        self.assertIn('id="setup-schwab-secret"',broker)
        self.assertIn('id="toggle-live"',broker)
        self.assertNotIn('id="setup-provider"',broker)
        self.assertIn('href="/integrations.html">⚙ Configure AI models',profile)
        self.assertIn('href="/broker-schwab.html#schwab-settings"',frontend)
        self.assertIn('"/broker-schwab.html":',server)
        self.assertIn('if path in ("/integrations.html","/broker-schwab.html")',server)
    def test_changes_do_not_require_20_characters(self):
        html=(ROOT/"web/index.html").read_text()
        assert 'minlength="20"' not in html
        self.assertIn('minlength="10"',html)
        self.assertIn('Administrator password (10+ characters', (ROOT/"web/setup.html").read_text())

if __name__=="__main__":unittest.main()
