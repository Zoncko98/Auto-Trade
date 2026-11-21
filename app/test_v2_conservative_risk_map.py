"""Contract tests for V1 risk budgets translated into non-authorizing V2."""
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import json
from trader_v2.models import Account,Capability,AssetClass
from trader_v2.conservative_risk_map import mapping


class ConservativeMappingTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def write(self,broker,config):
        path={
            "schwab":"live/risk_settings.json",
            "webull":"webull/risk_plan.json",
            "robinhood_crypto":"robinhood/risk_policy.json",
        }[broker]
        f=self.root/path
        f.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        f.write_text(json.dumps(config))
        f.chmod(0o600)
        return f

    def account(self,broker,cash="100",equity="200",exposure="10"):
        return Account("acct-"+broker,broker,
            Capability(frozenset({AssetClass.CRYPTO if broker=="robinhood_crypto" else AssetClass.STOCK})),
            D(cash),D(equity),{},trading_enabled=True,
            market_exposure=D(exposure))

    def robinhood(self):
        return self.write("robinhood_crypto",{
            "enabled":True,"max_order_usd":"5",
            "max_total_exposure_usd":"25","max_daily_loss_usd":"5",
            "max_open_positions":3,"max_single_asset_exposure_pct":"60",
            "min_add_interval_minutes":30,"min_hold_minutes":15,
            "min_profit_pct":"1.0","take_profit_pct":"3",
            "trailing_activation_pct":"2","trailing_drawdown_pct":"0.75",
            "stop_loss_pct":"2","fee_buffer_pct":"0.25",
            "reentry_cooldown_minutes":30})

    def webull(self):
        return self.write("webull",{
            "max_position_pct":5.0,"max_order_usd":100.0,
            "max_daily_loss_usd":25.0,"max_open_positions":3})

    def schwab(self):
        return self.write("schwab",{"version":1,"settings":{
            "strategy_capital_usd":100.0,"allocation_pct":50.0,
            "max_order_usd":30.0,"max_position_pct":5.0,
            "max_daily_loss":10.0,"max_open_positions":3,
            "max_buys_per_day":4,"max_orders_per_day":6,
            "max_exit_orders_per_day":5,"daily_growth_target_pct":1.0}})

    def test_unavailable_private_source_does_not_write_or_grant(self):
        before=list(self.root.rglob("*"))
        for broker in ("schwab","webull","robinhood_crypto"):
            row=mapping(self.root,broker)
            self.assertEqual(row["state"],"PRIVATE_RISK_FILE_UNAVAILABLE")
            self.assertIsNone(row["policy"])
            self.assertFalse(row["v2_live_order_authorized"])
        self.assertEqual(list(self.root.rglob("*")),before)

    def test_incorrect_source_permissions_fail_closed(self):
        f=self.webull()
        f.chmod(0o644)
        self.assertEqual(mapping(self.root,"webull")["state"],
                         "PRIVATE_RISK_FILE_UNAVAILABLE")

    def test_robinhood_saved_policy_needs_broker_account_and_other_controls(self):
        self.robinhood()
        no_sign=mapping(self.root,"robinhood_crypto")
        self.assertEqual(no_sign["state"],"SAVED_V1_NUMERIC_LIMITS_VALIDATED")
        self.assertIsNone(no_sign["policy"])
        row=mapping(self.root,"robinhood_crypto",
            self.account("robinhood_crypto","30","100"),
            signed_account_verified=True)
        self.assertEqual(row["state"],"CONSERVATIVE_STRUCTURAL_MAPPING_ONLY")
        policy=row["policy"]
        self.assertEqual(policy.max_order_notional,D("5"))
        self.assertEqual(policy.max_total_exposure,D("25"))
        self.assertEqual(policy.max_position_fraction,D("0.15"))
        self.assertEqual(policy.max_daily_loss,D("5"))
        self.assertEqual(policy.max_entries_per_day,1)
        self.assertEqual(policy.ai_mode,"REQUIRED")
        self.assertFalse(row["v2_live_order_authorized"])
        self.assertIn("V1_AI_AND_EXIT_POLICY_PARITY",row["unmapped_controls"])

    def test_webull_enforces_25pct_cash_allocation_and_live_hard_caps(self):
        self.webull()
        row=mapping(self.root,"webull",self.account("webull","200","300"),
                    signed_account_verified=True)
        self.assertEqual(row["state"],"CONSERVATIVE_STRUCTURAL_MAPPING_ONLY")
        policy=row["policy"]
        self.assertEqual(policy.max_order_notional,D("50"))
        self.assertEqual(policy.max_total_exposure,D("75"))
        self.assertEqual(policy.max_position_fraction,D("0.05"))
        self.assertEqual(policy.cash_reserve,D("150"))
        self.assertEqual(policy.max_open_positions,3)
        self.assertFalse(row["v2_live_order_authorized"])

    def test_schwab_preserves_strategy_capital_allocation_and_entry_exit_limits(self):
        self.schwab()
        row=mapping(self.root,"schwab",self.account("schwab","100","200"),
                    signed_account_verified=True)
        self.assertEqual(row["state"],"CONSERVATIVE_STRUCTURAL_MAPPING_ONLY")
        p=row["policy"]
        self.assertEqual(p.max_order_notional,D("30"))
        self.assertEqual(p.max_total_exposure,D("100"))
        self.assertEqual(p.max_position_fraction,D("0.025"))
        self.assertEqual(p.cash_reserve,D("50"))
        self.assertEqual(p.max_entries_per_day,4)
        self.assertEqual(p.max_exit_orders_per_day,5)
        self.assertEqual(p.max_daily_loss,D("10"))

    def test_mismatched_or_unsigned_account_never_maps_to_authority(self):
        self.robinhood()
        foreign=self.account("schwab")
        item=mapping(self.root,"robinhood_crypto",foreign,signed_account_verified=True)
        self.assertEqual(item["state"],"SIGNED_BROKER_ACCOUNT_OR_EQUITY_REQUIRED")
        self.assertIsNone(item["policy"])

    def test_missing_robinhood_cooldown_rejected_not_dropped(self):
        path=self.robinhood()
        data=json.loads(path.read_text())
        data.pop("min_hold_minutes")
        path.write_text(json.dumps(data))
        self.assertEqual(mapping(self.root,"robinhood_crypto")["state"],
                         "V1_ROBINHOOD_STRATEGY_GUARD_MISSING")

    def test_webull_over_hard_cap_fails_closed(self):
        self.webull()
        path=self.root/"webull/risk_plan.json"
        data=json.loads(path.read_text())
        data["max_order_usd"]=2000
        path.write_text(json.dumps(data))
        self.assertEqual(mapping(self.root,"webull")["state"],
                         "V1_WEBULL_HARD_LIMIT_EXCEEDED")


if __name__=="__main__":
    main()
