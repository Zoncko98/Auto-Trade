"""Effective V1 broker risk budget preview remains read-only and fail-closed."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json
from trader_v2.risk_envelopes import envelope

class RiskEnvelopesTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)

    def write(self,path,document):
        target=self.state/path
        target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        target.write_text(json.dumps(document),encoding="utf-8")
        target.chmod(0o600)
        return target

    def schwab_policy(self):
        return {"version":1,"revision":3,"settings":{
           "strategy_capital_usd":100.0,
           "allocation_pct":50.0,
           "max_order_usd":25.0,
           "max_position_pct":25.0,
           "max_daily_loss":5.0,
           "max_open_positions":3,
           "max_buys_per_day":3,
           "max_orders_per_day":7,
           "max_exit_orders_per_day":3,
           "daily_growth_target_pct":1.0}}
    def schwab_account(self):
        return {"broker":"schwab","auth":"CONNECTED","read_verified":True,
                "cash_usd":"80","equity_usd":"100","exposure_usd":"30"}

    def test_schwab_upper_bound_matches_v1_account_limits_without_order_rights(self):
        self.write("live/risk_settings.json",self.schwab_policy())
        d=envelope(self.state,"schwab",self.schwab_account())
        self.assertEqual(d["state"],"V1_BUDGET_UPPER_BOUND_OBSERVED")
        # min($80 * 50%=$40, max order=$25, $100 *25%=$25,
        #     strategy headroom=$70) = $25
        self.assertEqual(d["preliminary_budget_usd"],"25.00")
        self.assertEqual(d["position_budget_usd"],"25.00")
        self.assertEqual(d["max_exit_orders_per_day"],3)
        self.assertFalse(d["ready_to_submit"])
        self.assertFalse(d["v2_order_authorized"])
        self.assertFalse(d["verified_broker_order_limit"])
        self.assertFalse((self.state/"v2").exists())

    def test_existing_nine_field_schwab_risk_uses_explicit_v1_fallback(self):
        doc=self.schwab_policy()
        del doc["settings"]["max_exit_orders_per_day"]
        self.write("live/risk_settings.json",doc)
        result=envelope(self.state,"schwab",self.schwab_account())
        self.assertEqual(result["state"],"V1_BUDGET_UPPER_BOUND_OBSERVED")
        self.assertEqual(result["max_exit_orders_per_day"],3)
        self.assertEqual(result["exit_limit_source"],
                         "V1_LEGACY_VALIDATOR_DEFAULT_NOT_SAVED")
        self.assertFalse(result["ready_to_submit"])

    def test_schwab_zero_cash_allocation_never_shows_nonzero_budget(self):
        doc=self.schwab_policy()
        doc["settings"]["allocation_pct"]=0
        self.write("live/risk_settings.json",doc)
        d=envelope(self.state,"schwab",self.schwab_account())
        self.assertEqual(d["preliminary_budget_usd"],"0.00")

    def test_schwab_exposure_exhaustion_blocks_budget_despite_cash(self):
        self.write("live/risk_settings.json",self.schwab_policy())
        acc=self.schwab_account()
        acc["exposure_usd"]="100"
        d=envelope(self.state,"schwab",acc)
        self.assertEqual(d["preliminary_budget_usd"],"0.00")
        self.assertEqual(d["strategy_exposure_headroom_usd"],"0.00")

    def test_schwab_account_unverified_does_not_infer_current_cash(self):
        self.write("live/risk_settings.json",self.schwab_policy())
        doc=envelope(self.state,"schwab",{
            **self.schwab_account(),"read_verified":False})
        self.assertEqual(doc["state"],"ACCOUNT_OBSERVATION_REQUIRED")
        self.assertIsNone(doc["preliminary_budget_usd"])

    def test_webull_safeguards_25pct_cash_and_total_exposure(self):
        self.write("webull/risk_plan.json",{
           "max_position_pct":5.0,"max_order_usd":100.0,
           "max_daily_loss_usd":25.0,"max_open_positions":3})
        acc={"broker":"webull","auth":"CONNECTED","read_verified":True,
             "cash_usd":"200","equity_usd":"400","exposure_usd":"70",
             "entry_headroom_usd":"20","account_class":"CASH"}
        d=envelope(self.state,"webull",acc)
        # min(100, 200*.25=50, 400*.05=20,
        # 400*.25-70=30, worker 20) = 20
        self.assertEqual(d["preliminary_budget_usd"],"20.00")
        self.assertEqual(d["state"],"V1_BUDGET_UPPER_BOUND_OBSERVED")
        self.assertFalse(d["ready_to_submit"])
        acc["exposure_usd"]="125"
        self.assertEqual(envelope(self.state,"webull",acc)["preliminary_budget_usd"],"0.00")

    def test_webull_live_hard_limits_cannot_be_bypassed_by_source_file(self):
        self.write("webull/risk_plan.json",{
           "max_position_pct":25.0,"max_order_usd":2500.0,
           "max_daily_loss_usd":25.0,"max_open_positions":3})
        d=envelope(self.state,"webull",{"read_verified":True,"auth":"CONNECTED",
           "cash_usd":"500","equity_usd":"500","exposure_usd":"0"})
        self.assertEqual(d["state"],"RISK_SOURCE_INVALID")
        self.assertIsNone(d["preliminary_budget_usd"])

    def test_robinhood_buying_power_only_is_not_verified_cash_or_equity(self):
        self.write("robinhood/risk_policy.json",{
            "max_order_usd":"5","max_daily_loss_usd":"3",
            "max_open_positions":3,"max_total_exposure_usd":"20",
            "max_single_asset_exposure_pct":"50"})
        d=envelope(self.state,"robinhood_crypto",{
          "auth":"CONNECTED","read_verified":True,"buying_power_usd":"2"})
        self.assertEqual(d["state"],"PARTIAL_BROKER_HOLDINGS_UNVERIFIED")
        self.assertIsNone(d["preliminary_budget_usd"])
        self.assertEqual(d["buying_power_preliminary_ceiling_usd"],"2.00")
        self.assertFalse(d["verified_broker_order_limit"])
        self.assertFalse(d["v2_order_authorized"])

    def test_invalid_private_file_cannot_supply_risk(self):
        path=self.write("live/risk_settings.json",self.schwab_policy())
        path.chmod(0o644)
        self.assertEqual(envelope(self.state,"schwab",self.schwab_account())["state"],
                         "RISK_SOURCE_UNAVAILABLE")

    def test_nan_negatives_and_boolean_values_rejected(self):
        for invalid in ("NaN","-1",True,None):
            doc=self.schwab_policy()
            doc["settings"]["max_order_usd"]=invalid
            self.write("live/risk_settings.json",doc)
            with self.subTest(invalid=invalid):
                r=envelope(self.state,"schwab",self.schwab_account())
                self.assertEqual(r["state"],"RISK_SOURCE_INVALID")
                self.assertIsNone(r["preliminary_budget_usd"])

    def test_no_source_and_unknown_broker_never_authorize(self):
        self.assertFalse(envelope(self.state,"webull",{})["ready_to_submit"])
        with self.assertRaises(ValueError):
            envelope(self.state,"fake_broker",{})

if __name__=="__main__":main()
