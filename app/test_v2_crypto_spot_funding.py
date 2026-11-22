"""Robinhood spot/USD is authenticated spendable crypto, not stock settlement."""
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from trader_v2.launch_gates import launch_status
from trader_v2.migration_probe import _probe

NOW=datetime(2026,11,22,16,0,tzinfo=timezone.utc)
class CryptoClient:
 def __init__(self,buying="50",active=True):
  self.buying=buying;self.active=active;self.calls=0
 def list_accounts(self):
  self.calls+=1
  return [{"account_number":"rh1","status":"active",
           "is_api_tradable":self.active,
           "buying_power_currency":"USD","buying_power":self.buying}]
 def positions(self,account):
  return []
 def orders(self,account):
  return []
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","is_api_tradable":True}]
 def quote(self,symbol):
  raise ConnectionError("No quote can be fabricated")

class SpotFundingProofTests(TestCase):
 def probe(self,client,enabled=True):
  with TemporaryDirectory() as directory:
   with patch("robinhood_order_journal.OrderJournal") as journal,patch(
       "trader_v2.migration_probe.signed_pair_limits",
       return_value=("1","0.0001")):
    journal.return_value.load.return_value={"orders":[]}
    return _probe(directory,client,{"enabled":enabled,"account":"rh1"},
                  now=NOW,public_feed=None)
 def signed(self,broker):
  mode={"schwab":"AUTHENTICATED_SCHWAB_READ_ONLY",
        "webull":"AUTHENTICATED_WEBULL_READ_ONLY",
        "robinhood_crypto":"AUTHENTICATED_SIGNED_READ_ONLY"}[broker]
  return {"broker":broker,"mode":mode,"checked_at":NOW.isoformat(),
       "account_verified":True,"holdings_verified":True,
       "broker_history_verified":True,"local_journal_matched":True,
       "broker_open_order_count":0,"local_unresolved_count":0,
       "pairs_checked":1,"quote_timestamp_verified_symbols":1,"signed_last_trade_verified_symbols":1,
       "spot_buying_power_verified":True,
       "crypto_24x7_access_verified":True,
       "settled_cash_verified":False,"signed_settled_cash_verified":False,
       "settlement_contract_version":2}
 def gates(self,broker,report):
  with patch("trader_v2.launch_gates.private_json",return_value=report),patch(
       "trader_v2.launch_gates.mapping",
       return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}):
   raw=launch_status("/unused",broker,now=NOW)
  return {item["name"]:item["verified"] for item in raw["gates"]}
 def test_signed_tradable_spot_usd_does_not_claim_settled_stock_cash(self):
  doc=self.probe(CryptoClient())
  self.assertTrue(doc["spot_buying_power_verified"])
  self.assertTrue(doc["crypto_24x7_access_verified"])
  self.assertFalse(doc["settled_cash_verified"])
  self.assertEqual(doc["first_blocker"],
                   "BROKER_QUOTE_TIMESTAMP_OR_LAST_TRADE_UNVERIFIED")
  self.assertIn("NOT_SETTLED_CASH",doc["funding_source"])
 def test_disarmed_or_inactive_crypto_account_cannot_mint_spot_proof(self):
  self.assertFalse(self.probe(CryptoClient(),enabled=False)["spot_buying_power_verified"])
  self.assertFalse(self.probe(CryptoClient(active=False))["spot_buying_power_verified"])
  self.assertFalse(self.probe(CryptoClient(buying="-1"))["spot_buying_power_verified"])
 def test_signed_spot_crypto_funding_is_a_distinct_entry_gate(self):
  gates=self.gates("robinhood_crypto",self.signed("robinhood_crypto"))
  self.assertTrue(gates["SIGNED_SETTLED_FUNDING"])
  self.assertTrue(gates["SIGNED_MARKET_SESSION"])
  self.assertTrue(gates["EXECUTABLE_BROKER_QUOTE"])
  self.assertFalse(gates["V1_AI_AND_EXIT_PARITY"])
  self.assertFalse(gates["EXCLUSIVE_WRITER_OWNERSHIP"])
 def test_crypto_missing_spot_funds_or_tradability_stays_blocked(self):
  doc=self.signed("robinhood_crypto")
  doc["spot_buying_power_verified"]=False
  self.assertFalse(self.gates("robinhood_crypto",doc)["SIGNED_SETTLED_FUNDING"])
  doc["spot_buying_power_verified"]=True
  doc["crypto_24x7_access_verified"]=False
  self.assertFalse(self.gates("robinhood_crypto",doc)["SIGNED_MARKET_SESSION"])
 def test_foreign_spot_crypto_proof_never_unblocks_webull_or_schwab(self):
  for broker in ("schwab","webull"):
   with self.subTest(broker=broker):
    doc=self.signed(broker)
    gates=self.gates(broker,doc)
    self.assertFalse(gates["SIGNED_SETTLED_FUNDING"])
    self.assertFalse(gates["SIGNED_MARKET_SESSION"])
