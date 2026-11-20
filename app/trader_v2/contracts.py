"""Canonical V2 contracts. No live-broker implementations are enabled in milestone one."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from .models import Account,AssetClass,AIReview,Candidate,Candle,MarketSnapshot,OrderIntent

@dataclass(frozen=True)
class BrokerExecution:
    key:str
    state:str
    broker_order_id:str
    filled_quantity:Decimal
    average_price:Decimal
    fees:Decimal

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
