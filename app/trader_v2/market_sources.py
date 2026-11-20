"""V2 Phase 2 read-only source-specific market normalization.

Never generate a bid/ask or timestamp from last price or receipt time.
These snapshots are diagnostics, NOT authority to submit an order or an
exchange-calendar substitute. All normalizers are pure and network-free.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import csv,io
from .models import AssetClass,MarketSnapshot,Candle,amount,utc,valid_symbol
from .readonly_adapters import private_json,money,time_seen

class MarketSourceError(ValueError):
    def __init__(self,code):
        super().__init__(code)
        self.code=code

def _time(value):
    if isinstance(value,bool):raise MarketSourceError("QUOTE_TIMESTAMP_INVALID")
    if isinstance(value,(int,float)):
        if value <= 0:raise MarketSourceError("QUOTE_TIMESTAMP_INVALID")
        if value>1_000_000_000_000:value=value/1000
        try:return datetime.fromtimestamp(value,timezone.utc)
        except (OverflowError,OSError,ValueError):raise MarketSourceError("QUOTE_TIMESTAMP_INVALID") from None
    if isinstance(value,str) and value:
        if value.isdigit():return _time(int(value))
        try:
            dt=datetime.fromisoformat(value.replace("Z","+00:00"))
            return utc(dt)
        except (ValueError,TypeError):pass
    raise MarketSourceError("QUOTE_TIMESTAMP_INVALID")

def _quote_amount(value):
    if isinstance(value,(list,tuple)):
        if not value:raise MarketSourceError("EXECUTABLE_PRICE_MISSING")
        value=value[0]
    if isinstance(value,dict):
        value=value.get("price")
    n=money(value)
    if n is None or n<=0:raise MarketSourceError("EXECUTABLE_PRICE_MISSING_OR_INVALID")
    return n

def _sourced_time(at,now,ttl=90):
    dt=_time(at)
    age=(now-dt).total_seconds()
    if not -2<=age<=ttl:
        raise MarketSourceError("EXCHANGE_QUOTE_STALE_OR_FUTURE")
    return dt

@dataclass(frozen=True)
class QuoteReading:
    symbol:str
    asset_class:AssetClass
    source:str
    observed_at:datetime
    received_at:datetime
    bid:Decimal
    ask:Decimal
    last:Decimal|None
    source_tradable:bool
    broker_executable:bool=False  # explicitly never proved by this read-only layer
    def __post_init__(self):
        valid_symbol(self.symbol)
        if not isinstance(self.asset_class,AssetClass) or not self.source:
            raise ValueError("Invalid source")
        for key in ("observed_at","received_at"):
            object.__setattr__(self,key,utc(getattr(self,key)))
        if (self.observed_at-self.received_at).total_seconds()>2:
            raise ValueError("Quote after receipt")
        for key in ("bid","ask"):
            object.__setattr__(self,key,amount(getattr(self,key),key,False))
        if self.ask<self.bid:raise ValueError("Crossed market")
        if self.last is not None:object.__setattr__(self,"last",amount(self.last,"last",False))
        if self.broker_executable:
            raise ValueError("Read-only market observations cannot declare execution authority")
    def to_inert_snapshot(self):
        """For display/diagnostics only; unverified market session cannot open orders."""
        if self.last is None:raise MarketSourceError("TRADE_LAST_UNVERIFIED")
        return MarketSnapshot(self.symbol,self.asset_class,self.source,
             self.observed_at,self.received_at,self.bid,self.ask,self.last,False)
    def public(self):
        return {"symbol":self.symbol,"source":self.source,
                "asset_class":self.asset_class.value,"observed_at":self.observed_at.isoformat(),
                "bid":str(self.bid),"ask":str(self.ask),
                "last":str(self.last) if self.last is not None else None,
                "source_tradable":self.source_tradable,
                "broker_executable":False,"market_session_verified":False}

def schwab_market_quote(document,symbol,*,now=None):
    now=utc(now or datetime.now(timezone.utc))
    valid_symbol(symbol)
    if (not isinstance(document,dict) or document.get("schema")!=1 or
            document.get("source")!="schwab_broker_quotes" or
            not isinstance(document.get("symbols"),dict)):
        raise MarketSourceError("SCHWAB_SOURCE_UNVERIFIED")
    # File collection time is NOT an exchange quote timestamp.
    received=_sourced_time(document.get("observed_at"),now)
    row=document["symbols"].get(symbol)
    if not isinstance(row,dict):raise MarketSourceError("SYMBOL_NOT_IN_SOURCE")
    observed=_sourced_time(row.get("quote_timestamp"),now)
    if observed>received+timedelta(seconds=2):raise MarketSourceError("QUOTE_AFTER_COLLECTION")
    bid=_quote_amount(row.get("bid"));ask=_quote_amount(row.get("ask"))
    last=_quote_amount(row.get("last")) if row.get("last") is not None else None
    return QuoteReading(symbol,AssetClass.STOCK,"schwab_broker_quotes",
                        observed,received,bid,ask,last,row.get("tradable") is True)

def webull_market_quote(payload,symbol,*,now=None):
    """Direct Webull SDK market response normalized without making an SDK call."""
    now=utc(now or datetime.now(timezone.utc));valid_symbol(symbol)
    if not isinstance(payload,dict) or payload.get("symbol")!=symbol:
        raise MarketSourceError("WEBULL_SYMBOL_UNVERIFIED")
    observed=_sourced_time(payload.get("quote_time") or payload.get("time") or
                           payload.get("timestamp"),now)
    def price(*names):
        for name in names:
            if name in payload:return _quote_amount(payload[name])
        raise MarketSourceError("EXECUTABLE_PRICE_MISSING")
    bid=price("bid","bid_price","bids","bid_list")
    ask=price("ask","ask_price","asks","ask_list")
    last=None
    for name in ("last","last_price","lastPrice","price"):
        if name in payload:
            last=_quote_amount(payload[name]);break
    return QuoteReading(symbol,AssetClass.STOCK,"webull_openapi",
                        observed,now,bid,ask,last,True)

def robinhood_market_quote(payload,symbol,*,now=None):
    """Signed Robinhood v2 best-bid-ask response; no guessed venue timestamp."""
    now=utc(now or datetime.now(timezone.utc));valid_symbol(symbol)
    rows=payload.get("results") if isinstance(payload,dict) else None
    if not isinstance(rows,list):raise MarketSourceError("ROBINHOOD_QUOTE_UNVERIFIED")
    matched=[x for x in rows if isinstance(x,dict) and x.get("symbol")==symbol]
    if len(matched)!=1:raise MarketSourceError("ROBINHOOD_SYMBOL_MISSING_OR_AMBIGUOUS")
    row=matched[0]
    # Robinhood's bid/ask endpoint may omit exchange time and last trade.
    # Do NOT substitute local poll time, midpoint, or a display-only CoinGecko mark.
    observed=_sourced_time(row.get("quote_timestamp") or row.get("timestamp") or
                           row.get("updated_at"),now)
    bid=_quote_amount(row.get("bid"));ask=_quote_amount(row.get("ask"))
    last=_quote_amount(row.get("last")) if row.get("last") is not None else None
    return QuoteReading(symbol,AssetClass.CRYPTO,"robinhood_signed_bid_ask",
                        observed,now,bid,ask,last,True)

def coinbase_cached_quote(payload,symbol,*,now=None):
    """Coinbase public WebSocket cache is non-executable Robinhood signal data."""
    now=utc(now or datetime.now(timezone.utc));valid_symbol(symbol)
    if not isinstance(payload,dict) or not isinstance(payload.get("quotes"),dict):
        raise MarketSourceError("COINBASE_CACHE_UNAVAILABLE")
    row=payload["quotes"].get(symbol)
    if not isinstance(row,dict):raise MarketSourceError("SYMBOL_NOT_IN_SOURCE")
    observed=_sourced_time(row.get("at"),now)
    bid=_quote_amount(row.get("bid"));ask=_quote_amount(row.get("ask"))
    # Coinbase mid is a bid/ask midpoint, NOT a last trade.
    return QuoteReading(symbol,AssetClass.CRYPTO,"coinbase_ws_cache",
                        observed,now,bid,ask,None,True)

def paper_candles_csv(path,symbol,*,now=None,count=60,max_age_seconds=3600):
    """Read recorded completed one-minute candles, not a last-price quote.

    The existing public paper collector writes OPEN timestamps from completed
    1m bars. V2 advances each timestamp by 60s to represent its close.
    """
    now=utc(now or datetime.now(timezone.utc));valid_symbol(symbol)
    if not 1<=count<=240:raise ValueError("Invalid replay window")
    path=Path(path)
    try:
        if path.is_symlink() or path.stat().st_size>32000:
            raise MarketSourceError("PAPER_REPLAY_SOURCE_UNSAFE")
        raw=path.read_text(encoding="utf-8")
        reader=csv.DictReader(io.StringIO(raw))
        if reader.fieldnames!=["timestamp","symbol","price"]:
            raise MarketSourceError("PAPER_REPLAY_SCHEMA_INVALID")
        rows=list(reader)
        if len(rows)>240:raise MarketSourceError("PAPER_REPLAY_SOURCE_OVERSIZE")
    except (OSError,UnicodeError):
        raise MarketSourceError("PAPER_REPLAY_UNAVAILABLE") from None
    collected=[]
    seen=set()
    for row in rows:
        if row.get("symbol")!=symbol:continue
        if any(k not in row for k in ("timestamp","symbol","price")):
            raise MarketSourceError("PAPER_REPLAY_SCHEMA_INVALID")
        open_at=_time(row["timestamp"])
        close_at=open_at+timedelta(minutes=1)
        age=(now-close_at).total_seconds()
        if not 0<=age<=max_age_seconds:
            continue  # no unclosed or stale candle reaches the controller
        if close_at in seen:raise MarketSourceError("DUPLICATE_CANDLE")
        seen.add(close_at)
        price=_quote_amount(row["price"])
        collected.append(Candle(symbol,close_at,price,closed=True))
    return sorted(collected,key=lambda x:x.observed_at)[-count:]

def cached_market_status(state_dir,*,now=None):
    """Read-only coverage summary; no quote API calls or credential refresh."""
    from .readonly_adapters import private_json
    now=utc(now or datetime.now(timezone.utc));root=Path(state_dir)
    schwab=private_json(root/"live/broker_market_snapshot.json",maximum=30000)
    coinbase=private_json(root/"robinhood/coinbase_market.json",maximum=3000000)
    probe=private_json(root/"webull/stock_api_probe.json",maximum=20000)
    counts={"schwab":{"state":"NO_FRESH_QUOTE","symbols":0},
            "webull":{"state":"QUOTE_UNVERIFIED","symbols":0},
            "robinhood_crypto":{"state":"NO_FRESH_QUOTE","symbols":0},
            "paper":{"state":"RECORDED_CANDLES_ONLY","symbols":0}}
    if schwab and isinstance(schwab.get("symbols"),dict):
        good=0
        for s in tuple(schwab["symbols"])[:100]:
            try:schwab_market_quote(schwab,s,now=now);good+=1
            except (MarketSourceError,ValueError):pass
        counts["schwab"]={"state":"FRESH_READ_ONLY" if good else "NO_FRESH_QUOTE","symbols":good}
    if coinbase and isinstance(coinbase.get("quotes"),dict):
        good=0
        for s in tuple(coinbase["quotes"])[:250]:
            try:coinbase_cached_quote(coinbase,s,now=now);good+=1
            except (MarketSourceError,ValueError):pass
        counts["robinhood_crypto"]={"state":"FRESH_EXTERNAL_SIGNAL_ONLY" if good else "NO_FRESH_QUOTE",
                                    "symbols":good}
    if probe:
        checked=probe.get("checked_at")
        if time_seen(checked,now):
            state=probe.get("state")
            counts["webull"]["state"]=(
                "BROKER_ENDPOINTS_AUTHORIZED_NO_QUOTE_CACHE"
                if state=="ALL_STOCK_ENDPOINTS_AUTHORIZED"
                else "BROKER_ENDPOINTS_PARTIAL_OR_RESTRICTED")
    return counts
