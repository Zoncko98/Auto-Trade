"""Signed Robinhood V2 estimated quote GET-only diagnosis; no broker POST."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from trader_v2.robinhood_estimate_diagnostics import inspect,observed,ALLOWLIST
from robinhood_crypto_gateway import RobinhoodCryptoAdapter
import base64

NOW=datetime(2026,11,22,18,10,tzinfo=timezone.utc)

def estimate(**override):
 row={"symbol":"BTC-USD","side":"both","quantity":"0.0001",
      "timestamp":NOW.isoformat(),"bid":"100","ask":"100.1",
      "fee_ratio":"0.005","est_fee":"0.001",
      "est_total_cost":"10.01","est_total_credit":"10.00"}
 row.update(override)
 return {"results":[row]}

class SignedV2EstimateTests(TestCase):
 def test_signed_fee_and_timestamp_valid_estimate_never_authorizes_broker(self):
  self.assertEqual(inspect(estimate(),"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_FRESH_NONCROSSED_GET_ONLY")
 def test_crossed_price_always_reports_invalid_without_swapping(self):
  self.assertEqual(inspect(estimate(bid="101",ask="100.1"),"BTC-USD",
      D("0.0001"),now=NOW),"SIGNED_ESTIMATE_CROSSED")
 def test_stale_timestamp_and_wrong_quantity_fail(self):
  self.assertEqual(inspect(estimate(timestamp=(NOW-timedelta(seconds=50)).isoformat()),
      "BTC-USD",D("0.0001"),now=NOW),
      "SIGNED_ESTIMATE_FIELDS_OR_TIMESTAMP_UNVERIFIED")
  self.assertEqual(inspect(estimate(quantity="10"),"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_QUANTITY_MISMATCH")
 def test_fee_is_not_assumed_zero_if_missing(self):
  bad=estimate();del bad["results"][0]["est_fee"]
  self.assertEqual(inspect(bad,"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_FIELDS_OR_TIMESTAMP_UNVERIFIED")
 def test_provider_both_side_rows_validate_together_not_first_only(self):
  request=estimate()
  first=dict(request["results"][0],side="bid")
  second=dict(request["results"][0],side="ask")
  two={"results":[first,second]}
  self.assertEqual(inspect(two,"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_FRESH_NONCROSSED_GET_ONLY")
  second["ask"]="99"
  second["bid"]="98"
  self.assertEqual(inspect(two,"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_CROSSED_ACROSS_SIDES")
  second["ask"]="100.1";second["bid"]="100"
  second["timestamp"]=(NOW-timedelta(minutes=10)).isoformat()
  self.assertEqual(inspect(two,"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_FIELDS_OR_TIMESTAMP_UNVERIFIED")

 def test_native_json_numbers_are_observational_only(self):
  self.assertEqual(inspect(estimate(bid=100.0,ask=100.1,
      fee_ratio=0.005,est_fee=0.001,quantity=0.0001),
      "BTC-USD",D("0.0001"),now=NOW),
      "SIGNED_ESTIMATE_FRESH_NONCROSSED_GET_ONLY")
 def test_duplicate_identity_and_unsupported_symbol_rejected(self):
  multi=estimate();multi["results"]=multi["results"]*2
  self.assertEqual(inspect(multi,"BTC-USD",D("0.0001"),now=NOW),
                   "SIGNED_ESTIMATE_SIDE_IDENTITY_UNVERIFIED")
  self.assertEqual(observed(object(),"DOGE-USD"),
                   "SIGNED_ESTIMATE_SYMBOL_NOT_ALLOWLISTED")
 def test_signed_gateway_issues_only_documented_get_route(self):
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization
  private=Ed25519PrivateKey.generate().private_bytes(
       serialization.Encoding.Raw,serialization.PrivateFormat.Raw,
       serialization.NoEncryption())
  calls=[]
  def transport(path,headers):
   calls.append((path,headers.get("x-signature")))
   return estimate()
  client=RobinhoodCryptoAdapter("fake-test-key",
      base64.b64encode(private).decode(),transport=transport,clock=lambda:NOW.timestamp())
  result=client.estimated_price("BTC-USD","both",D("0.0001"))
  self.assertEqual(result["results"][0]["symbol"],"BTC-USD")
  self.assertEqual(len(calls),1)
  self.assertTrue(calls[0][0].startswith("/api/v2/crypto/trading/estimated_price/?"))
  self.assertIn("side=both",calls[0][0])
  self.assertIn("quantity=0.0001",calls[0][0])
  self.assertTrue(calls[0][1])
  with self.assertRaises(ValueError):
   client.estimated_price("BTC-USD","both",D("-1"))
  with self.assertRaises(ValueError):
   client.estimated_price("BTC-USD","sell",D("0.0001"))
  self.assertEqual(len(calls),1)
 def test_missing_signed_read_method_does_not_claim_estimate(self):
  self.assertEqual(observed(object(),"BTC-USD"),
                   "SIGNED_ESTIMATE_CLIENT_UNAVAILABLE")
 def test_quote_probe_does_not_turn_estimate_into_execution_gate(self):
  from trader_v2.migration_probe import _probe
  from test_v2_migration_probe import FakeSignedClient
  from trader_v2.models import MarketSnapshot,AssetClass
  broker=FakeSignedClient(NOW)
  broker.quotes["BTC-USD"]={"results":[{"symbol":"BTC-USD","bid":"101","ask":"100"}]}
  broker.estimated_price=lambda sym,side,quantity: estimate(
       timestamp=datetime.now(timezone.utc).isoformat())
  with TemporaryDirectory() as folder:
   result=_probe(Path(folder),broker,{"account":"acc1","enabled":True},now=NOW)
  self.assertEqual(result["signed_v2_estimate_diagnostics"]["BTC-USD"],
                   "SIGNED_ESTIMATE_FRESH_NONCROSSED_GET_ONLY")
  self.assertEqual(result["independent_trade_crosscheck_symbols"],0)
  self.assertFalse(result["cutover_ready"])
