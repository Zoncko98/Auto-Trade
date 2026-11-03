from pathlib import Path
import unittest
r=Path(__file__).resolve().parent.parent
class TileArrangementTests(unittest.TestCase):
 def test_reordering_controls(self):
  html=(r/'web/index.html').read_text();js=(r/'web/app.js').read_text()
  for token in ('workspace-reset-order','workspace-sort-toolbar','BROKER-REPORTED EQUITY'):
   self.assertIn(token,html)
  for token in ('WORKSPACE_ORDER_KEY','localStorage.setItem','dragstart','dragover','dragend','drop','ArrowLeft','ArrowRight','applyWorkspaceOrder()'):
   self.assertIn(token,js)
 def test_equity_from_broker_only(self):
  js=(r/'web/app.js').read_text()
  for token in ('/api/webull/portfolio?account_id=','total_net_liquidation_value','total_asset_currency!=="USD"','valid===accounts.length','webullEquityRequestId++'):
   self.assertIn(token,js)
  self.assertIn('live orders disabled',js)
if __name__=='__main__':unittest.main()
