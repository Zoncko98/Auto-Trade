from pathlib import Path
import unittest
root=Path(__file__).resolve().parent.parent
class OperationsUiTests(unittest.TestCase):
 def test_navigation_and_sections(self):
  html=(root/'web/index.html').read_text()
  js=(root/'web/app.js').read_text()
  for token in ('data-view="operations"','id="view-operations"','id="ops-activity"','id="ops-orders"','id="ops-portfolio"','id="ops-decision-detail"','id="ops-decision-select"'):
   self.assertIn(token,html)
  for token in ('loadOperations()','opsInspect()','/api/robinhood/status','/api/robinhood/portfolio','/api/live','/api/status'):
   self.assertIn(token,js)
 def test_consistent_broker_navigation(self):
  html=(root/'web/index.html').read_text()
  js=(root/'web/app.js').read_text()
  for group in ('live','robinhood','webull','paper'):
   section=html.split('id="'+group+'-nav-group"',1)[1].split('</div>',1)[0]
   self.assertIn('data-ops-target="exits"',section)
  for group in ('live','robinhood'):
   section=html.split('id="'+group+'-nav-group"',1)[1].split('</div>',1)[0]
   self.assertIn('data-ops-target="orders"',section)
  self.assertIn('showView("operations")',js)
  self.assertIn('opsSection(target)',js)
 def test_read_only_and_safety_labels(self):
  html=(root/'web/index.html').read_text()
  js=(root/'web/app.js').read_text()
  self.assertIn('unresolved intent remains locked',html)
  self.assertIn('Real brokerage and simulated equity are never combined',html)
  self.assertIn('Broker fill","Not established by this decision record"',js)
  self.assertIn('const fresh=live?.worker_online===true',js)
  self.assertIn('Promise.allSettled',js)
if __name__=='__main__':unittest.main()
