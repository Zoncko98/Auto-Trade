"""Test deterministic cash-only pretrade checks via unittest discovery."""
import unittest
from risk_controls import RiskControls, RiskLimits

class RiskControlsTests(unittest.TestCase):
    def setUp(self):
        self.risk=RiskControls(RiskLimits(
            initial_capital=100.0,max_position_pct=25.0,
            max_daily_loss=5.0,max_open_positions=3))

    def test_trade_guards(self):
        scenarios=(
            ("valid order",(20,100,100,0,0),True),
            ("oversized order",(30,100,100,0,0),False),
            ("insufficient cash",(20,10,100,0,0),False),
            ("daily loss limit",(20,100,100,0,-5),False),
            ("position limit",(20,100,100,3,0),False),
            ("zero-value order",(0,100,100,0,0),False),
            ("NaN order",(float("nan"),100,100,0,0),False),
            ("infinite order",(float("inf"),100,100,0,0),False),
            ("negative cash",(10,-1,100,0,0),False),
            ("negative equity",(10,100,-1,0,0),False),
            ("negative position count",(10,100,100,-1,0),False),
            ("fractional position count",(10,100,100,0.5,0),False),
        )
        for label,args,expected in scenarios:
            with self.subTest(label=label):
                self.assertIs(self.risk.check_new_position(*args)[0],expected)

if __name__=="__main__":
    unittest.main()
