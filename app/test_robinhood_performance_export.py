"""Read-only Robinhood report: financial accuracy, provenance and auth."""
import io,json,threading,tempfile,unittest
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
from zipfile import ZipFile
from robinhood_performance_export import build_robinhood_performance_workbook

NS="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NOW=datetime(2026,11,4,18,0,tzinfo=timezone.utc)

def row(id,side,symbol,status="filled",qty="1",price="10",fee="0.1",verified=True,
        offset=0,account="acct",error=None):
    at=(NOW+timedelta(minutes=offset)).isoformat()
    r={"account":account,"client_order_id":id,"broker_order_id":"broker-"+id,
       "symbol":symbol,"side":side,"status":status,
       "created_at":at,"filled_at":at if status=="filled" else None,
       "filled_quantity":qty if status=="filled" else None,
       "average_fill_price":price if status=="filled" else None,
       "fee_charged":fee,"fee_verified":verified,
       "quantity":qty,"limit_price":price}
    if error is not None:r["submission_error"]=error
    return r

def sheet_cells(blob,sheet=1):
    with ZipFile(io.BytesIO(blob)) as z:
        doc=ET.fromstring(z.read(f"xl/worksheets/sheet{sheet}.xml"))
    result={}
    for c in doc.findall(".//"+NS+"c"):
        val=c.find(NS+"v")
        word=c.find(".//"+NS+"t")
        result[c.attrib["r"]]=(val.text if val is not None else
                                word.text if word is not None else None)
    return result

class RobinhoodReportTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state=Path(self.dir.name)
        self.folder=self.state/"robinhood"
        self.folder.mkdir()
        (self.folder/"risk_policy.json").write_text(json.dumps({
            "account":"acct","enabled":True,"max_order_usd":"7.50"}))
        self.orders=[
          row("btc-buy","buy","BTC-USD",qty="2",price="10",fee="0.20",offset=0),
          row("btc-win","sell","BTC-USD",qty="1",price="11",fee="0.10",offset=20),
          row("btc-loss","sell","BTC-USD",qty="1",price="9.9",fee="0.10",offset=40),
          row("eth-buy","buy","ETH-USD",qty="2",price="10",fee="0",verified=False,offset=5),
          row("eth-sell","sell","ETH-USD",qty="1",price="11",fee="0.11",offset=50),
          row("other-buy","buy","NEAR-USD",qty="10",price="1",fee="0",account="other",offset=1),
          row("other-sell","sell","NEAR-USD",qty="10",price="50",fee="0",account="other",offset=55),
          row("avax-reject","buy","AVAX-USD",status="rejected",qty="2",price="9",
              error="Robinhood write rejected (HTTP 400); =HYPERLINK(\"bad\",\"x\")",offset=65)]
        self.orders.append({"account":"acct","symbol":"PEPE-USD",
           "client_order_id":"external-pepe","side":"external_reduction",
           "status":"externally_reconciled","quantity":"100",
           "filled_at":NOW.isoformat(),"note":"External sale; not bot P/L"})
        (self.folder/"order_intents.json").write_text(json.dumps({
            "version":1,"orders":self.orders}))
        self.scans=[
          {"at":NOW.isoformat(),"entry_candidate_symbol":"BTC-USD",
           "execution_status":"ORDER_ACCEPTED","ai_review_status":"PASS",
           "ai_reason":"Technical momentum passed with good spread",
           "execution_reason":"Approved technical candidate; broker accepted",
           "ai_model":"local:example","ai_candidate_reviews":[{
               "symbol":"BTC-USD","outcome":"PASS","elapsed_seconds":1.5,
               "reason":"Momentum and spread qualified"}]},
          {"at":(NOW+timedelta(minutes=20)).isoformat(),
           "exit_candidate_symbol":"BTC-USD","execution_status":"SELL_ORDER_ACCEPTED",
           "ai_review_status":"NOT_INVOKED","execution_reason":"TAKE_PROFIT BTC-USD"},
          {"at":(NOW+timedelta(minutes=40)).isoformat(),
           "exit_candidate_symbol":"BTC-USD","execution_status":"SELL_ORDER_ACCEPTED",
           "ai_review_status":"NOT_INVOKED","execution_reason":"STOP_LOSS BTC-USD"},
          {"at":(NOW+timedelta(minutes=65)).isoformat(),
           "entry_candidate_symbol":"AVAX-USD","execution_status":"BLOCKED_RobinhoodWriteRejected",
           "execution_reason":"Robinhood write rejected (HTTP 400)",
           "ai_review_status":"PASS"}
        ]
        (self.folder/"decision_history.json").write_text(json.dumps(self.scans))
    def test_xlsx_sheets_financial_math_missing_and_external(self):
        output=build_robinhood_performance_workbook(self.state,NOW+timedelta(hours=1))
        self.assertTrue(output.startswith(b"PK"))
        with ZipFile(io.BytesIO(output)) as z:
            names=z.namelist()
            self.assertIn("xl/worksheets/sheet10.xml",names)
            workbook=z.read("xl/workbook.xml").decode()
            for sheet in ("Overview","Trade Ledger","Closed Exits","Asset Analysis",
                          "Daily Results","Open Cost Basis","Scan Evidence",
                          "Candidate Reviews","Blocked and Rejected","Methodology"):
                self.assertIn(sheet,workbook)
        overview=sheet_cells(output,1)
        overview_map={overview[f"A{i}"]:overview.get(f"B{i}") for i in range(2,25) if f"A{i}" in overview}
        self.assertEqual(overview_map["Broker-confirmed filled buys"],"2")
        self.assertEqual(overview_map["Broker-confirmed filled sells"],"3")
        self.assertEqual(overview_map["Sell fills with verified P/L"],"2")
        self.assertEqual(overview_map["Sell fills lacking verified P/L"],"1")
        self.assertEqual(overview_map["Winning verified sells"],"1")
        self.assertEqual(overview_map["Losing verified sells"],"1")
        self.assertEqual(overview_map["Verified win rate %"],"50.0")
        self.assertAlmostEqual(float(overview_map["Verified net realized P/L USD"]),0.5,places=6)
        self.assertEqual(overview_map["External/manual reductions excluded from bot P/L"],"1")
        exits=sheet_cells(output,3)
        self.assertEqual(exits["J2"],"WIN")
        self.assertEqual(exits["J3"],"LOSS")
        self.assertAlmostEqual(float(exits["H2"]),0.8,places=6)
        self.assertAlmostEqual(float(exits["H3"]),-0.3,places=6)
        self.assertIsNone(exits.get("H4"))
        self.assertIn("TIME_SYMBOL_ONLY",exits["N2"])
        self.assertIn("P/L NOT VERIFIED",exits["O4"])
        ledger=sheet_cells(output,2)
        self.assertNotIn("NEAR-USD",str(ledger))
        self.assertTrue(any("EXTERNAL BROKER SALE" in str(v) for v in ledger.values()))
        with ZipFile(io.BytesIO(output)) as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    self.assertNotIn(b"<f>",z.read(name))
                    self.assertNotIn(b"our-private-key",z.read(name))
        self.assertTrue(any("=HYPERLINK" in str(v) for v in ledger.values()))
    def test_absent_history_is_not_fake_profit(self):
        (self.folder/"order_intents.json").write_text(json.dumps({"version":1,"orders":[]}))
        (self.folder/"decision_history.json").unlink()
        cells=sheet_cells(build_robinhood_performance_workbook(self.state),1)
        self.assertEqual(cells["B4"],"0")
        self.assertIsNone(cells.get("B14"))
    def test_configured_account_required(self):
        (self.folder/"risk_policy.json").unlink()
        with self.assertRaisesRegex(ValueError,"configured Robinhood"):
            build_robinhood_performance_workbook(self.state)
    def test_untrusted_journal_structure_is_rejected(self):
        (self.folder/"order_intents.json").write_text(json.dumps({"version":2,"orders":[]}))
        with self.assertRaises(Exception):
            build_robinhood_performance_workbook(self.state)

class RobinhoodReportHTTPTests(RobinhoodReportTests):
    def test_authenticated_export_and_guest_denial(self):
        from dashboard_server import Handler
        import dashboard_server
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address=f"http://127.0.0.1:{server.server_port}/api/robinhood/performance.xlsx"
        with patch.object(dashboard_server,"STATE_DIR",self.state),\
             patch.object(dashboard_server,"UNIFIED_APP",True):
            with self.assertRaises(HTTPError) as blocked:
                urlopen(address,timeout=10)
            self.assertEqual(blocked.exception.code,401)
            with patch.object(Handler,"_nonce",return_value="test-authenticated-session"):
                with urlopen(address,timeout=10) as response:
                    self.assertEqual(response.status,200)
                    self.assertIn("spreadsheetml.sheet",response.headers["Content-Type"])
                    self.assertIn("attachment",response.headers["Content-Disposition"])
                    self.assertEqual(response.headers["Cache-Control"],"no-store")
                    contents=response.read(10_000_000)
                    self.assertTrue(contents.startswith(b"PK"))
                with self.assertRaises(HTTPError) as filtered:
                    urlopen(address+"?account=other",timeout=10)
                self.assertEqual(filtered.exception.code,400)
