"""Signed Webull USD settlement cannot be inferred from buying power."""
from unittest import TestCase
from copy import deepcopy
from decimal import Decimal
from trader_v2.webull_settlement import signed_settled_cash_budget


class WebullSettledCashTests(TestCase):
 def setUp(self):
  self.signed={
   "total_asset_currency":"USD","total_cash_balance":"100",
   "account_currency_assets":[{
     "currency":"USD","cash_balance":"100","settled_cash":"80",
     "held_amount":"5","frozen_amount":"10","buying_power":"90"}],
   "used_margin":"0",
  }
 def test_signed_settled_cash_budget_reduces_held_and_frozen(self):
  self.assertEqual(signed_settled_cash_budget(self.signed),Decimal("65"))
 def test_missing_held_or_frozen_cannot_imply_zero(self):
  for field in ("held_amount","frozen_amount","settled_cash"):
   doc=deepcopy(self.signed)
   del doc["account_currency_assets"][0][field]
   self.assertIsNone(signed_settled_cash_budget(doc))
 def test_total_or_day_buying_power_never_replaces_settled_funds(self):
  doc=deepcopy(self.signed)
  del doc["account_currency_assets"][0]["settled_cash"]
  doc["day_buying_power"]="99999"
  self.assertIsNone(signed_settled_cash_budget(doc))
 def test_reject_overstated_settled_cash_and_margin_usage(self):
  doc=deepcopy(self.signed)
  doc["account_currency_assets"][0]["settled_cash"]="120"
  self.assertIsNone(signed_settled_cash_budget(doc))
  doc=deepcopy(self.signed)
  doc["used_margin"]="1"
  self.assertIsNone(signed_settled_cash_budget(doc))
 def test_duplicate_usd_and_currency_ambiguity(self):
  doc=deepcopy(self.signed)
  doc["account_currency_assets"].append(deepcopy(doc["account_currency_assets"][0]))
  self.assertIsNone(signed_settled_cash_budget(doc))
 def test_zero_spendable_cannot_authorize_new_buy(self):
  doc=deepcopy(self.signed)
  doc["account_currency_assets"][0]["frozen_amount"]="100"
  self.assertEqual(signed_settled_cash_budget(doc),Decimal("0"))
