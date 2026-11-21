"""Source-faithful, non-authorizing V1 risk-envelope previews for V2 cutover.

Only reads private on-disk settings and already-verified V1 broker snapshots.
Provides USD budget upper bounds, not order-ready limits or V2 permissions.
Broker-specific cash/settlement, market sessions, fees, and order minimums
remain outside V2 until their adapters prove them.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .readonly_adapters import private_json

_BROKERS={"schwab","webull","robinhood_crypto"}
_FILES={
    "schwab":"live/risk_settings.json",
    "webull":"webull/risk_plan.json",
    "robinhood_crypto":"robinhood/risk_policy.json",
}

def _positive(doc,key,*,allow_zero=False):
    value=doc.get(key)
    if isinstance(value,bool) or not isinstance(value,(int,float,str,Decimal)):
        raise ValueError("RISK_SOURCE_FIELD_UNVERIFIED")
    try: number=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError("RISK_SOURCE_FIELD_UNVERIFIED") from None
    if not number.is_finite() or number<0 or (number==0 and not allow_zero) or number>1_000_000_000:
        raise ValueError("RISK_SOURCE_FIELD_UNVERIFIED")
    return number

def _count(doc,key):
    value=doc.get(key)
    if type(value) is not int or not 1<=value<=1000:
        raise ValueError("RISK_COUNT_UNVERIFIED")
    return value

def _p(v):
    return str(v.quantize(Decimal("0.01")))

def _observation_decimal(account,key):
    value=account.get(key)
    if value is None or isinstance(value,bool):
        raise ValueError("ACCOUNT_VALUE_UNVERIFIED")
    try: d=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError("ACCOUNT_VALUE_UNVERIFIED") from None
    if not d.is_finite() or d<0 or d>1_000_000_000:
        raise ValueError("ACCOUNT_VALUE_UNVERIFIED")
    return d

def envelope(state_dir,broker,account):
    if broker not in _BROKERS:
        raise ValueError("UNKNOWN_BROKER_RISK_MAPPING")
    base={"broker":broker,"source":_FILES[broker],
          "state":"RISK_SOURCE_UNAVAILABLE",
          "v2_order_authorized":False,"ready_to_submit":False,
          "verified_broker_order_limit":False,
          "preliminary_budget_usd":None,
          "requested_order_ceiling_usd":None,
          "unmapped_requirements":[
              "BROKER_EXECUTABLE_QUOTE_AND_SESSION",
              "FULL_BROKER_POSITION_AND_SETTLEMENT_RECONCILIATION",
              "BROKER_MINIMUM_AND_DUPLICATE_ORDER_GATES",
              "V1_TO_V2_WRITER_HANDOFF"],
          }
    doc=private_json(Path(state_dir)/_FILES[broker],maximum=16000)
    if not doc:return base
    if broker=="schwab":
        if doc.get("version")!=1 or not isinstance(doc.get("settings"),dict):
            return {**base,"state":"RISK_SCHEMA_UNVERIFIED"}
        config=doc["settings"]
    else:config=doc
    try:
        requested=_positive(config,"max_order_usd")
        day_loss=_positive(config,"max_daily_loss" if broker=="schwab"
                           else "max_daily_loss_usd")
        positions=_count(config,"max_open_positions")
        result={**base,"requested_order_ceiling_usd":_p(requested),
                "max_daily_loss_usd":_p(day_loss),
                "max_open_positions":positions,
                "source_state":"SAVED_V1_POLICY_NOT_EXECUTION_AUTHORITY"}
        if broker=="schwab":
            capital=_positive(config,"strategy_capital_usd")
            pos_pct=_positive(config,"max_position_pct")
            allocation=_positive(config,"allocation_pct",allow_zero=True)
            buy_count=_count(config,"max_buys_per_day")
            total_count=_count(config,"max_orders_per_day")
            legacy_nine={"strategy_capital_usd","allocation_pct",
                "max_order_usd","max_position_pct","max_daily_loss",
                "max_open_positions","max_buys_per_day","max_orders_per_day",
                "daily_growth_target_pct"}
            if "max_exit_orders_per_day" not in config and set(config)==legacy_nine:
                # Matches live_extension.validate_risk's explicit documented
                # legacy fallback, not an invented user-saved control.
                exit_count=3
                exit_source="V1_LEGACY_VALIDATOR_DEFAULT_NOT_SAVED"
            else:
                exit_count=_count(config,"max_exit_orders_per_day")
                exit_source="V1_SAVED_RISK_POLICY"
            if pos_pct>100 or allocation>100 or total_count<buy_count:
                raise ValueError("INVALID_SCHWAB_SOURCE_LIMITS")
            result.update({
              "max_entries_per_day":buy_count,
              "max_orders_per_day":total_count,
              "max_exit_orders_per_day":exit_count,
              "exit_limit_source":exit_source,
              "saved_position_pct":str(pos_pct),
              "saved_cash_allocation_pct":str(allocation),
              "saved_strategy_capital_usd":_p(capital),
            })
        elif broker=="webull":
            pos_pct=_positive(config,"max_position_pct")
            if pos_pct>10 or requested>1000 or day_loss>250 or positions>10:
                raise ValueError("WEBULL_RISK_OUTSIDE_LIVE_HARD_LIMITS")
            result["saved_position_pct"]=str(pos_pct)
            result["unmapped_requirements"].append(
                "WEBULL_MARGIN_CASH_FUNDING_AND_ENTRY_COUNT")
        else:
            total=_positive(config,"max_total_exposure_usd")
            pct=_positive(config,"max_single_asset_exposure_pct")
            if pct>100 or total<requested:
                raise ValueError("INVALID_ROBINHOOD_RISK_CAPS")
            result.update({
                "max_total_exposure_usd":_p(total),
                "saved_single_asset_pct_of_exposure":str(pct),
            })
            result["unmapped_requirements"].append(
                "ROBINHOOD_POSITION_LOTS_COOLDOWNS_AND_BROKER_MINIMUMS")
    except ValueError:
        return {**base,"state":"RISK_SOURCE_INVALID"}
    if not isinstance(account,dict) or account.get("read_verified") is not True or account.get("auth")!="CONNECTED":
        result["state"]="ACCOUNT_OBSERVATION_REQUIRED"
        return result
    try:
        if broker=="schwab":
            cash=_observation_decimal(account,"cash_usd")
            equity=_observation_decimal(account,"equity_usd")
            exposure=_observation_decimal(account,"exposure_usd")
            if cash>equity:
                raise ValueError("ACCOUNT_CASH_GT_EQUITY")
            capital=min(equity,capital)
            position_budget=capital*pos_pct/Decimal("100")
            discretionary=min(
                cash*allocation/Decimal("100"),requested,position_budget)
            headroom=max(Decimal("0"),capital-exposure)
            budget=max(Decimal("0"),min(discretionary,headroom))
            result.update({
                "state":"V1_BUDGET_UPPER_BOUND_OBSERVED",
                "preliminary_budget_usd":_p(budget),
                "effective_strategy_capital_usd":_p(capital),
                "strategy_exposure_headroom_usd":_p(headroom),
                "position_budget_usd":_p(position_budget),
                "budget_source":"V1_SCHWAB_VERIFIED_CASH_EQUITY_EXPOSURE",
            })
        elif broker=="webull":
            cash=_observation_decimal(account,"cash_usd")
            equity=_observation_decimal(account,"equity_usd")
            exposure=_observation_decimal(account,"exposure_usd")
            if cash>equity:
                raise ValueError("ACCOUNT_CASH_GT_EQUITY")
            headroom=max(Decimal("0"),equity*Decimal("0.25")-exposure)
            upper=min(requested,cash*Decimal("0.25"),equity*pos_pct/100,headroom)
            reported=account.get("entry_headroom_usd")
            if reported is not None:
                upper=min(upper,_observation_decimal(account,"entry_headroom_usd"))
            result.update({
                "state":"V1_BUDGET_UPPER_BOUND_OBSERVED",
                "preliminary_budget_usd":_p(max(Decimal("0"),upper)),
                "strategy_exposure_headroom_usd":_p(headroom),
                "budget_source":"V1_WEBULL_CASH_25PCT_AND_EXPOSURE_25PCT_LIMIT",
            })
            if "MARGIN" in str(account.get("account_class","")).upper():
                result["unmapped_requirements"].append(
                    "MARGIN_CASH_FUNDING_NEEDS_FRESH_BROKER_PROOF")
        else:
            buying_power=_observation_decimal(account,"buying_power_usd")
            asset_ceiling=total*pct/Decimal("100")
            result.update({
                "state":"PARTIAL_BROKER_HOLDINGS_UNVERIFIED",
                "preliminary_budget_usd":None,
                "buying_power_preliminary_ceiling_usd":_p(
                    min(requested,buying_power,asset_ceiling)),
                "budget_source":"ROBINHOOD_BUYING_POWER_ONLY_NOT_CASH_EQUITY",
            })
        # Never turn source evidence into broker approval; no order is
        # price-verified, account-mapped to V2, or reconciled here.
        return result
    except ValueError:
        return {**result,"state":"ACCOUNT_OBSERVATION_INVALID",
                "preliminary_budget_usd":None}
