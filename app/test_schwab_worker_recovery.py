"""Schwab monitoring survives transient held-asset candle outages without orders."""
import unittest
from unittest.mock import patch,MagicMock
from datetime import datetime,timezone
from decimal import Decimal
from live_order_safety import LiveBlocked
import live_worker

class TestSchwabRecovery(unittest.TestCase):
    def test_stale_held_candle_blocks_every_order_but_does_not_kill_worker(self):
        ledger=MagicMock()
        ledger.data={"orders":[],"halted":False,"opening_positions":{"NOK":3,"F":1},
                     "last_candle":0}
        snap=({},{"NOK":3,"F":1},Decimal("25"),Decimal("50"),Decimal("100"))
        calls=[]
        def candle_result(value,now):
            calls.append(value)
            if value=="NOK":
                raise LiveBlocked("Market candles missing or stale")
            return "SELL",int(now.timestamp()*1000)
        client=MagicMock()
        with patch.object(live_worker,"_live_risk",return_value={
                  "max_orders_per_day":7,"max_open_positions":3}),patch.object(
              live_worker,"get_snapshot",return_value=snap),patch.object(
              live_worker,"adopt_existing_account_position"),patch.object(
              live_worker,"reconcile",return_value=True),patch.object(
              live_worker,"risk_preflight",return_value=(0,False)),patch.object(
              live_worker,"market_is_normal",return_value=True),patch.object(
              live_worker,"_orders_today",return_value=0),patch.object(
              live_worker,"same_day_filled_buy",return_value=False),patch.object(
              live_worker,"recent_candles",side_effect=lambda c,s:s),patch.object(
              live_worker,"cross_signal",side_effect=candle_result),patch.object(
              live_worker,"_audit") as audit:
            live_worker.attempt(client,"selected",ledger,datetime.now(timezone.utc),submit=True)
        client.place_order.assert_not_called()
        client.get_quote.assert_not_called()
        self.assertEqual(len(calls),2)
        self.assertEqual(audit.call_args.args[2],"HELD_CANDLES_UNAVAILABLE")

    def test_paused_monitor_refreshes_broker_at_most_once_per_minute(self):
        client=MagicMock()
        with patch.object(live_worker.time,"monotonic",return_value=120.0),patch.object(
                live_worker,"get_snapshot",return_value=(None,{},0,0,0)) as scan:
            when,verified=live_worker.refresh_paused_account(client,"selected",0.0)
            self.assertEqual(when,120.0)
            self.assertTrue(verified)
            _,verified=live_worker.refresh_paused_account(client,"selected",when)
            self.assertTrue(verified)
            scan.assert_called_once()
        with patch.object(live_worker.time,"monotonic",return_value=181.0),patch.object(
                live_worker,"get_snapshot",return_value=(None,{},0,0,0)) as scan:
            _,verified=live_worker.refresh_paused_account(client,"selected",120.0)
            self.assertTrue(verified)
            scan.assert_called_once()

    def test_failed_paused_snapshot_is_not_claimed_verified(self):
        with patch.object(live_worker.time,"monotonic",return_value=150.0),patch.object(
                live_worker,"get_snapshot",side_effect=LiveBlocked("broker unavailable")) as scan:
            checked,verified=live_worker.refresh_paused_account(MagicMock(),"selected",0.0)
            self.assertFalse(verified)
            self.assertEqual(checked,150.0)
            scan.assert_called_once()
        with patch.object(live_worker.time,"monotonic",return_value=151.0),patch.object(
                live_worker,"get_snapshot") as scan:
            _,verified=live_worker.refresh_paused_account(
                MagicMock(),"selected",checked,prior_verified=verified)
            self.assertFalse(verified)
            scan.assert_not_called()

if __name__=="__main__":unittest.main()
