import unittest
from datetime import datetime,timezone
from decimal import Decimal
from autonomous_selector import choose_entry

class MomentumTests(unittest.TestCase):
 def test_continuing_momentum_qualifies_without_new_crossover(self):
  now=datetime(2026,11,2,19,0,tzinfo=timezone.utc)
  t=int(now.timestamp()*1000)
  values=[10,10.02,10.04,10.06,10.08,10.10,10.12]
  bars=[{"datetime":t-300000*(8-i),"close":value} for i,value in enumerate(values)]
  found=choose_entry([(Decimal("6"),"F",Decimal("10.10"),Decimal("10.12"))],
                     lambda _:bars,now,True)
  self.assertIsNotNone(found)
  self.assertIn("continuing momentum",found.reason)
 def test_flat_price_does_not_qualify(self):
  now=datetime(2026,11,2,19,0,tzinfo=timezone.utc)
  t=int(now.timestamp()*1000)
  bars=[{"datetime":t-300000*(8-i),"close":10} for i in range(7)]
  self.assertIsNone(choose_entry([(Decimal("6"),"F",Decimal("9.99"),Decimal("10"))],
                   lambda _:bars,now,True))
