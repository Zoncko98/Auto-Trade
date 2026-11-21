"""Deterministic fee-adjusted *shadow* reward test for V2 crypto BUY signals.

This is evidence only: it cannot approve, reject, delay, or size paper/live
orders. Prior observed candle resistance is NOT a forecast, and a public
Coinbase indicative spread is NOT a Robinhood broker-executable spread.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from .models import AssetClass, Candle, Candidate, MarketSnapshot, OrderSide, amount, utc

LOOKBACK = 20
FEE_BPS = Decimal("5")  # existing V2 SimulatedBroker model, per side
SLIPPAGE_BPS = Decimal("5")  # existing model, per side
MIN_NET_PCT = Decimal("0.50")  # illustrative target, NOT a trading policy
MAX_SPREAD_PCT = Decimal("0.50")  # matches V2 default risk spread upper bound

def _out(state, **fields):
    return {
        "state": state,
        "mode": "ADVISORY_COUNTERFACTUAL_ONLY",
        "changed_execution": False,
        "broker_executable": False,
        "live_order_authorized": False,
        "market_target_is_forecast": False,
        "fee_model": "V2_SIMULATOR_ASSUMPTIONS_NOT_BROKER_FEES",
        **fields,
    }

def _pct(d):
    return format(d.quantize(Decimal("0.001")), "f")

def assess(candidate: Candidate, quote: MarketSnapshot, candles: list[Candle], *,
           now: datetime, fee_bps=FEE_BPS,
           slippage_bps=SLIPPAGE_BPS, min_net_pct=MIN_NET_PCT) -> dict:
    """Evaluate only fee-adjusted hypothetical BUY potential, never control orders.

    Resistance is the highest *previously observed* closed 1-minute price
    in the trailing 20 completed bars before the signal bar; no future data.
    Entry assumes immediate ask plus configured slippage and buy fee.
    Exit at past resistance assumes the current bid/last ratio persists,
    then subtracts sell slippage and fee. This assumption can be wrong;
    therefore SHADOW_PASS is never approval or a profit prediction.
    """
    if not isinstance(candidate,Candidate) or not isinstance(quote,MarketSnapshot):
        return _out("EVIDENCE_UNAVAILABLE",reason="INVALID_CANDIDATE_OR_QUOTE")
    if candidate.side is OrderSide.SELL:
        return _out("EXIT_NOT_GATED",reason="NEVER_FILTER_RISK_REDUCING_EXITS")
    if candidate.side is not OrderSide.BUY or candidate.asset_class is not AssetClass.CRYPTO:
        return _out("EVIDENCE_UNAVAILABLE",reason="UNSUPPORTED_SHADOW_ASSET")
    now=utc(now)
    if (candidate.symbol!=quote.symbol or quote.asset_class is not AssetClass.CRYPTO
            or candidate.signal_at>now or abs((now-candidate.signal_at).total_seconds())>120):
        return _out("EVIDENCE_UNAVAILABLE",reason="IDENTITY_OR_SIGNAL_TIME_INVALID")
    age=(now-quote.observed_at).total_seconds()
    if age < -2 or age>90 or not quote.market_open:
        return _out("EVIDENCE_UNAVAILABLE",reason="QUOTE_STALE_OR_NOT_ACTIVE")
    if not isinstance(candles,list) or len(candles)<LOOKBACK+1:
        return _out("INSUFFICIENT_HISTORY",reason="REQUIRES_21_GENUINE_CLOSED_BARS")
    recent=candles[-(LOOKBACK+1):]
    if any(not isinstance(c,Candle) or not c.closed or c.symbol!=candidate.symbol
           for c in recent):
        return _out("EVIDENCE_UNAVAILABLE",reason="CANDLE_IDENTITY_INVALID")
    times=[c.observed_at for c in recent]
    if (times[-1]!=candidate.signal_at or
        any((b-a).total_seconds()!=60 for a,b in zip(times,times[1:])) or
        times[-1]>now or times[-1]<now-timedelta(seconds=120)):
        return _out("EVIDENCE_UNAVAILABLE",reason="CANDLE_GAP_OR_RECENCY_INVALID")
    try:
        fee=amount(fee_bps,"fee bps")
        slippage=amount(slippage_bps,"slippage bps")
        minimum=amount(min_net_pct,"net target")
    except ValueError:
        return _out("EVIDENCE_UNAVAILABLE",reason="INVALID_COST_ASSUMPTIONS")
    if fee>Decimal("100") or slippage>Decimal("100") or minimum>Decimal("20"):
        return _out("EVIDENCE_UNAVAILABLE",reason="COST_ASSUMPTIONS_EXCEED_BOUNDS")
    spread=(quote.ask-quote.bid)/quote.ask*Decimal("100")
    context={
        "model_fee_bps_per_side":str(fee),
        "model_slippage_bps_per_side":str(slippage),
        "minimum_hypothetical_net_pct":_pct(minimum),
        "observed_spread_pct":_pct(spread),
        "reference_candles":LOOKBACK,
        "reference_closed_at":recent[-2].observed_at.isoformat(),
    }
    if spread>MAX_SPREAD_PCT:
        return _out("SHADOW_REJECT_SPREAD",reason="PUBLIC_SPREAD_EXCEEDS_V2_SIM_LIMIT",**context)
    resistance=max(c.close for c in recent[:-1])
    # Repeat current observed spread at the earlier candle resistance. This is
    # intentionally a hypothetical scenario rather than a broker prediction.
    entry_cost=(quote.ask*(Decimal("1")+slippage/10000)*
                (Decimal("1")+fee/10000))
    exit_after_cost=(resistance*(quote.bid/quote.last)*
                     (Decimal("1")-slippage/10000)*
                     (Decimal("1")-fee/10000))
    net=(exit_after_cost/entry_cost-Decimal("1"))*100
    result={**context,
            "historical_resistance_close":str(resistance),
            "hypothetical_net_at_prior_high_pct":_pct(net)}
    if net>=minimum:
        return _out("SHADOW_PASS_PAST_RESISTANCE_ROOM",
                    reason="PAST_HIGH_HAS_HYPOTHETICAL_REWARD_AFTER_SIM_COSTS",
                    **result)
    return _out("SHADOW_REJECT_REWARD_AFTER_FEES",
                reason="PRIOR_HIGH_DOES_NOT_COVER_ASSUMED_COSTS_AND_TARGET",
                **result)
