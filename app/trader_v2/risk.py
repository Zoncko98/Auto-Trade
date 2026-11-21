"""Deterministic account-specific risk checks; exits independent of entry caps."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal,ROUND_DOWN,ROUND_UP
from .models import (Account,AssetClass,AuthState,Candidate,MarketSnapshot,
                     OrderSide,RiskPolicy,RiskDecision,utc)

def evaluate_risk(account:Account,candidate:Candidate,quote:MarketSnapshot,
                  policy:RiskPolicy,*,now:datetime,daily_realized_loss=Decimal("0"),
                  entries_today=0,exits_today=0,estimated_fee_bps=Decimal("10"))->RiskDecision:
    if not isinstance(account,Account) or not isinstance(candidate,Candidate) or not isinstance(quote,MarketSnapshot):
        raise TypeError("Validated account, candidate and market snapshot required")
    if not isinstance(policy,RiskPolicy):raise TypeError("RiskPolicy required")
    now=utc(now)
    side=candidate.side
    def blocked(reason):
        return RiskDecision("ENTRY_BLOCKED" if side is OrderSide.BUY else "EXIT_BLOCKED",reason)
    if candidate.account_id!=account.account_id:
        return blocked("ACCOUNT_MISMATCH")
    if candidate.symbol!=quote.symbol or candidate.asset_class!=quote.asset_class:
        return blocked("MARKET_SYMBOL_OR_CLASS_MISMATCH")
    if candidate.asset_class not in account.capability.asset_classes:
        return blocked("BROKER_ASSET_UNSUPPORTED")
    if account.auth is not AuthState.CONNECTED:
        return blocked("BROKER_REAUTH_OR_CONNECTION_REQUIRED")
    if not account.trading_enabled:
        return blocked("ACCOUNT_DISARMED")
    if account.capability.shorting:
        # This first V2 executor is deliberately cash/long only, regardless
        # of broader legacy broker capabilities.
        return blocked("V2_PAPER_ONLY_LONG")
    if not quote.market_open:
        return blocked("MARKET_SESSION_CLOSED")
    age=(now-quote.observed_at).total_seconds()
    if age< -2 or age>policy.max_snapshot_age_seconds:
        return blocked("QUOTE_STALE_OR_FUTURE")
    if quote.observed_at < candidate.signal_at:
        return blocked("QUOTE_PREDATES_SIGNAL")
    if quote.spread_fraction>policy.max_spread_fraction:
        return blocked("SPREAD_TOO_WIDE")
    if now<candidate.signal_at or (now-candidate.signal_at).total_seconds()>policy.max_snapshot_age_seconds:
        return blocked("SIGNAL_EXPIRED_OR_FUTURE")
    if type(entries_today) is not int or type(exits_today) is not int or min(entries_today,exits_today)<0:
        raise ValueError("Invalid order counters")
    from .models import amount
    fee_rate=amount(estimated_fee_bps,"estimated fee bps")/Decimal("10000")
    loss=amount(daily_realized_loss,"daily loss")
    held=account.positions.get(candidate.symbol,Decimal("0"))
    if side is OrderSide.SELL:
        # Entry counts, entry exposure and daily entry loss gates never skip
        # a valid risk-reducing exit. Broker/session/quote/held checks still apply.
        if exits_today>=policy.max_exit_orders_per_day:
            return blocked("EXIT_ORDER_LIMIT")
        if held<=0:return blocked("NO_LONG_HOLDING")
        price=(quote.bid*Decimal("0.995")).quantize(Decimal("0.00000001"),rounding=ROUND_DOWN)
        quantity=held
        if quantity*price<account.capability.min_notional:
            return blocked("BROKER_MINIMUM_EXIT_NOTIONAL")
        return RiskDecision("PASS","RISK_REDUCING_EXIT",quantity,price,account.cash)

    if loss>=policy.max_daily_loss:return blocked("DAILY_LOSS_LIMIT")
    if entries_today>=policy.max_entries_per_day:return blocked("ENTRY_DAILY_COUNT_LIMIT")
    if held<=0 and len([q for q in account.positions.values() if q>0])>=policy.max_open_positions:
        return blocked("OPEN_POSITION_LIMIT")
    cash_headroom=max(Decimal("0"),account.cash-policy.cash_reserve)
    strategy_headroom=max(Decimal("0"),policy.max_total_exposure-account.market_exposure)
    position_limit=account.equity*policy.max_position_fraction
    current_symbol_value=held*quote.ask
    position_headroom=max(Decimal("0"),position_limit-current_symbol_value)
    # Leave room for both marketable price slippage and simulated/executable fees.
    limit_price=(quote.ask*Decimal("1.005")).quantize(Decimal("0.00000001"),rounding=ROUND_UP)
    effective=min(policy.max_order_notional,strategy_headroom,position_headroom,
                  cash_headroom/(Decimal("1")+fee_rate))
    if effective<=0:return blocked("CASH_OR_EXPOSURE_EXHAUSTED")
    raw_quantity=effective/limit_price
    if account.capability.fractional:
        increment=account.capability.quantity_increment
        quantity=(raw_quantity/increment).to_integral_value(
            rounding=ROUND_DOWN)*increment
    else:
        quantity=raw_quantity.to_integral_value(rounding=ROUND_DOWN)
    if quantity<=0 or quantity*limit_price<account.capability.min_notional:
        return blocked("BROKER_MINIMUM_ORDER")
    return RiskDecision("PASS","CASH_AND_LIMITS_VERIFIED",
                        quantity,limit_price,effective)
