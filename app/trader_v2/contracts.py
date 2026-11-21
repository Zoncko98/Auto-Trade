"""Canonical V2 contracts. No live-broker implementations are enabled in milestone one."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from .models import Account,AssetClass,AIReview,Candidate,Candle,MarketSnapshot,OrderIntent,amount,valid_id

@dataclass(frozen=True)
class BrokerExecution:
    key:str
    state:str
    broker_order_id:str
    filled_quantity:Decimal
    average_price:Decimal
    fees:Decimal
    def __post_init__(self):
        valid_id(self.key)
        if self.state not in ("BROKER_ACCEPTED","PARTIALLY_FILLED","FILLED","CANCELED","REJECTED"):
            raise ValueError("Unsupported broker receipt state")
        if (not isinstance(self.broker_order_id,str) or
                not 1<=len(self.broker_order_id)<=160 or
                any(ch.isspace() or ord(ch)<32 for ch in self.broker_order_id)):
            raise ValueError("Broker order identifier is invalid")
        for field in ("filled_quantity","average_price","fees"):
            object.__setattr__(self,field,amount(getattr(self,field),field))

@runtime_checkable
class TradingBroker(Protocol):
    """Write-capable protocol implemented only by SimulatedBroker in milestone one."""
    provider_id:str
    def account(self,account_id:str)->Account: ...
    def submit(self,intent:OrderIntent)->BrokerExecution: ...
    def find_order(self,key:str)->BrokerExecution|None: ...

@runtime_checkable
class MarketDataProvider(Protocol):
    def snapshot(self,symbol:str,asset_class:AssetClass)->MarketSnapshot: ...
    def candles(self,symbol:str,asset_class:AssetClass,count:int)->list[Candle]: ...

@runtime_checkable
class StrategyController(Protocol):
    strategy_id:str
    def candidate(self,account_id:str,candles:list[Candle])->Candidate|None: ...

@runtime_checkable
class AIReviewer(Protocol):
    def review(self,candidate:Candidate,snapshot:MarketSnapshot)->AIReview: ...

def inspect_paper_adapter(broker:TradingBroker,account_id:str)->Account:
    """Pure read-only contract check. Never calls order submission."""
    if not isinstance(broker,TradingBroker):raise TypeError("Missing V2 broker methods")
    account=broker.account(account_id)
    if not isinstance(account,Account) or account.broker != broker.provider_id:
        raise ValueError("Inconsistent broker account contract")
    return account
