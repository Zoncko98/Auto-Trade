from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent.parent
class BrokerDashboardUnificationTests(unittest.TestCase):
 def test_three_live_brokers_share_design_contract(self):
  html=(ROOT/'web/index.html').read_text()
  css=(ROOT/'web/workspace.css').read_text()
  for broker in ('live','robinhood','webull','paper'):
   self.assertIn('data-broker-dashboard="'+broker+'"',html)
   self.assertIn('id="view-'+("overview" if broker=="paper" else broker)+'"',html)
  self.assertEqual(html.count('<h1>Live account</h1>'),3)
  self.assertIn('[data-broker-dashboard] .stats-grid',css)
  self.assertIn('[data-broker-dashboard] .rh-portfolio-metrics',css)
 def test_no_duplicate_shared_operations_sidebar(self):
  html=(ROOT/'web/index.html').read_text()
  self.assertNotIn('data-ops-target=',html)
  self.assertIn('id="overview-shared-nav"',html)
  self.assertIn('data-view="operations"',html)
