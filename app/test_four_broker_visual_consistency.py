from pathlib import Path
import re,unittest
ROOT=Path(__file__).resolve().parent.parent
class BrokerVisualConsistencyTests(unittest.TestCase):
 def test_same_top_level_dashboard_structure(self):
  html=(ROOT/'web/index.html').read_text()
  for name in ('live','robinhood','webull','paper'):
   with self.subTest(name=name):
    match=re.search(r'<section class="view hidden" id="view-[^"]+"[^>]*data-broker-dashboard="'+name+r'"[^>]*>',html)
    self.assertIsNotNone(match)
    next_view=html.find('<section class="view hidden"',match.end())
    region=html[match.end():next_view if next_view!=-1 else len(html)]
    self.assertIn('aria-label=',match.group(0))
    for cls in ('hero-head','notice','rh-portfolio-performance','stats-grid','content-grid','broker-holdings-heading'):
     self.assertIn(cls,region,(name,cls))
    self.assertLess(region.index('rh-portfolio-performance'),region.index('stats-grid'))
    self.assertLess(region.index('stats-grid'),region.index('content-grid'))
    stat_start=region.index('class="stats-grid"')
    stat_end=region.index('class="content-grid"',stat_start)
    self.assertEqual(region[stat_start:stat_end].count('class="stat-card"'),4)
    perf_start=region.index('class="rh-portfolio-metrics"')
    perf_end=region.index('class="stats-grid"',perf_start)
    self.assertEqual(len(re.findall(r'<strong id="(?:rh-performance|webull-performance|schwab-perf|paper-performance)-',region[perf_start:perf_end])),3)
 def test_unique_existing_account_data_bindings(self):
  html=(ROOT/'web/index.html').read_text()
  for id_ in ('schwab-perf-holdings','webull-positions','robinhood-positions-list','positions-list','stat-equity','webull-equity','live-equity','robinhood-total-stat'):
   self.assertEqual(html.count('id="'+id_+'"'),1,id_)
