"""Synthetic Phase 2 account adapter tests; no broker calls or live orders."""
import json,os,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from trader_v2.readonly_adapters import ReadOnlyBrokerRegistry,private_json
from trader_v2.models import AuthState
from trader_v2.status import summary

class ReadOnlyAccounts(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.now=datetime.now(timezone.utc).replace(microsecond=0);self.at=self.now.isoformat()
  self.registry=ReadOnlyBrokerRegistry(self.root)
 def write(self,name,data):
  file=self.root/name;file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  file.write_text(json.dumps(data));file.chmod(0o600);return file
 def schwab(self):
  self.write("live/operator.json",{"mode":"running"})
  self.write("live/account_snapshot.json",{"at":self.at,"cash":"100",
    "equity":"120","exposure":"20"})
  self.write("live/worker_heartbeat.json",{"at":self.at,"armed":True})
 def webull(self):
  self.write("config/webull_openapi.json",{"synthetic":True})
  self.write("webull/trading_policy.json",{"enabled":True,
    "stock_account":"ACC-1","crypto_account":"",
    "trade_stocks":True,"trade_crypto":False})
  self.write("webull/worker_status.json",{"updated_at":self.at,
    "worker":"RUNNING","environment":"production",
    "broker_accounts":[{"account_id":"ACC-1","account_type":"CASH"}],
    "account_summaries":[{"account_id":"ACC-1","environment":"production",
       "currency":"USD","cash":"100","account_value":"125","market_value":"25"}],
    "stock_buy_readiness":{"status":"EXPOSURE_OR_CASH_BUDGET_EXHAUSTED",
      "max_new_stock_usd":"0"}})
 def robinhood(self):
  self.write("robinhood/risk_policy.json",{"enabled":True,"account":"SYNTHETIC-ACCOUNT"})
  self.write("robinhood/worker_status.json",{"updated_at":self.at,
    "worker":"monitoring","broker_order_history_status":"VERIFIED",
    "accounts":[{"account_status":"active","api_tradable":True,
      "currency":"USD","buying_power_usd":"125.50"}]})
 def test_missing_evidence_refuses_to_claim_accounts_or_balances(self):
  rows=self.registry.inspect_all(now=self.now)
  self.assertEqual(len(rows),4)
  self.assertTrue(all(not row.read_verified for row in rows))
  self.assertTrue(all(row.equity_usd is None for row in rows))
  self.assertFalse(list(self.root.rglob("*.json")))
 def test_schwab_only_connected_on_fresh_worker_and_snapshot(self):
  self.schwab()
  row=self.registry.inspect("schwab",now=self.now)
  self.assertEqual(row.auth,AuthState.CONNECTED)
  self.assertEqual(row.equity_usd,D("120"));self.assertTrue(row.permission_armed)
  stale=self.registry.inspect("schwab",now=self.now+timedelta(seconds=130))
  self.assertFalse(stale.read_verified);self.assertIsNone(stale.equity_usd)
 def test_schwab_paused_is_not_disconnected(self):
  self.schwab();self.write("live/operator.json",{"mode":"paused"})
  row=self.registry.inspect("schwab",now=self.now)
  self.assertEqual(row.auth,AuthState.CONNECTED)
  self.assertFalse(row.permission_armed)
 def test_schwab_missing_equity_does_not_invent_zero(self):
  self.schwab();self.write("live/account_snapshot.json",{"at":self.at,"cash":"100"})
  row=self.registry.inspect("schwab",now=self.now)
  self.assertFalse(row.read_verified);self.assertIsNone(row.equity_usd)
 def test_schwab_supervisor_restart_budget_not_claimed_authenticated(self):
  self.write("live/supervisor_status.json",{"state":"MANUAL_REVIEW_REQUIRED",
    "reason":"RESTART_BUDGET_EXHAUSTED"})
  row=self.registry.inspect("schwab",now=self.now)
  self.assertEqual(row.reason_code,"MANUAL_REVIEW_REQUIRED")
  self.assertEqual(row.auth,AuthState.TEMPORARY_ERROR)
 def test_webull_authenticated_account_and_real_zero_headroom(self):
  self.webull()
  row=self.registry.inspect("webull",now=self.now)
  self.assertTrue(row.read_verified);self.assertTrue(row.permission_armed)
  self.assertEqual(row.equity_usd,D("125"))
  self.assertEqual(row.entry_headroom_usd,D("0"))
  self.assertEqual(row.account_class,"CASH")
  self.assertNotIn("ACC-1",str(row.public()))
 def test_webull_credential_rotation_invalidates_broker_account(self):
  self.webull()
  cred=self.root/"config/webull_openapi.json"
  newer=(self.root/"webull/worker_status.json").stat().st_mtime+3
  os.utime(cred,(newer,newer))
  row=self.registry.inspect("webull",now=self.now)
  self.assertFalse(row.read_verified)
  self.assertEqual(row.reason_code,"CREDENTIAL_ROTATED_OR_UNVERIFIED")
 def test_webull_wrong_selected_account_and_currency_are_rejected(self):
  self.webull()
  self.write("webull/trading_policy.json",{"enabled":True,"stock_account":"OTHER",
    "crypto_account":"","trade_stocks":True,"trade_crypto":False})
  self.assertEqual(self.registry.inspect("webull",now=self.now).reason_code,
    "SELECTED_ACCOUNT_MISSING")
  self.webull()
  p=self.root/"webull/worker_status.json";doc=json.loads(p.read_text())
  doc["account_summaries"][0]["currency"]="EUR";self.write("webull/worker_status.json",doc)
  self.assertEqual(self.registry.inspect("webull",now=self.now).reason_code,
    "BROKER_USD_BALANCE_UNVERIFIED")
 def test_webull_stale_snapshot_no_cash_claim(self):
  self.webull()
  row=self.registry.inspect("webull",now=self.now+timedelta(minutes=4))
  self.assertFalse(row.read_verified);self.assertIsNone(row.cash_usd)
 def test_robinhood_buying_power_is_not_cash_or_equity(self):
  self.robinhood();row=self.registry.inspect("robinhood_crypto",now=self.now)
  self.assertTrue(row.read_verified)
  self.assertEqual(row.buying_power_usd,D("125.50"))
  self.assertIsNone(row.cash_usd);self.assertIsNone(row.equity_usd)
 def test_robinhood_history_degraded_visible(self):
  self.robinhood()
  p=self.root/"robinhood/worker_status.json";doc=json.loads(p.read_text())
  doc["worker"]="monitoring_degraded";doc["broker_order_history_status"]="UNAVAILABLE"
  self.write("robinhood/worker_status.json",doc)
  row=self.registry.inspect("robinhood_crypto",now=self.now)
  self.assertEqual(row.worker_state,"DEGRADED")
  self.assertEqual(row.reason_code,"BROKER_ORDER_HISTORY_RECONCILIATION_REQUIRED")
 def test_robinhood_missing_balance_not_fabricated(self):
  self.robinhood()
  p=self.root/"robinhood/worker_status.json";doc=json.loads(p.read_text())
  doc["accounts"][0]["buying_power_usd"]="NaN";self.write("robinhood/worker_status.json",doc)
  self.assertFalse(self.registry.inspect("robinhood_crypto",now=self.now).read_verified)
 def test_paper_equity_unknown_with_unpriced_holdings(self):
  self.write("paper_account.json",{"schema":1,"cash":100,"positions":{}})
  self.assertEqual(self.registry.inspect("paper",now=self.now).equity_usd,D("100"))
  self.write("paper_account.json",{"schema":1,"cash":100,
    "positions":{"SPY":{"quantity":1,"entry_price":20}}})
  self.assertIsNone(self.registry.inspect("paper",now=self.now).equity_usd)
 def test_private_file_rejects_world_permissions_and_links(self):
  p=self.write("live/worker_heartbeat.json",{"at":self.at})
  p.chmod(0o644);self.assertIsNone(private_json(p))
  p.chmod(0o600);link=p.with_name("alias.json");link.symlink_to(p)
  self.assertIsNone(private_json(link))
 def test_authenticated_v2_status_shows_readonly_adapters_while_engine_off(self):
  self.schwab();self.webull();self.robinhood()
  with patch.dict(os.environ,{"AUTO_TRADER_V2_ENABLED":"false"}):
   doc=summary(self.root)
  self.assertFalse(doc["feature_enabled"])
  self.assertFalse(doc["live_order_authority"])
  self.assertEqual(len(doc["broker_adapters"]),4)
  self.assertTrue(doc["broker_adapters"][0]["read_verified"])
  self.assertFalse((self.root/"v2").exists())

if __name__=="__main__":unittest.main()
