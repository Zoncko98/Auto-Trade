"""Direct signed stock candle adapters and genuine Coinbase minute-bar source.

Each candle is constructed from a provider-recorded COMPLETED interval.
No forward-fill, synthetic OHLC, replay-only snapshots or inferred session.
The caller separately verifies a current signed executable broker quote.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3,stat
from .models import Candle,amount,utc

class SignedCandleUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def _stock_rows(rows,symbol,now,*,source):
    if not isinstance(rows,list) or not 6<=len(rows)<=300:
        raise SignedCandleUnavailable("SIGNED_STOCK_CANDLE_HISTORY_UNAVAILABLE")
    now=utc(now)
    accepted={}
    for row in rows:
        if not isinstance(row,dict):
            raise SignedCandleUnavailable("SIGNED_STOCK_CANDLE_SCHEMA_INVALID")
        if row.get("trading_sessions") not in (None,"RTH"):
            continue
        try:
            if source=="schwab":
                raw=row["datetime"]
                if type(raw) is not int or raw%300000:
                    raise ValueError
                opened=datetime.fromtimestamp(raw/1000,timezone.utc)
            else:
                from webull_signals import _time
                opened=_time(row["time"])
                if opened.timestamp()%300!=0:
                    raise ValueError
            closed=opened+timedelta(minutes=5)
            price=amount(str(row["close"]),"signed stock close",False)
        except (TypeError,KeyError,ValueError,OverflowError):
            raise SignedCandleUnavailable("SIGNED_STOCK_CANDLE_FIELDS_UNVERIFIED") from None
        age=(now-closed).total_seconds()
        if age<-2 or (now-closed).total_seconds()<60:
            # Exclude the currently still-forming bar; do not use it as a
            # confirmed crossover. Future sources fail rather than vanish.
            if age<-2:
                raise SignedCandleUnavailable("SIGNED_STOCK_FUTURE_BAR")
            continue
        if age>14*86400:
            continue
        if closed in accepted:
            raise SignedCandleUnavailable("SIGNED_STOCK_DUPLICATE_CANDLE")
        accepted[closed]=price
    candles=[Candle(symbol,t,p,True) for t,p in sorted(accepted.items())]
    if len(candles)<6:
        raise SignedCandleUnavailable("SIGNED_STOCK_COMPLETED_CANDLES_INSUFFICIENT")
    return candles[-120:]

def schwab_signed_candles(client,symbol,*,now=None):
    from live_worker import recent_candles
    now=utc(now or datetime.now(timezone.utc))
    try:rows=recent_candles(client,symbol)
    except Exception:
        raise SignedCandleUnavailable("SCHWAB_SIGNED_M5_READ_UNAVAILABLE") from None
    return _stock_rows(rows,symbol,now,source="schwab")

def webull_signed_candles(broker,symbol,*,now=None):
    now=utc(now or datetime.now(timezone.utc))
    try:rows=broker.bars(symbol,"EQUITY",period="M5")
    except Exception:
        raise SignedCandleUnavailable("WEBULL_SIGNED_M5_READ_UNAVAILABLE") from None
    return _stock_rows(rows,symbol,now,source="webull")

def coinbase_recorded_candles(state_dir,symbol,*,now=None):
    # Read the V2 paper collector's actual provider-timestamped ticks.
    # This is permissible as technical evidence ONLY; the Robinhood order
    # quote must still come from authenticated signed broker data.
    symbols={"BTC-USD":"BTCUSD","ETH-USD":"ETHUSD"}
    if symbol not in symbols:
        raise SignedCandleUnavailable("PUBLIC_CRYPTO_SOURCE_NOT_ALLOWLISTED")
    now=utc(now or datetime.now(timezone.utc))
    path=Path(state_dir)/"v2"/"fresh_paper"/"tick_bars.sqlite3"
    if path.is_symlink():
        raise SignedCandleUnavailable("CRYPTO_CANDLE_DATABASE_SYMLINK")
    try:
        meta=path.stat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode&0o077 or meta.st_size>40_000_000:
            raise ValueError
        with sqlite3.connect("file:"+str(path.absolute())+"?mode=ro",uri=True,timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("SELECT minute_start,close FROM tick_bars "
                "WHERE symbol=? ORDER BY minute_start DESC LIMIT 120",
                (symbols[symbol],)).fetchall()
    except (OSError,sqlite3.Error,ValueError):
        raise SignedCandleUnavailable("RECORDED_CRYPTO_CANDLE_SOURCE_UNAVAILABLE") from None
    candles=[]
    prev=set()
    current=int(now.timestamp())//60*60
    for minute,close in reversed(rows):
        if type(minute) is not int or minute%60 or minute in prev:
            raise SignedCandleUnavailable("PUBLIC_CRYPTO_CANDLE_TIME_UNVERIFIED")
        prev.add(minute)
        if minute>=current:continue
        try:price=amount(str(close),"actual minute trade close",False)
        except (ValueError,TypeError):
            raise SignedCandleUnavailable("PUBLIC_CRYPTO_CANDLE_PRICE_INVALID") from None
        closed=datetime.fromtimestamp(minute+60,timezone.utc)
        candles.append(Candle(symbol,closed,price,True))
    if len(candles)<9:
        raise SignedCandleUnavailable("PUBLIC_CRYPTO_WARMING_UP")
    return candles
