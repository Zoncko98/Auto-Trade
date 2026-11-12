import unittest
from datetime import datetime,timezone,timedelta
from robinhood_entry_quality import verify_entry,EntryQualityBlocked

NOW=datetime(2026,11,12,21,0,tzinfo=timezone.utc)
SIGNAL={"symbol":"BTC-USD","source":"COINBASE_WS","momentum_pct":1.1,
        "history_span_seconds":900,"trend_up":True,"history_points":6}
POLICY={"account":"account-a","take_profit_pct":"3","min_profit_pct":"1",
        "fee_buffer_pct":"0.25"}
class Journal:
    def __init__(self,rows=None):self.rows=rows or []
    def load(self):return {"orders":self.rows}
def loss(days=0,account="account-a",symbol="BTC-USD",pnl="-0.25",minutes=0):
    return {"account":account,"symbol":symbol,"side":"sell","status":"filled",
            "filled_at":(NOW-timedelta(days=days,minutes=minutes)).isoformat(),
            "realized_pnl_usd":pnl}
class QualityTests(unittest.TestCase):
    def test_clean_live_quote_passes(self):
        result=verify_entry(POLICY,SIGNAL,"0.15",Journal(),NOW)
        self.assertEqual(result["estimated_round_trip_cost_pct"],"0.65")
    def test_spread_blocks(self):
        with self.assertRaisesRegex(EntryQualityBlocked,"spread"):
            verify_entry(POLICY,SIGNAL,"0.30",Journal(),NOW)
    def test_fee_budget_blocks(self):
        policy=dict(POLICY,fee_buffer_pct="1.1")
        with self.assertRaisesRegex(EntryQualityBlocked,"round-trip"):
            verify_entry(policy,SIGNAL,"0.15",Journal(),NOW)
    def test_stale_cache_blocks_entry(self):
        with self.assertRaisesRegex(EntryQualityBlocked,"cached"):
            verify_entry(POLICY,dict(SIGNAL,source="COINBASE_RECENT_CACHE"),"0.1",Journal(),NOW)
    def test_chase_and_short_trend_block(self):
        for change in ({"momentum_pct":1.95},{"history_span_seconds":300},
                       {"trend_up":False},{"history_points":None}):
            with self.subTest(change=change),self.assertRaises(EntryQualityBlocked):
                verify_entry(POLICY,dict(SIGNAL,**change),"0.1",Journal(),NOW)
    def test_two_asset_losses_block(self):
        rows=[loss(minutes=15),loss(minutes=80)]
        with self.assertRaisesRegex(EntryQualityBlocked,"two verified"):
            verify_entry(POLICY,SIGNAL,"0.1",Journal(rows),NOW)
    def test_other_account_losses_do_not_block(self):
        rows=[loss(account="other"),loss(account="other",minutes=80)]
        verify_entry(POLICY,SIGNAL,"0.1",Journal(rows),NOW)
    def test_four_recent_losses_block_new_asset(self):
        rows=[loss(symbol="SOL-USD",minutes=10*i) for i in range(1,5)]
        with self.assertRaisesRegex(EntryQualityBlocked,"four consecutive"):
            verify_entry(POLICY,SIGNAL,"0.1",Journal(rows),NOW)
    def test_six_recent_buys_stop_churn(self):
        rows=[{"account":"account-a","symbol":"ETH-USD","side":"buy","status":"filled",
               "filled_at":(NOW-timedelta(hours=i)).isoformat()} for i in range(6)]
        with self.assertRaisesRegex(EntryQualityBlocked,"six filled buys"):
            verify_entry(POLICY,SIGNAL,"0.1",Journal(rows),NOW)
    def test_other_account_buys_do_not_count(self):
        rows=[{"account":"other","side":"buy","status":"filled",
               "filled_at":NOW.isoformat()} for _ in range(10)]
        verify_entry(POLICY,SIGNAL,"0.1",Journal(rows),NOW)
    def test_old_losses_expire(self):
        verify_entry(POLICY,SIGNAL,"0.1",Journal([loss(days=3),loss(days=4)]),NOW)
if __name__=="__main__":unittest.main()
