import unittest
from pathlib import Path
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent.parent
class BrokerVisualConsistencyTests(unittest.TestCase):
 def test_same_top_level_dashboard_structure(self):
  soup=BeautifulSoup((ROOT/'web/index.html').read_text(), 'html.parser')
  for name in ('live','robinhood','webull','paper'):
   with self.subTest(name=name):
    view=soup.select_one('[data-broker-dashboard="'+name+'"]')
    self.assertIsNotNone(view)
    self.assertTrue(view.get('aria-label'))
    children=[c for c in view.find_all(recursive=False) if c.name in ('div','section')]
    classes=[set(c.get('class',[])) for c in children]
    for cls in ('hero-head','notice','rh-portfolio-performance','stats-grid','content-grid'):
     self.assertGreaterEqual(sum(cls in v for v in classes),1,(name,cls))
    self.assertLess(next(i for i,c in enumerate(classes) if 'rh-portfolio-performance' in c),next(i for i,c in enumerate(classes) if 'stats-grid' in c))
    self.assertEqual(len(view.select('.stats-grid > .stat-card')),4)
    self.assertEqual(len(view.select('.rh-portfolio-metrics > div')),3)
    raw=(ROOT/'web/index.html').read_text()
    start=raw.index('data-broker-dashboard="'+name+'"')
    next_start=min([i for i in [raw.find('data-broker-dashboard="'+other+'"',start+1) for other in ('live','webull','robinhood','paper') if other!=name] if i!=-1] or [len(raw)])
    self.assertIn('broker-holdings-heading',raw[start:next_start])
 def test_unique_existing_account_data_bindings(self):
  soup=BeautifulSoup((ROOT/'web/index.html').read_text(),'html.parser')
  for id_ in ('schwab-perf-holdings','webull-positions','robinhood-positions-list','positions-list','stat-equity','webull-equity','live-equity','robinhood-total-stat'):
   self.assertEqual(len(soup.select('[id="'+id_+'"]')),1,id_)
