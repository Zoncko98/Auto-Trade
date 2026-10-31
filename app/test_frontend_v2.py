"""Regression tests for authenticated dashboard controls, evidence and Excel output.

All broker inputs synthetic; nothing reaches Schwab or submits an order.
"""
import io
import json
import tempfile
import unittest
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from live_extension import (RISK_DEFAULTS,validate_risk,read_live_risk,
    set_live_risk,broker_fills,rows_from_live,log_decision,read_decisions,excel_export)
from dashboard_control import write_atomic
from live_order_safety import OrderLedger,LiveBlocked
from live_worker import risk_preflight

class UIControls(unittest.TestCase):
    def test_live_limits_are_bounded_to_hard_capped_cash_only_configuration(self):
        self.assertEqual(validate_risk(RISK_DEFAULTS)["max_order_usd"],25)
        for key,unsafe in [
            ("max_order_usd",25.01),("max_daily_loss",5.01),
            ("max_position_pct",25.1),("max_open_positions",4),
            ("max_buys_per_day",4),("max_orders_per_day",8),
            ("allocation_pct",150),
        ]:
            row=dict(RISK_DEFAULTS);row[key]=unsafe
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_risk(row)
        row=dict(RISK_DEFAULTS);row["max_orders_per_day"]=2
        with self.assertRaisesRegex(ValueError,"below daily buy"):
            validate_risk(row)

    def test_atomic_settings_and_revision_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            original=read_live_risk(temp)
            self.assertEqual(original["revision"],0)
            revised=dict(RISK_DEFAULTS);revised["max_order_usd"]=12
            saved=set_live_risk(temp,0,revised,write_atomic)
            self.assertEqual(saved["revision"],1)
            self.assertEqual(read_live_risk(temp)["settings"]["max_order_usd"],12)
            with self.assertRaises(RuntimeError):
                set_live_risk(temp,0,RISK_DEFAULTS,write_atomic)
            self.assertEqual(read_live_risk(temp)["settings"]["max_order_usd"],12)

    def test_invalid_live_config_blocks_worker_not_silently_defaulted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"live";root.mkdir()
            (root/"risk_settings.json").write_text('{"version":1,"revision":4,"settings":{}}')
            with self.assertRaises(ValueError):
                read_live_risk(temp)

    def test_runtime_loss_limit_tightens_existing_hard_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger=OrderLedger.open(Path(temp)/"orders.json")
            ledger.data["day"]=datetime.now(timezone.utc).date().isoformat()
            ledger.data["day_start_equity"]="100"
            with self.assertRaisesRegex(LiveBlocked,"drawdown"):
                risk_preflight(ledger,{},Decimal("98.0"),Decimal("98"),
                    Decimal("0"),"F",{**RISK_DEFAULTS,"max_daily_loss":1.5})
            self.assertFalse(risk_preflight(ledger,{},Decimal("98"),Decimal("98"),
                 Decimal("0"),"F",RISK_DEFAULTS)[1])

class AuditTrail(unittest.TestCase):
    def test_append_and_read_validated_no_hidden_reasoning(self):
        with tempfile.TemporaryDirectory() as temp:
            event={"at":datetime.now(timezone.utc).isoformat(),
                "symbol":"SOFI","decision":"AI_VETO",
                "summary":"impact zero; candidate blocked",
                "model":"local:qwen2.5:1.5b",
                "headlines":[{"title":"Company statement","source":"Publisher",
                              "published_at":"2026-10-30T20:00:00+00:00",
                              "url":"https://news.google.com/"}]}
            log_decision(temp,event)
            rows=read_decisions(temp)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["decision"],"AI_VETO")
            self.assertEqual((Path(temp)/"live"/"decisions.jsonl").stat().st_mode & 0o077,0)

    def test_order_fill_price_is_verified_from_execution_legs(self):
        result={"filledQuantity":2,"orderActivityCollection":[{
            "activityType":"EXECUTION","executionLegs":[
            {"quantity":1,"price":10.05},{"quantity":1,"price":10.15}]}]}
        details=broker_fills(result,2)
        self.assertEqual(details["filled_price"],"10.1000")
        self.assertIsNone(broker_fills({"filledQuantity":2},2))
        self.assertIsNone(broker_fills(result,3))

    def test_ledger_stores_fill_only_if_broker_detail_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger=OrderLedger.open(Path(temp)/"orders.json")
            o=ledger.record_before_network("F","BUY",2,Decimal("10.20"),12345)
            ledger.mark_accepted(o,123)
            ledger.mark_terminal(o,"FILLED",{"filled_price":"10.10","filled_quantity":"2"})
            reopened=OrderLedger.open(ledger.path)
            self.assertEqual(reopened.data["orders"][0]["filled_price"],"10.10")

    def test_pnl_never_assumes_original_spyd_purchase_price(self):
        sample={"orders":[
            {"symbol":"SPYD","action":"SELL","quantity":2,"state":"FILLED",
             "limit_price":"49","filled_price":"49.10"},
            {"symbol":"F","action":"BUY","quantity":2,"state":"FILLED",
             "limit_price":"10.20","filled_price":"10.10"},
            {"symbol":"F","action":"SELL","quantity":2,"state":"FILLED",
             "limit_price":"11.00","filled_price":"10.80"}]}
        rows=rows_from_live(sample)
        self.assertIsNone(rows[0]["gross_realized_pnl"])
        self.assertIsNone(rows[1]["gross_realized_pnl"])
        self.assertEqual(rows[2]["gross_realized_pnl"],1.4)

    def test_real_xlsx_files_and_excel_formula_injection_is_literal_text(self):
        entries=[{"index":0,"created_at":"2026-10-30","symbol":"F",
                  "action":"BUY","quantity":1,"limit_price":9.0,
                  "filled_price":None,"filled_notional":None,
                  "gross_realized_pnl":None,"state":"WORKING",
                  "reason":"=HYPERLINK(\"https://evil.example\")"}]
        evidence=[{"at":"2026-10-30","symbol":"F","decision":"NO_SIGNAL",
                   "summary":"No completed candle trigger","model":"None",
                   "headlines":[{"title":"+cmd","source":"Publisher"}]}]
        workbook=excel_export("Live",entries,evidence)
        self.assertGreater(len(workbook),1500)
        with ZipFile(io.BytesIO(workbook)) as z:
            names=z.namelist()
            self.assertIn("xl/worksheets/sheet2.xml",names)
            for name in names:
                if name.endswith(".xml"):
                    ET.fromstring(z.read(name))
            cells=z.read("xl/worksheets/sheet2.xml").decode()
            self.assertIn('t="inlineStr"',cells)
            self.assertNotIn("<f>",cells)
            self.assertIn("HYPERLINK",cells)
            sheet=z.read("xl/worksheets/sheet3.xml").decode()
            self.assertIn("+cmd",sheet)
        one=excel_export("Live",entries,evidence,single=0)
        self.assertGreater(len(one),1000)
        with self.assertRaises(LookupError):
            excel_export("Live",entries,evidence,single=1)

if __name__=="__main__":
    unittest.main()
