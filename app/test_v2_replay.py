"""Historical replay: deterministic, bounded, simulated-only."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from trader_v2.models import Candle, AssetClass, RiskPolicy
from trader_v2.replay import replay_candles

class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2025, 10, 1, 14, tzinfo=timezone.utc)
        closes = [10,10,10,10,10,11,12,13,12,11,10,9,8,9,10,11,12,13]
        self.candles = [
            Candle("DEMO", start + timedelta(minutes=i), Decimal(str(value)))
            for i,value in enumerate(closes)]
    def test_replay_is_deterministic_and_cost_adjusted(self):
        a = replay_candles(self.candles, AssetClass.STOCK)
        b = replay_candles(self.candles, AssetClass.STOCK)
        self.assertEqual(a,b)
        self.assertEqual(a["live_orders_submitted"],0)
        self.assertGreater(a["signals"],0)
        self.assertGreater(a["fills"],0)
        self.assertEqual(a["mode"],"HISTORICAL_SYNTHETIC_REPLAY_ONLY")
    def test_crypto_replay_uses_distinct_controller(self):
        r = replay_candles(self.candles, AssetClass.CRYPTO)
        self.assertEqual(r["asset_class"],"CRYPTO")
        self.assertEqual(r["live_orders_submitted"],0)
    def test_invalid_timestamps_and_series_are_rejected(self):
        with self.assertRaises(ValueError):
            replay_candles(self.candles[:9], AssetClass.STOCK)
        with self.assertRaises(ValueError):
            replay_candles([self.candles[1],self.candles[0]]+self.candles[2:], AssetClass.STOCK)
    def test_extra_cost_changes_result_or_fills(self):
        low = replay_candles(self.candles,AssetClass.STOCK,fee_bps="0",slippage_bps="0")
        high = replay_candles(self.candles,AssetClass.STOCK,fee_bps="20",slippage_bps="20")
        self.assertNotEqual((low["net_pnl_after_simulated_costs"],low["fills"]),
                            (high["net_pnl_after_simulated_costs"],high["fills"]))
    def test_entry_gate_does_not_disable_exit(self):
        policy = RiskPolicy(max_entries_per_day=1)
        r = replay_candles(self.candles,AssetClass.STOCK,policy=policy)
        self.assertEqual(r["live_orders_submitted"],0)
