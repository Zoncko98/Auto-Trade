import unittest
from technical_indicators import calculate
class Tests(unittest.TestCase):
 def bars(self, n=100):
  return [{"close":10+i*.03,"volume":300000} for i in range(n)]
 def test_trending(self):
  x=calculate(self.bars())
  self.assertGreaterEqual(x["rsi14"],0)
  self.assertLessEqual(x["rsi14"],100)
  self.assertTrue(x["advisory_only"])
 def test_insufficient(self):
  with self.assertRaises(ValueError):calculate(self.bars(40))
 def test_invalid_price(self):
  bars=self.bars();bars[-1]["close"]=0
  with self.assertRaises(ValueError):calculate(bars)
 def test_flat(self):
  x=calculate([{"close":10,"volume":1000} for _ in range(100)])
  self.assertEqual(x["rsi14"],50)
if __name__=="__main__":unittest.main()
