"""Public Coinbase price feed, market data only."""
import json
import ssl,threading,time
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from dashboard_control import write_atomic
from robinhood_crypto_gateway import PAIR
URL="wss://ws-feed.exchange.coinbase.com"
def value(x):
 try:
  y=Decimal(str(x))
  return y if y.is_finite() and y>0 else None
 except (ValueError,TypeError,InvalidOperation):return None
def date(x):
 try:
  d=datetime.fromisoformat(x.replace("Z","+00:00"))
  return d if d.tzinfo else None
 except (ValueError,TypeError,AttributeError):return None
def online_products(msg):
 if not isinstance(msg,dict) or msg.get("type")!="status":return set()
 return {p["id"] for p in msg.get("products",[])
  if isinstance(p,dict) and isinstance(p.get("id"),str)
  and PAIR.fullmatch(p["id"]) and p.get("status")=="online"}
def ticker(msg,allowed,now=None):
 now=now or datetime.now(timezone.utc)
 if not isinstance(msg,dict) or msg.get("type")!="ticker":return None
 sym=msg.get("product_id")
 if not isinstance(sym,str) or not PAIR.fullmatch(sym) or sym not in allowed:return None
 at=date(msg.get("time"))
 bid,ask,price=(value(msg.get(k)) for k in ("best_bid","best_ask","price"))
 if at is None or not -5<=(now-at).total_seconds()<=90:return None
 if bid is None or ask is None or price is None or bid>ask:return None
 if not bid*Decimal(".97")<=price<=ask*Decimal("1.03"):return None
 return {"symbol":sym,"at":at.isoformat(),"mid":str((bid+ask)/2),"bid":str(bid),"ask":str(ask)}
def read_snapshot(root,now=None):
 now=now or datetime.now(timezone.utc)
 path=Path(root)/"robinhood"/"coinbase_market.json"
 try:
  if path.stat().st_size>3000000:raise ValueError("Oversized feed")
  doc=json.loads(path.read_text())
  if not isinstance(doc,dict):raise ValueError("Bad feed")
 except (OSError,ValueError,TypeError):
  return {"state":"UNAVAILABLE","quotes":{},"history":{},"subscribed":0}
 quotes={};history={}
 for sym,row in doc.get("quotes",{}).items():
  if not isinstance(sym,str) or not PAIR.fullmatch(sym) or not isinstance(row,dict):continue
  at=date(row.get("at"));bid=value(row.get("bid"));ask=value(row.get("ask"))
  if at is None or bid is None or ask is None or bid>ask:continue
  if not 0<=(now-at).total_seconds()<=90:continue
  quotes[sym]={"results":[{"symbol":sym,"bid":str(bid),"ask":str(ask)}]}
  accepted=[]
  for sample in doc.get("history",{}).get(sym,[])[-200:]:
   if not isinstance(sample,dict):continue
   at0=date(sample.get("at"));mid=value(sample.get("mid"))
   if at0 and mid and 0<=(now-at0).total_seconds()<=3600:
    accepted.append({"symbol":sym,"at":at0.isoformat(),"mid":str(mid)})
  history[sym]=accepted
 state=("LIVE" if quotes and doc.get("connected") is True else
        "RECENT_CACHE" if quotes else "STALE_OR_UNAVAILABLE")
 return {"state":state,"quotes":quotes,"history":history,
         "connected":doc.get("connected") is True,
         "subscribed":doc.get("subscribed",0)}
class CoinbaseFeed:
 def __init__(self,state,connector=None):
  self.state=Path(state);self.connector=connector
  self.lock=threading.RLock();self.wanted=();self.active=()
  self.quotes={};self.history={};self.bucket={}
  self.last_write=0;self.thread=None;self.connected=False
 def update_symbols(self,symbols):
  with self.lock:
   self.wanted=tuple(sorted({s for s in symbols if isinstance(s,str) and PAIR.fullmatch(s)}))[:250]
 def start(self):
  if self.thread and self.thread.is_alive():return
  self.thread=threading.Thread(target=self._run,name="coinbase-public-market",daemon=True)
  self.thread.start()
 def ingest(self,msg,now=None):
  now=now or datetime.now(timezone.utc)
  with self.lock:
   row=ticker(msg,self.active or self.wanted,now)
   if row is None:return False
   sym=row["symbol"];at=date(row["at"])
   old=self.quotes.get(sym)
   if old and date(old["at"])>=at:return False
   self.quotes[sym]=row
   bucket=int(at.timestamp())//20
   if self.bucket.get(sym)!=bucket:
    self.history.setdefault(sym,[]).append({"symbol":sym,"at":row["at"],"mid":row["mid"]})
    self.bucket[sym]=bucket
   self.history[sym]=[x for x in self.history[sym][-200:]
    if 0<=(at-date(x["at"])).total_seconds()<=3600]
   return True
 def flush(self,force=False):
  if not force and time.time()-self.last_write<20:return
  with self.lock:
   doc={"updated_at":datetime.now(timezone.utc).isoformat(),
    "connected":self.connected,"subscribed":len(self.active),
    "quotes":dict(self.quotes),"history":{k:list(v) for k,v in self.history.items()}}
  write_atomic(self.state/"robinhood"/"coinbase_market.json",doc)
  self.last_write=time.time()
 def _run(self):
  retry=2
  while True:
   with self.lock:wanted=self.wanted
   if not wanted:
    time.sleep(2);continue
   sock=None
   try:
    if self.connector is None:
     from websocket import create_connection
     sock=create_connection(URL,timeout=10,sslopt={"cert_reqs":ssl.CERT_REQUIRED})
    else:sock=self.connector(URL)
    sock.send(json.dumps({"type":"subscribe","channels":["status"]}))
    catalogue=set()
    for _ in range(4):
     message=json.loads(sock.recv())
     if isinstance(message,dict) and message.get("type")=="status":
      catalogue=online_products(message)
      break
    supported=tuple(sym for sym in wanted if sym in catalogue)
    if not supported:raise RuntimeError("No overlapping Coinbase markets")
    with self.lock:self.active,self.connected=supported,True
    sock.send(json.dumps({"type":"subscribe","product_ids":list(supported),
     "channels":["ticker_batch"]}))
    sock.send(json.dumps({"type":"unsubscribe","channels":["status"]}))
    retry=2
    while True:
     with self.lock:
      if self.wanted!=wanted:break
     raw=sock.recv()
     if not isinstance(raw,str) or len(raw)>200000:continue
     try:msg=json.loads(raw)
     except ValueError:continue
     if isinstance(msg,dict) and msg.get("type")=="error":
      raise RuntimeError("Coinbase subscription rejected")
     self.ingest(msg);self.flush()
   except Exception:
    time.sleep(retry);retry=min(60,retry*2)
   finally:
    with self.lock:self.connected,self.active=False,()
    if sock:
     try:sock.close()
     except Exception:pass
    self.flush(force=True)
