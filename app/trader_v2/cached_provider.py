"""Read-only cached V2 MarketDataProvider bridge; never calls broker SDKs.

Market snapshots remain inert (market_open=False) until independent
session/entitlement, broker price and account-specific cutover checks.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from .models import AssetClass,utc
from .market_sources import (
 MarketSourceError,schwab_market_quote,coinbase_cached_quote,paper_candles_csv)
from .readonly_adapters import private_json

class CachedMarketDataProvider:
    def __init__(self,state_dir,*,replay_csv=None):
        self.state=Path(state_dir)
        self.replay_csv=Path(replay_csv) if replay_csv else None

    def quote(self,symbol,asset_class,*,now=None):
        now=utc(now or datetime.now(timezone.utc))
        if not isinstance(asset_class,AssetClass):
            raise ValueError("Normalized asset class required")
        if asset_class is AssetClass.STOCK:
            doc=private_json(self.state/"live/broker_market_snapshot.json",maximum=30000)
            return schwab_market_quote(doc,symbol,now=now)
        if asset_class is AssetClass.CRYPTO:
            doc=private_json(self.state/"robinhood/coinbase_market.json",maximum=3000000)
            return coinbase_cached_quote(doc,symbol,now=now)
        raise MarketSourceError("UNSUPPORTED_ASSET")

    def snapshot(self,symbol,asset_class):
        # Never claim a verified exchange session or broker executable fill.
        return self.quote(symbol,asset_class).to_inert_snapshot()

    def candles(self,symbol,asset_class,count):
        if not isinstance(asset_class,AssetClass):
            raise ValueError("Normalized asset class required")
        if self.replay_csv is None:
            raise MarketSourceError("PAPER_REPLAY_NOT_CONFIGURED")
        return paper_candles_csv(self.replay_csv,symbol,count=count)
