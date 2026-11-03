import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

class FourBrokerLayoutTests(unittest.TestCase):
 def test_section_order_for_each_original_dashboard(self):
  html=(ROOT/'web/index.html').read_text()
  sections={
   'live':('id="schwab-perf-value"','id="live-equity"','id="live-execution-pill"'),
   'webull':('id="webull-performance-value"','id="webull-equity"','id="webull-worker-updated"'),
   'robinhood':('id="rh-performance-value"','id="robinhood-total-stat"','id="robinhood-execution-pill"'),
   'paper':('id="paper-performance-value"','id="stat-equity"','id="paper-execution-label"')
  }
  for broker,markers in sections.items():
   with self.subTest(broker=broker):
    view='overview' if broker=='paper' else broker
    start=html.index('id="view-'+view+'"')
    region=html[start:]
    self.assertTrue(all(m in region for m in markers))
    self.assertLess(region.index(markers[0]),region.index(markers[1]))
    self.assertLess(region.index(markers[1]),region.index(markers[2]))
    self.assertIn('data-broker-dashboard="'+broker+'"',html[start:start+150])
 def test_positions_present_once_and_paper_data_bound(self):
  html=(ROOT/'web/index.html').read_text()
  js=(ROOT/'web/app.js').read_text()
  for id_ in ('schwab-perf-holdings','robinhood-positions-list','webull-positions','positions-list'):
   self.assertEqual(html.count('id="'+id_+'"'),1)
  for id_ in ('paper-performance-value','paper-performance-pnl','paper-performance-return',
              'paper-holdings-coverage','stat-open-holdings','paper-last-decision'):
   self.assertIn('$("'+id_+'")',js)
  self.assertIn('hasCosts',js)
  self.assertNotIn('data-ops-target=',html)
