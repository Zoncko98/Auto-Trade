"""Conservative V1-to-V2 account risk translation, never trading authorization.

A canonical broker Account must be independently authenticated before use.
This only maps numeric ceilings; unmapped exit/cooldown/session constraints
still prohibit V2 broker orders until separate acceptance checks exist.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from .models import Account,RiskPolicy
from .readonly_adapters import private_json

_FILES={
 "schwab":"live/risk_settings.json",
 "webull":"webull/risk_plan.json",
 "robinhood_crypto":"robinhood/risk_policy.json",
}

class RiskMappingUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _value(doc,key,upper=Decimal("1000000000"),*,zero=False):
    raw=doc.get(key)
    if isinstance(raw,bool) or not isinstance(raw,(str,int,float,Decimal)):
        raise RiskMappingUnavailable("V1_RISK_FIELD_UNVERIFIED")
    try:v=Decimal(str(raw))
    except (ValueError,TypeError,InvalidOperation):
        raise RiskMappingUnavailable("V1_RISK_FIELD_UNVERIFIED") from None
    if not v.is_finite() or v<0 or (v==0 and not zero) or v>upper:
        raise RiskMappingUnavailable("V1_RISK_FIELD_INVALID")
    return v


def _count(doc,key,upper=1000):
    v=doc.get(key)
    if type(v) is not int or not 1<=v<=upper:
        raise RiskMappingUnavailable("V1_RISK_COUNT_UNVERIFIED")
    return v


def mapping(state_dir,broker,account=None,*,signed_account_verified=False):
    """Return structural risk mapping; never a broker or live-order permission."""
    if broker not in _FILES:raise ValueError("Unknown account broker")
    result={"broker":broker,"source":_FILES[broker],
        "state":"V1_RISK_UNVERIFIED","v2_live_order_authorized":False,
        "broker_account_signed":False,"policy":None,
        "unmapped_controls":["BROKER_ORDER_RECONCILIATION",
          "SETTLED_FUNDING","MARKET_SESSION",
          "SIGNED_EXECUTABLE_QUOTE","EXCLUSIVE_V1_V2_HANDOFF",
          "V1_AI_AND_EXIT_POLICY_PARITY"]}
    cfg=private_json(Path(state_dir)/_FILES[broker],maximum=16000)
    if cfg is None:
        result["state"]="PRIVATE_RISK_FILE_UNAVAILABLE"
        return result
    if broker=="schwab":
        if cfg.get("version")!=1 or not isinstance(cfg.get("settings"),dict):
            result["state"]="V1_RISK_SCHEMA_UNVERIFIED"
            return result
        cfg=cfg["settings"]
    try:
        order=_value(cfg,"max_order_usd")
        daily=_value(cfg,"max_daily_loss" if broker=="schwab" else "max_daily_loss_usd")
        n=_count(cfg,"max_open_positions",100)
        if broker=="schwab":
            capital=_value(cfg,"strategy_capital_usd")
            allocation=_value(cfg,"allocation_pct",Decimal("100"),zero=True)/100
            pct=_value(cfg,"max_position_pct",Decimal("100"))/100
            buys=_count(cfg,"max_buys_per_day")
            orders=_count(cfg,"max_orders_per_day")
            if buys>orders:
                raise RiskMappingUnavailable("V1_SCHWAB_ORDER_LIMITS_CONTRADICT")
            exits=_count(cfg,"max_exit_orders_per_day") if "max_exit_orders_per_day" in cfg else 3
            if "max_exit_orders_per_day" not in cfg:
                legacy={"strategy_capital_usd","allocation_pct",
                    "max_order_usd","max_position_pct","max_daily_loss",
                    "max_open_positions","max_buys_per_day","max_orders_per_day",
                    "daily_growth_target_pct"}
                if set(cfg)!=legacy:
                    raise RiskMappingUnavailable("V1_EXIT_LIMIT_MISSING")
        elif broker=="webull":
            if order>1000 or daily>250 or n>10:
                raise RiskMappingUnavailable("V1_WEBULL_HARD_LIMIT_EXCEEDED")
            pct=_value(cfg,"max_position_pct",Decimal("10"))/100
            buys=1
            exits=1
        else:
            if order>25 or n>10:
                raise RiskMappingUnavailable("V1_ROBINHOOD_HARD_LIMIT_EXCEEDED")
            total=_value(cfg,"max_total_exposure_usd",Decimal("250"))
            if total<order:
                raise RiskMappingUnavailable("V1_TOTAL_EXPOSURE_LT_ORDER")
            pct=_value(cfg,"max_single_asset_exposure_pct",Decimal("100"))/100
            buys=1
            exits=1
            # Mandatory saved strategy-specific controls cannot be dropped
            # by the generic V2 risk model; keep them as explicit blockers.
            for k in ("min_add_interval_minutes","min_hold_minutes",
                      "min_profit_pct","take_profit_pct","trailing_activation_pct",
                      "trailing_drawdown_pct","stop_loss_pct","fee_buffer_pct",
                      "reentry_cooldown_minutes"):
                if k not in cfg:
                    raise RiskMappingUnavailable("V1_ROBINHOOD_STRATEGY_GUARD_MISSING")
    except RiskMappingUnavailable as exc:
        result["state"]=exc.code
        return result
    result["state"]="SAVED_V1_NUMERIC_LIMITS_VALIDATED"
    if not signed_account_verified:
        return result
    if (not isinstance(account,Account) or account.broker!=broker
        or not account.trading_enabled or account.equity<=0):
        result["state"]="SIGNED_BROKER_ACCOUNT_OR_EQUITY_REQUIRED"
        return result
    try:
        if broker=="schwab":
            effective_cap=min(capital,account.equity)
            total_exposure=effective_cap
            per_asset=effective_cap*pct
            order_cap=min(order,account.cash*allocation)
            reserve=account.cash*(1-allocation)
        elif broker=="webull":
            total_exposure=account.equity*Decimal("0.25")
            per_asset=account.equity*pct
            order_cap=min(order,account.cash*Decimal("0.25"))
            reserve=account.cash*Decimal("0.75")
        else:
            total_exposure=min(total,account.equity)
            per_asset=total*pct
            order_cap=order
            reserve=Decimal("0")
        ratio=min(Decimal("1"),per_asset/account.equity)
        if order_cap<=0 or total_exposure<=0 or ratio<=0:
            raise RiskMappingUnavailable("NO_VERIFIED_ACCOUNT_HEADROOM")
        # Round DOWN to the risk ceiling precision; never raise old limits.
        p=RiskPolicy(
            max_order_notional=order_cap.quantize(Decimal("0.000000000001"),rounding=ROUND_DOWN),
            max_total_exposure=total_exposure.quantize(Decimal("0.000000000001"),rounding=ROUND_DOWN),
            max_position_fraction=ratio.quantize(Decimal("0.000000000001"),rounding=ROUND_DOWN),
            cash_reserve=reserve.quantize(Decimal("0.000000000001"),rounding=ROUND_DOWN),
            max_daily_loss=daily,
            max_open_positions=n,
            max_entries_per_day=buys,
            max_exit_orders_per_day=exits,
            max_spread_fraction=Decimal("0.005"),
            max_snapshot_age_seconds=60,
            ai_mode="REQUIRED",
        )
    except (ValueError,TypeError,RiskMappingUnavailable) as exc:
        result["state"]="V2_RISK_TRANSLATION_UNAVAILABLE"
        return result
    result.update({
        "state":"CONSERVATIVE_STRUCTURAL_MAPPING_ONLY",
        "broker_account_signed":True,
        "policy":p,
    })
    return result
