import unittest
from trade_explanations import comparisons,explanation
class Tests(unittest.TestCase):
 def test_rank(self):
  a=comparisons([(2,"A",1,2),(1,"B",1,2)],"B")
  self.assertEqual(a[0]["outcome"],"screened_not_selected")
  self.assertEqual(a[1]["outcome"],"selected")
 def test_no_fake_level(self):
  self.assertIsNone(explanation("A","trend","review")["invalidation_level"])
 def test_negative_level(self):
  with self.assertRaises(ValueError): explanation("A","trend","review",invalidation=-3)
 def test_cap(self):
  self.assertEqual(len(explanation("A","t","r",alternatives=list(range(30)))["alternatives"]),8)
if __name__=="__main__":unittest.main()
