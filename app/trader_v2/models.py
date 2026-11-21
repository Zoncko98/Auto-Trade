"""Validated canonical models. V2 monetary values are Decimal; timestamps require UTC context."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping
import re

_SYM=re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{0,31}$")
_ID=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,95}$")

def amount(v, name="amount", zero=True):
    if isinstance(v,(float,bool)) or not isinstance(v,(int,str,Decimal)):
        raise ValueError(name+" must be Decimal, integer or string")
    try: d=Decimal(str(v))
    except (InvalidOperation,TypeError,ValueError):raise ValueError("Invalid "+name) from None
    if not d.is_finite() or d<0 or (not zero and d==0) or d.adjusted()>14 or d.as_tuple().exponent < -12:
        raise ValueError("Invalid magnitude or precision for "+name)
    return d

def utc(t):
    if not isinstance(t,datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return t.astimezone(timezone.utc)

def valid_symbol(s):
    if not isinstance(s,str) or not _SYM.fullmatch(s):raise ValueError("Invalid normalized symbol")
    return s

def valid_id(s):
    if not isinstance(s,str) or not _ID.fullmatch(s):raise ValueError("Invalid identifier")
    return s

class AssetClass(str,Enum):
    STOCK="STOCK";CRYPTO="CRYPTO"
class AuthState(str,Enum):
    CONNECTED="CONNECTED";EXPIRING="EXPIRING";REAUTH_REQUIRED="REAUTH_REQUIRED"
    TEMPORARY_ERROR="TEMPORARY_ERROR";DISABLED="DISABLED"
class OrderSide(str,Enum):
    BUY="BUY";SELL="SELL"
class AIState(str,Enum):
    PASS="PASS";VETO="VETO";UNAVAILABLE="UNAVAILABLE";NOT_NEEDED="NOT_NEEDED"
class OrderState(str,Enum):
    PROPOSED="PROPOSED";RISK_APPROVED="RISK_APPROVED";INTENT_PERSISTED="INTENT_PERSISTED"
    SUBMITTING="SUBMITTING";BROKER_ACCEPTED="BROKER_ACCEPTED"
    PARTIALLY_FILLED="PARTIALLY_FILLED";FILLED="FILLED";CANCELED="CANCELED"
    REJECTED="REJECTED";UNKNOWN_REQUIRES_RECONCILIATION="UNKNOWN_REQUIRES_RECONCILIATION"
TERMINAL=frozenset({OrderState.FILLED,OrderState.CANCELED,OrderState.REJECTED})

@dataclass(frozen=True)
class Capability:
    asset_classes:frozenset[AssetClass]
    fractional:bool=False
    shorting:bool=False
    min_notional:Decimal=Decimal("1")
    quantity_increment:Decimal=Decimal("0.00000001")
    def __post_init__(self):
        if not self.asset_classes or any(not isinstance(x,AssetClass) for x in self.asset_classes):
            raise ValueError("Invalid asset capabilities")
        object.__setattr__(self,"min_notional",amount(self.min_notional,"minimum notional",False))
        object.__setattr__(self,"quantity_increment",amount(self.quantity_increment,
                                  "broker quantity increment",False))

@dataclass(frozen=True)
class Account:
    account_id:str
    broker:str
    capability:Capability
    cash:Decimal
    equity:Decimal
    positions:Mapping[str,Decimal]=field(default_factory=dict)
    auth:AuthState=AuthState.CONNECTED
    trading_enabled:bool=False
    market_exposure:Decimal=Decimal("0")
    def __post_init__(self):
        valid_id(self.account_id);valid_id(self.broker)
        if not isinstance(self.auth,AuthState) or not isinstance(self.capability,Capability):
            raise ValueError("Invalid account auth or capability")
        for k in ("cash","equity","market_exposure"):
            object.__setattr__(self,k,amount(getattr(self,k),k))
        if self.cash>self.equity+Decimal("0.01"):
            raise ValueError("Invalid account cash/equity")
        p=dict(self.positions)
        if len(p)>1000:raise ValueError("Too many positions")
        for s,v in p.items():valid_symbol(s);p[s]=amount(v,"position")
        object.__setattr__(self,"positions",p)

@dataclass(frozen=True)
class MarketSnapshot:
    symbol:str
    asset_class:AssetClass
    source:str
    observed_at:datetime
    received_at:datetime
    bid:Decimal
    ask:Decimal
    last:Decimal
    market_open:bool
    def __post_init__(self):
        valid_symbol(self.symbol);valid_id(self.source)
        if not isinstance(self.asset_class,AssetClass):raise ValueError("Invalid market asset class")
        for k in ("observed_at","received_at"):object.__setattr__(self,k,utc(getattr(self,k)))
        for k in ("bid","ask","last"):object.__setattr__(self,k,amount(getattr(self,k),k,False))
        if self.ask<self.bid or (self.observed_at-self.received_at).total_seconds()>2:
            raise ValueError("Invalid market chronology or crossed quote")
    @property
    def spread_fraction(self):return (self.ask-self.bid)/self.ask

@dataclass(frozen=True)
class Candle:
    symbol:str
    observed_at:datetime
    close:Decimal
    closed:bool=True
    def __post_init__(self):
        valid_symbol(self.symbol);object.__setattr__(self,"observed_at",utc(self.observed_at))
        object.__setattr__(self,"close",amount(self.close,"close",False))

@dataclass(frozen=True)
class Candidate:
    strategy:str
    version:str
    account_id:str
    symbol:str
    asset_class:AssetClass
    side:OrderSide
    signal_at:datetime
    evidence:Mapping[str,str]
    def __post_init__(self):
        valid_id(self.strategy);valid_id(self.account_id);valid_symbol(self.symbol)
        if not isinstance(self.version,str) or not 1<=len(self.version)<=32:raise ValueError("Invalid strategy version")
        if not isinstance(self.side,OrderSide) or not isinstance(self.asset_class,AssetClass):
            raise ValueError("Invalid signal")
        object.__setattr__(self,"signal_at",utc(self.signal_at))
        if not isinstance(self.evidence,Mapping) or not 1<=len(self.evidence)<=20 or any(
            not isinstance(k,str) or not isinstance(v,str) or len(k)>70 or len(v)>250
            for k,v in self.evidence.items()):
            raise ValueError("Missing or unbounded strategy evidence")

@dataclass(frozen=True)
class AIReview:
    state:AIState
    symbol:str
    reviewed_at:datetime
    expires_at:datetime
    model:str=""
    reason:str=""
    def __post_init__(self):
        valid_symbol(self.symbol)
        if not isinstance(self.state,AIState):raise ValueError("Invalid review state")
        object.__setattr__(self,"reviewed_at",utc(self.reviewed_at))
        object.__setattr__(self,"expires_at",utc(self.expires_at))
        if self.expires_at<self.reviewed_at or len(self.model)>96 or len(self.reason)>500:
            raise ValueError("Invalid AI review")

@dataclass(frozen=True)
class RiskPolicy:
    max_order_notional:Decimal=Decimal("25")
    max_total_exposure:Decimal=Decimal("100")
    max_position_fraction:Decimal=Decimal("0.25")
    cash_reserve:Decimal=Decimal("0")
    max_spread_fraction:Decimal=Decimal("0.005")
    max_daily_loss:Decimal=Decimal("5")
    max_open_positions:int=3
    max_entries_per_day:int=3
    max_exit_orders_per_day:int=10
    max_snapshot_age_seconds:int=90
    ai_mode:str="OFF"
    def __post_init__(self):
        for k in ("max_order_notional","max_total_exposure","max_daily_loss"):
            object.__setattr__(self,k,amount(getattr(self,k),k,False))
        for k in ("max_position_fraction","max_spread_fraction"):
            d=amount(getattr(self,k),k,False)
            if d>1:raise ValueError("Invalid fraction "+k)
            object.__setattr__(self,k,d)
        object.__setattr__(self,"cash_reserve",amount(self.cash_reserve,"cash_reserve"))
        if not (1<=self.max_open_positions<=100 and 1<=self.max_entries_per_day<=1000
                and 1<=self.max_exit_orders_per_day<=1000 and 1<=self.max_snapshot_age_seconds<=3600):
            raise ValueError("Invalid risk counts")
        if self.ai_mode not in ("OFF","OPTIONAL","REQUIRED"):raise ValueError("Invalid AI policy")

@dataclass(frozen=True)
class RiskDecision:
    code:str
    reason:str
    quantity:Decimal=Decimal("0")
    limit_price:Decimal=Decimal("0")
    effective_headroom:Decimal=Decimal("0")
    def __post_init__(self):
        if self.code not in ("PASS","ENTRY_BLOCKED","EXIT_BLOCKED") or not isinstance(self.reason,str) or len(self.reason)>180:
            raise ValueError("Invalid risk decision")
        for k in ("quantity","limit_price","effective_headroom"):
            object.__setattr__(self,k,amount(getattr(self,k),k))
        if self.code=="PASS" and (self.quantity<=0 or self.limit_price<=0):
            raise ValueError("PASS must have price and quantity")

@dataclass(frozen=True)
class OrderIntent:
    key:str
    account_id:str
    strategy:str
    symbol:str
    asset_class:AssetClass
    side:OrderSide
    quantity:Decimal
    limit_price:Decimal
    proposed_at:datetime
    def __post_init__(self):
        valid_id(self.key);valid_id(self.account_id);valid_id(self.strategy);valid_symbol(self.symbol)
        if not isinstance(self.asset_class,AssetClass) or not isinstance(self.side,OrderSide):
            raise ValueError("Invalid order intent class/side")
        object.__setattr__(self,"quantity",amount(self.quantity,"quantity",False))
        object.__setattr__(self,"limit_price",amount(self.limit_price,"limit price",False))
        object.__setattr__(self,"proposed_at",utc(self.proposed_at))
