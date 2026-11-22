"""Broker-specific V1 protective-exit compatibility boundaries for V2.

Pure rule evaluations, no broker requests or writes. Inputs must be backed by
independently signed V1/V2 fills and current signed broker quotes; missing
provenance fails closed. This is a building block, NOT full entry/exit parity.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from .models import MarketSnapshot, AssetClass, utc, amount
from .live_pipeline import SIGNED_SOURCES


class ExitParityUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _n(value,name,*,zero=False):
    try:
        return amount(value,name,zero)
    except (ValueError,TypeError):
        raise ExitParityUnavailable("V2_EXIT_"+name.upper()+"_UNVERIFIED") from None


@dataclass(frozen=True)
class ManagedExitLot:
    symbol:str
    quantity:Decimal
    signed_available_quantity:Decimal
    cost_basis:Decimal
    opened_at:datetime
    high_water_bid:Decimal|None=None
    cost_basis_broker_verified:bool=False
    original_fills_reconciled:bool=False
    same_day_filled_buy:bool=False
    def __post_init__(self):
        from .models import valid_symbol
        valid_symbol(self.symbol)
        for key in ("quantity","cost_basis","signed_available_quantity"):
            object.__setattr__(self,key,_n(getattr(self,key),key,zero=(key=="signed_available_quantity")))
        object.__setattr__(self,"opened_at",utc(self.opened_at))
        if self.high_water_bid is not None:
            object.__setattr__(self,"high_water_bid",_n(self.high_water_bid,"high_water_bid"))
        if (type(self.cost_basis_broker_verified) is not bool or
            type(self.original_fills_reconciled) is not bool or
            type(self.same_day_filled_buy) is not bool):
            raise ExitParityUnavailable("V2_EXIT_LOT_FLAGS_UNVERIFIED")
        if self.quantity>self.signed_available_quantity:
            raise ExitParityUnavailable("V2_MANAGED_LOT_EXCEEDS_SIGNED_BROKER_AVAILABILITY")


@dataclass(frozen=True)
class ExitPolicy:
    broker:str
    stop_loss_pct:Decimal=Decimal("2")
    min_profit_pct:Decimal=Decimal("1")
    take_profit_pct:Decimal=Decimal("3")
    trailing_activation_pct:Decimal=Decimal("2")
    trailing_drawdown_pct:Decimal=Decimal("0.75")
    min_hold_minutes:int=15
    sell_fee_pct:Decimal=Decimal("0.25")
    stop_reference_fee_pct:Decimal=Decimal("0.25")
    def __post_init__(self):
        if self.broker not in SIGNED_SOURCES:
            raise ExitParityUnavailable("V2_EXIT_BROKER_UNVERIFIED")
        for key in ("stop_loss_pct","min_profit_pct","take_profit_pct",
                    "trailing_activation_pct","trailing_drawdown_pct"):
            object.__setattr__(self,key,_n(getattr(self,key),key))
        for key in ("sell_fee_pct","stop_reference_fee_pct"):
            object.__setattr__(self,key,_n(getattr(self,key),key,zero=True))
        if (type(self.min_hold_minutes) is not int or
            not 1<=self.min_hold_minutes<=1440 or
            self.sell_fee_pct>Decimal("20") or
            self.stop_reference_fee_pct>Decimal("20") or
            self.take_profit_pct<self.min_profit_pct or
            self.trailing_activation_pct<self.min_profit_pct+self.trailing_drawdown_pct):
            raise ExitParityUnavailable("V2_EXIT_POLICY_CONTRADICTORY")
        if self.broker=="webull" and (
              self.stop_loss_pct!=2 or self.min_profit_pct!=1 or
              self.take_profit_pct!=3 or self.trailing_activation_pct!=2 or
              self.trailing_drawdown_pct!=Decimal("0.75") or
              self.min_hold_minutes!=15 or
              self.sell_fee_pct!=Decimal("0.25")):
            raise ExitParityUnavailable("WEBULL_V1_EXIT_CONSTANTS_DIFFER")


def exit_trigger(broker:str,lot:ManagedExitLot,quote:MarketSnapshot,
                 policy:ExitPolicy,*,now:datetime,technical_reversal=False):
    """Return V1-compatible protection reason, HOLD, or fail closed.

    The caller must still enforce the account's original risk policy, available
    settled inventory, all open orders, market session, writer lock, daily exit
    budget, and broker's actual order size/minimum before a SELL.
    """
    now=utc(now)
    if not isinstance(lot,ManagedExitLot) or not isinstance(policy,ExitPolicy) or (
          not isinstance(quote,MarketSnapshot) or
          broker not in SIGNED_SOURCES or policy.broker!=broker or
          quote.source not in SIGNED_SOURCES[broker] or
          lot.symbol!=quote.symbol or
          quote.asset_class is not (AssetClass.CRYPTO if broker=="robinhood_crypto" else AssetClass.STOCK)):
        raise ExitParityUnavailable("V2_EXIT_BROKER_QUOTE_OR_SYMBOL_UNVERIFIED")
    if not lot.cost_basis_broker_verified or not lot.original_fills_reconciled:
        raise ExitParityUnavailable("V2_EXIT_MANAGED_COST_OR_RECEIPTS_UNVERIFIED")
    if type(technical_reversal) is not bool:
        raise ExitParityUnavailable("V2_EXIT_TECHNICAL_SIGNAL_UNVERIFIED")
    max_age=30 if broker=="robinhood_crypto" else 60
    max_spread=Decimal("0.005") if broker=="robinhood_crypto" else Decimal("0.02")
    if (lot.opened_at>now or not quote.market_open or quote.observed_at>now or
            (now-quote.observed_at).total_seconds()>max_age or
            quote.spread_fraction>max_spread):
        raise ExitParityUnavailable("V2_EXIT_SIGNED_MARKET_SNAPSHOT_INVALID")
    if broker=="schwab":
        # Existing V1 Schwab: no same-day exit of an acquired position,
        # and an authenticated 3/5-bar down-cross is mandatory. The historic
        # one-off SPYD liquidation needs separate explicit adoption approval.
        if lot.same_day_filled_buy:
            return "HOLD"
        return "V1_SCHWAB_BEARISH_CROSS" if technical_reversal else "HOLD"
    hold_minutes=Decimal(str((now-lot.opened_at).total_seconds()))/60
    hold_met=hold_minutes>=policy.min_hold_minutes
    net_price=quote.bid*(1-policy.sell_fee_pct/100)
    pnl=(net_price/lot.cost_basis-1)*100
    if broker=="webull":
        stop_hit=pnl<=-policy.stop_loss_pct
    else:
        legacy_price=quote.bid*(1-policy.stop_reference_fee_pct/100)
        stop_hit=(legacy_price/lot.cost_basis-1)*100<=-policy.stop_loss_pct
    if stop_hit:return "STOP_LOSS"
    if hold_met and pnl>=policy.take_profit_pct:return "TAKE_PROFIT"
    peak=lot.high_water_bid
    if peak is not None:
        peak=max(peak,quote.bid)
        peak_net=(peak*(1-policy.sell_fee_pct/100)/lot.cost_basis-1)*100
        drawdown=max(Decimal("0"),(1-quote.bid/peak)*100)
        if (hold_met and peak_net>=policy.trailing_activation_pct and
            drawdown>=policy.trailing_drawdown_pct and pnl>=policy.min_profit_pct):
            return "TRAILING_PROFIT"
    if technical_reversal and hold_met and pnl>=policy.min_profit_pct:
        return "PROFIT_REVERSAL"
    return "HOLD"
