"""Account-scoped durable broker-bid high-water marks for bot-owned crypto lots.

Only broker-verified bot positions are observed. State resets on any change to
quantity, average cost or position opening timestamp; older peaks cannot leak
into new lots. This is not a broker-native trailing stop or guaranteed fill.
"""
import json,os,tempfile
from decimal import Decimal,InvalidOperation
from pathlib import Path

class ExitTrackerError(ValueError): pass

def _number(raw):
    try:
        value=Decimal(str(raw))
    except (ValueError,TypeError,InvalidOperation):
        raise ExitTrackerError("Invalid broker bid") from None
    if not value.is_finite() or value<=0:
        raise ExitTrackerError("Invalid broker bid")
    return value

def _signature(position):
    if not isinstance(position,dict) or position.get("cost_basis_verified") is not True:
        raise ExitTrackerError("Broker-confirmed cost basis required")
    cost=_number(position.get("average_unit_cost"))
    qty=_number(position.get("quantity"))
    opened=position.get("opened_at")
    if not isinstance(opened,str) or not opened:
        raise ExitTrackerError("Position opening timestamp missing")
    return [str(qty),str(cost),opened]

class ExitTracker:
    def __init__(self,root):
        self.path=Path(root)/"robinhood"/"exit_peaks.json"

    def load(self):
        try: doc=json.loads(self.path.read_text())
        except FileNotFoundError: return {"version":1,"accounts":{}}
        except (OSError,ValueError,TypeError) as exc:
            raise ExitTrackerError("Exit peak state unavailable") from None
        if not isinstance(doc,dict) or doc.get("version")!=1 or not isinstance(doc.get("accounts"),dict):
            raise ExitTrackerError("Exit peak state invalid")
        return doc

    def _save(self,doc):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=".exit-peaks-",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w") as stream:
                os.fchmod(stream.fileno(),0o600)
                json.dump(doc,stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def update(self,account,positions,bids):
        if not isinstance(account,str) or not account:
            raise ExitTrackerError("Configured account required")
        if not isinstance(positions,dict) or not isinstance(bids,dict):
            raise ExitTrackerError("Invalid positions or quote state")
        doc=self.load()
        acct=doc["accounts"].setdefault(account,{})
        if not isinstance(acct,dict):
            raise ExitTrackerError("Account peak state invalid")
        for old in list(acct):
            if old not in positions:acct.pop(old,None)
        peaks={}
        for symbol,position in positions.items():
            if symbol not in bids:
                # No fresh quote: retain previous peak, but do not authorize a
                # trailing decision with an unobserved current price.
                continue
            signature=_signature(position)
            bid=_number(bids[symbol])
            old=acct.get(symbol)
            old_peak=None
            if isinstance(old,dict) and old.get("signature")==signature:
                try:old_peak=_number(old.get("high_water_bid"))
                except ExitTrackerError: pass
            peak=max(bid,old_peak) if old_peak is not None else bid
            acct[symbol]={"signature":signature,"high_water_bid":str(peak)}
            peaks[symbol]=peak
        self._save(doc)
        return peaks

    def peak(self,account,symbol,position):
        doc=self.load()
        account_data=doc["accounts"].get(account)
        if not isinstance(account_data,dict):return None
        item=account_data.get(symbol)
        if not isinstance(item,dict) or item.get("signature")!=_signature(position):return None
        try:return _number(item.get("high_water_bid"))
        except ExitTrackerError:return None
