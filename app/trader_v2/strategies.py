"""Pure versioned stock and crypto controllers using normalized closed candles.

These are deterministic baseline examples for replay, NOT calibrated or
approved profit-seeking live strategies.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from .models import AssetClass,Candidate,Candle,OrderSide

@dataclass(frozen=True)
class _CrossController:
    strategy_id:str
    asset_class:AssetClass
    short:int
    long:int
    version:str="baseline-1"
    def __post_init__(self):
        if not 2<=self.short<self.long<=100:raise ValueError("Invalid moving average periods")

    def candidate(self,account_id:str,candles:list[Candle])->Candidate|None:
        if not isinstance(candles,list) or len(candles)<self.long+1:
            return None
        recent=candles[-(self.long+1):]
        symbol=recent[-1].symbol
        if any(not isinstance(c,Candle) or c.symbol!=symbol or not c.closed for c in recent):
            return None
        times=[x.observed_at for x in recent]
        if sorted(set(times))!=times:
            return None
        closes=[x.close for x in recent]
        def avg(a):return sum(a,Decimal("0"))/Decimal(len(a))
        previous_short=avg(closes[-self.short-1:-1])
        previous_long=avg(closes[-self.long-1:-1])
        current_short=avg(closes[-self.short:])
        current_long=avg(closes[-self.long:])
        side=None
        if previous_short<=previous_long and current_short>current_long:
            side=OrderSide.BUY
        elif previous_short>=previous_long and current_short<current_long:
            side=OrderSide.SELL
        indicator="SMA_CROSS"
        continuation_momentum=None
        if side is None and self.asset_class is AssetClass.STOCK and (
                getattr(self,"include_continuation",False) is True):
            # V1 Schwab + Webull permit moderate 3-completed-bar
            # continuation ONLY after the normal cross is HOLD. The legacy
            # quote ranking, liquidity, AI and session filters remain separate.
            tail=closes[-4:]
            if all(tail[i]>tail[i-1] for i in range(1,4)):
                momentum=(tail[-1]/tail[0]-1)*100
                if Decimal("0.4")<=momentum<=Decimal("2"):
                    side=OrderSide.BUY
                    indicator="M5_TREND_CONTINUATION"
                    continuation_momentum=momentum
        if side is None:return None
        evidence={"indicator":indicator,"short_period":str(self.short),
                    "long_period":str(self.long),"previous_short":str(previous_short),
                    "previous_long":str(previous_long),"current_short":str(current_short),
                    "current_long":str(current_long)}
        if continuation_momentum is not None:
            evidence["momentum_pct"]=str(continuation_momentum)
        return Candidate(strategy=self.strategy_id,version=self.version,
          account_id=account_id,symbol=symbol,asset_class=self.asset_class,
          side=side,signal_at=recent[-1].observed_at,evidence=evidence)

class StockController(_CrossController):
    def __init__(self,short=3,long=5,*,include_continuation=False):
        super().__init__("stock_sma",AssetClass.STOCK,short,long)
        object.__setattr__(self,"include_continuation",include_continuation is True)

class CryptoController(_CrossController):
    def __init__(self,short=4,long=8):
        super().__init__("crypto_sma",AssetClass.CRYPTO,short,long)
