"""Phase 4 Schwab exit-priority regression: synthetic broker inputs only.

No network connection or live brokerage credentials are used.
"""
from __future__ import annotations
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import io
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import live_worker
from live_extension import RISK_DEFAULTS, read_live_risk, validate_risk

class ExitOrderPriorityTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,20,15,0,tzinfo=timezone.utc)
        self.client=MagicMock()
        self.client.place_order.return_value.status_code=201
        self.ledger=MagicMock()
        self.ledger.data={"orders":[],"last_candle":0,"opening_positions":{},"halted":False}
        self.ledger.record_before_network.return_value={"state":"SUBMITTING"}
        self.snap=({},{"DEMO":2},Decimal("20"),Decimal("80"),Decimal("100"))
        self.risk={**RISK_DEFAULTS,"max_orders_per_day":7,
                   "max_buys_per_day":3,"max_exit_orders_per_day":3}

    def simulate(self, *, exits=0, with_position=True, sell_signal=True):
        equities=types.ModuleType("schwab.orders.equities")
        sell=MagicMock()
        equities.equity_sell_limit=sell
        equities.equity_buy_limit=MagicMock()
        utils=types.ModuleType("schwab.utils")
        utils.Utils=MagicMock()
        utils.Utils.return_value.extract_order_id.return_value=991
        root=types.ModuleType("schwab")
        orders=types.ModuleType("schwab.orders")
        root.orders=orders;root.utils=utils;orders.equities=equities
        captured=io.StringIO()
        with ExitStack() as stack:
            # Isolate account-writer lock state in CI rather than trying to
            # create or inspect /state under an unprivileged GitHub runner.
            temp=stack.enter_context(tempfile.TemporaryDirectory())
            isolated_live=Path(temp)/"live"
            isolated_live.mkdir(mode=0o700)
            stack.enter_context(patch.object(live_worker,"STATE_DIR",isolated_live))
            stack.enter_context(patch.dict(sys.modules,{
                "schwab":root,"schwab.orders":orders,
                "schwab.orders.equities":equities,"schwab.utils":utils}))
            mocks={
                "_live_risk":self.risk,
                "get_snapshot":self.snap if with_position else ({},{},Decimal("0"),Decimal("80"),Decimal("100")),
                "reconcile":True,
                "risk_preflight":(0,False),
                "market_is_normal":True,
                "same_day_filled_buy":False,
                "recent_candles":[1,2,3,4,5,6],
                "cross_signal":("SELL" if sell_signal else None,int(self.now.timestamp()*1000)),
                "result":{"DEMO":{}},
                "quote_levels":(Decimal("10"),Decimal("10.01")),
                "sell_limit":Decimal("9.95"),
            }
            for name,value in mocks.items():
                if name in ("get_snapshot","recent_candles"):
                    side=(lambda *args, val=value: val)
                    stack.enter_context(patch.object(live_worker,name,side_effect=side))
                else:
                    stack.enter_context(patch.object(live_worker,name,return_value=value))
            count=stack.enter_context(patch.object(live_worker,"_orders_today"))
            count.side_effect=lambda ledger,now,action=None: exits if action=="SELL" else 7
            audit=stack.enter_context(patch.object(live_worker,"_audit"))
            entries=stack.enter_context(patch.object(live_worker,"scan_entries"))
            stack.enter_context(patch.object(live_worker,"adopt_existing_account_position"))
            stack.enter_context(redirect_stdout(captured))
            live_worker.attempt(self.client,"account",self.ledger,self.now,submit=True)
        return captured.getvalue(),audit,entries,sell

    def test_held_exit_submits_after_prior_daily_entry_cap(self):
        stdout,audit,entries,sell=self.simulate()
        self.client.place_order.assert_called_once()
        self.ledger.record_before_network.assert_called_once()
        self.assertEqual(self.ledger.record_before_network.call_args.args[1],"SELL")
        self.ledger.mark_accepted.assert_called_once()
        self.assertIn("AUTONOMOUS DECISION: SELL",stdout)
        sell.assert_called_once()
        entries.assert_not_called()

    def test_separate_exit_cap_blocks_before_quote_or_broker_order(self):
        stdout,audit,entries,sell=self.simulate(exits=3)
        self.client.place_order.assert_not_called()
        self.client.get_quote.assert_not_called()
        self.assertIn("exit allowance reached",stdout)
        self.assertEqual(audit.call_args.args[2],"EXIT_ORDER_LIMIT")
        entries.assert_not_called()

    def test_new_buy_still_blocked_at_old_combined_order_cap(self):
        stdout,audit,entries,sell=self.simulate(with_position=False)
        self.client.place_order.assert_not_called()
        self.assertEqual(audit.call_args.args[2],"DAILY_ENTRY_ORDER_LIMIT")
        self.assertIn("Daily entry allowance reached",stdout)
        entries.assert_not_called()

    def test_migrates_nine_field_saved_policy_without_mutating_disk(self):
        nine={k:v for k,v in RISK_DEFAULTS.items() if k!="max_exit_orders_per_day"}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"live"
            root.mkdir(mode=0o700)
            path=root/"risk_settings.json"
            original=json.dumps({"version":1,"revision":9,"settings":nine})
            path.write_text(original)
            read=read_live_risk(tmp)
            self.assertEqual(read["revision"],9)
            self.assertEqual(read["settings"]["max_exit_orders_per_day"],3)
            self.assertEqual(path.read_text(),original)
            self.assertEqual(read["settings"]["max_orders_per_day"],nine["max_orders_per_day"])
        with self.assertRaises(ValueError):
            validate_risk({**RISK_DEFAULTS,"max_exit_orders_per_day":31})

    def test_existing_frontend_shows_and_controls_separate_limits(self):
        base=Path(__file__).resolve().parent
        web=(base/"web") if (base/"web"/"index.html").is_file() else (base.parent/"web")
        html=(web/"index.html").read_text(encoding="utf-8")
        js=(web/"local.js").read_text(encoding="utf-8")
        self.assertIn('id="live-max_exit_orders_per_day"',html)
        self.assertIn('id="live-risk-exits-preview"',html)
        self.assertIn('"max_exit_orders_per_day"',js)
        self.assertIn("settings.max_exit_orders_per_day",js)
if __name__=="__main__":
    unittest.main()
