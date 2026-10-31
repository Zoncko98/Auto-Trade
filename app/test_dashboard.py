"""End-to-end API, authentication, control state and paper capital tests."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import dashboard_server as ds
from dashboard_control import (
    default_control, read_control, validated_settings, write_atomic,
)
from ai_review import ReviewDecision
from paper_engine import PaperEngine
from risk_controls import RiskLimits


class Approved:
    def review(self, candidate):
        return ReviewDecision(True, "Approved only in test", "fixture")


class ControlTests(unittest.TestCase):
    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(read_control(Path(directory) / "missing.json")["mode"], "stopped")

    def test_invalid_limit_rejected(self):
        for key, value in (("allocation_pct", 101), ("max_daily_loss", float("nan")),
                           ("max_position_pct", -1), ("reinvest_pct", 120),
                           ("max_open_positions", 3.1)):
            s = default_control()["settings"].copy()
            s[key] = value
            with self.assertRaises(ValueError):
                validated_settings(s)

    def test_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory) / "control.json"
            control=default_control()
            write_atomic(path, control)
            self.assertEqual(read_control(path), control)

    def test_allocation_limits_paper_buy(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=PaperEngine(Path(directory)/"account.json",
                               RiskLimits(100,25,5,3),
                               allowed_symbols={"SPY"}, reviewer=Approved())
            limits=default_control()["settings"].copy()
            limits["allocation_pct"]=10
            limits["max_order_usd"]=7
            engine.set_trade_settings(limits)
            now=datetime.now(timezone.utc)
            start=now-timedelta(seconds=150)
            for i, price in enumerate([10,9,8,7,8,11]):
                result=engine.process("SPY",price,
                       (start+timedelta(seconds=10*i)).isoformat(),now=now)
            self.assertEqual(result, "PAPER_BUY")
            trade=engine.state["trades"][0]
            self.assertLessEqual(round(trade["quantity"]*trade["price"],2),7)
            self.assertGreater(engine.state["cash"],92)

    def test_reinvestment_reserve_and_equity(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=PaperEngine(Path(directory)/"account.json",
                               RiskLimits(100,25,5,3),
                               allowed_symbols={"SPY"}, reviewer=Approved())
            settings=default_control()["settings"].copy()
            settings["reinvest_pct"]=0
            engine.set_trade_settings(settings)
            now=datetime.now(timezone.utc)
            start=now-timedelta(seconds=200)
            values=[10,9,8,7,8,11,15,16,15,14,13,12,11,10]
            for i,price in enumerate(values):
                engine.process("SPY",price,
                               (start+timedelta(seconds=10*i)).isoformat(),now=now)
            sells=[t for t in engine.state["trades"] if t["action"]=="PAPER_SELL"]
            self.assertTrue(sells,"Expected simulated sell on falling short MA")
            profitable=[t for t in sells if t["realized_pnl"]>0]
            self.assertTrue(profitable,"Fixture must produce a profitable closing trade")
            self.assertGreater(engine.state["reserved_profit"],0)
            self.assertAlmostEqual(profitable[0]["reserved_profit"],profitable[0]["realized_pnl"],places=2)
            self.assertAlmostEqual(engine.equity(),100+profitable[0]["realized_pnl"],places=2)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.original=(ds.STATE_DIR,ds.PASSWORD,ds.SESSION_SECRET,ds.INITIAL_CAPITAL)
        ds.STATE_DIR=Path(cls.tmp.name)
        ds.PASSWORD="very-long-testing-password-123456"
        ds.SESSION_SECRET=b"aaaaaaaa-bbbbbbbb-cccccccc-dddddddd"
        ds.INITIAL_CAPITAL=100
        ds.write_atomic(ds.STATE_DIR/"control.json",default_control())
        cls.httpd=ds.ThreadingHTTPServer(("127.0.0.1",0),ds.Handler)
        cls.httpd.daemon_threads=True
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(2)
        ds.STATE_DIR,ds.PASSWORD,ds.SESSION_SECRET,ds.INITIAL_CAPITAL=cls.original
        cls.tmp.cleanup()

    def send(self,method,path,obj=None,cookie="",csrf=""):
        headers={"Host":"127.0.0.1"}
        body=None
        if obj is not None:
            body=json.dumps(obj)
            headers["Content-Type"]="application/json"
        if cookie:
            headers["Cookie"]=cookie
        if csrf:
            headers["X-CSRF-Token"]=csrf
        conn=http.client.HTTPConnection("127.0.0.1",self.httpd.server_port,timeout=3)
        conn.request(method,path,body=body,headers=headers)
        res=conn.getresponse()
        raw=res.read()
        result=json.loads(raw) if res.getheader("Content-Type","").startswith("application/json") else raw
        cookies=res.getheader("Set-Cookie","")
        code=res.status
        conn.close()
        return code,result,cookies

    def auth(self):
        code,data,headers=self.send("POST","/api/login",{"password":ds.PASSWORD})
        self.assertEqual(code,200)
        cookie=headers.split(";",1)[0]
        return cookie,data["csrf"]

    def test_health_and_denied_without_login(self):
        self.assertEqual(self.send("GET","/health")[0],200)
        self.assertEqual(self.send("GET","/api/status")[0],401)

    def test_login_settings_and_mode_csrf(self):
        cookie,csrf=self.auth()
        code,stat,_=self.send("GET","/api/status",cookie=cookie)
        self.assertEqual(code,200)
        self.assertEqual(stat["control"]["mode"],"stopped")
        rev=stat["control"]["revision"]
        self.assertEqual(self.send("POST","/api/mode",{"revision":rev,"mode":"running"},cookie=cookie)[0],403)
        code,changed,_=self.send("POST","/api/mode",{"revision":rev,"mode":"running"},cookie,csrf)
        self.assertEqual(code,200)
        self.assertEqual(changed["control"]["mode"],"running")
        self.assertEqual(self.send("POST","/api/mode",{"revision":rev,"mode":"paused"},cookie,csrf)[0],409)
        settings=changed["control"]["settings"].copy()
        settings["allocation_pct"]=40
        settings["max_daily_loss"]=3
        code,updated,_=self.send("POST","/api/settings",{"revision":rev+1,"settings":settings},cookie,csrf)
        self.assertEqual(code,200)
        self.assertEqual(updated["control"]["settings"]["allocation_pct"],40)
        self.assertTrue((ds.STATE_DIR/"settings_audit.jsonl").exists())
        self.assertEqual(self.send("POST","/api/logout",{},cookie,csrf)[0],200)

    def test_pagination(self):
        events=[{"action":"PAPER_BUY","symbol":"SPY","n":i} for i in range(42)]
        write_atomic(ds.STATE_DIR/"paper_account.json",{
            "schema":1,"cash":100,"reserved_profit":0,"positions":{},"history":{},
            "trades":events,"reviews":[],"halted":False,
        })
        cookie,_=self.auth()
        code,page,_=self.send("GET","/api/trades?page=2&limit=25",cookie=cookie)
        self.assertEqual(code,200)
        self.assertEqual(page["total"],42)
        self.assertEqual(len(page["items"]),17)
        self.assertEqual(page["items"][0]["n"],16)


    def test_retired_legacy_cloud_routes_stay_closed(self):
        """Legacy /api/cloud routes are no longer implemented.

        Cloud/OAuth configuration uses authenticated AI integration settings
        in the unified dashboard, with independent secret redaction tests.
        Do not reintroduce a deprecated API to satisfy an outdated test.
        """
        cookie,csrf=self.auth()
        self.assertEqual(self.send("GET","/api/cloud")[0],401)
        self.assertEqual(self.send("GET","/api/cloud",cookie=cookie)[0],404)
        doc={"provider":"openai","key":"synthetic-example-not-real-1234"}
        self.assertEqual(self.send("POST","/api/cloud/key",doc,cookie=cookie)[0],403)
        self.assertEqual(self.send("POST","/api/cloud/key",doc,cookie,csrf)[0],404)
        self.assertEqual(self.send("POST","/api/cloud/config",
            {"revision":0,"config":{}},cookie,csrf)[0],404)
        self.assertFalse((ds.STATE_DIR/"cloud_credentials.json").exists())


if __name__ == "__main__":

    unittest.main(verbosity=2)
