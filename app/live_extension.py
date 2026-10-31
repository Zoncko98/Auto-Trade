"""Live dashboard extension: bounded risk, transparent evaluations, true XLSX export.

No Schwab credentials, no trading capabilities, no hidden model reasoning.
"""
from __future__ import annotations
import fcntl
import json
import math
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from collections import deque
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

RISK_DEFAULTS={
  "allocation_pct":100.0, "max_order_usd":25.0, "max_position_pct":25.0,
  "max_daily_loss":5.0, "max_open_positions":3, "max_buys_per_day":3,
  "max_orders_per_day":7, "daily_growth_target_pct":1.0}
RISK_BOUNDS={
  "allocation_pct":(0,100), "max_order_usd":(1,25),
  "max_position_pct":(1,25), "max_daily_loss":(0.5,5),
  "max_open_positions":(1,3), "max_buys_per_day":(1,3),
  "max_orders_per_day":(1,7), "daily_growth_target_pct":(0,10)}
INTEGERS={"max_open_positions","max_buys_per_day","max_orders_per_day"}

def validate_risk(settings):
    if not isinstance(settings,dict) or set(settings)!=set(RISK_DEFAULTS):
        raise ValueError("Exactly eight supported live risk settings required")
    result={}
    for name,(low,high) in RISK_BOUNDS.items():
        val=settings[name]
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or not low<=val<=high:
            raise ValueError(name+" must be between "+str(low)+" and "+str(high))
        if name in INTEGERS:
            if type(val) is not int: raise ValueError(name+" must be an integer")
            result[name]=val
        else:result[name]=round(float(val),4)
    if result["max_orders_per_day"]<result["max_buys_per_day"]:
        raise ValueError("Total order cap cannot be below daily buy cap")
    return result

def read_live_risk(state_dir):
    file=Path(state_dir)/"live"/"risk_settings.json"
    if not file.exists():
        return {"version":1,"revision":0,"settings":dict(RISK_DEFAULTS),
                "updated_at":"Default hard safety limits"}
    if file.stat().st_size>8192:raise ValueError("Live risk document too large")
    data=json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("version")!=1 or type(data.get("revision")) is not int or data["revision"]<0:
        raise ValueError("Invalid live risk document")
    return {"version":1,"revision":data["revision"],
            "settings":validate_risk(data["settings"]),
            "updated_at":str(data.get("updated_at",""))[:50]}

def set_live_risk(state_dir,revision,settings,atomic_writer):
    if type(revision) is not int or revision<0:raise ValueError("Invalid revision")
    clean=validate_risk(settings)
    folder=Path(state_dir)/"live"
    folder.mkdir(parents=True,mode=0o700,exist_ok=True)
    with (folder/"risk.lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        current=read_live_risk(state_dir)
        if current["revision"]!=revision:raise RuntimeError("Risk settings changed; reload the page")
        payload={"version":1,"revision":revision+1,"settings":clean,
                 "updated_at":datetime.now(timezone.utc).isoformat()}
        atomic_writer(folder/"risk_settings.json",payload)
    return payload

def log_decision(state_dir,event):
    """Store bounded public evidence and a decision summary; never private CoT."""
    root=Path(state_dir)/"live"
    root.mkdir(parents=True,mode=0o700,exist_ok=True)
    if not isinstance(event,dict) or not all(k in event for k in ("at","decision","symbol","summary")):
        raise ValueError("Missing decision evidence fields")
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}|-",event["symbol"]):
        raise ValueError("Invalid trade candidate symbol")
    raw=(json.dumps(event,allow_nan=False,ensure_ascii=True,separators=(",",":"))+"\n").encode()
    if len(raw)>7000:raise ValueError("Decision record too long")
    path=root/"decisions.jsonl"
    with (root/"decisions.lock").open("a+") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        if path.exists() and path.stat().st_size+len(raw)>4_000_000:
            path.replace(root/"decisions.previous.jsonl")
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:
            os.fchmod(fd,0o600)
            os.write(fd,raw);os.fsync(fd)
        finally:os.close(fd)

def read_decisions(state_dir,limit=125):
    result=deque(maxlen=max(1,min(200,int(limit))))
    root=Path(state_dir)/"live"
    for path in (root/"decisions.previous.jsonl",root/"decisions.jsonl"):
        try:
            if not path.exists() or path.stat().st_size>4_010_000:continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if len(line)>8000:continue
                try:
                    row=json.loads(line)
                    if isinstance(row,dict):result.append(row)
                except (ValueError,TypeError):pass
        except (OSError,UnicodeError):continue
    return list(reversed(result))

def _decimal(v):
    try:
        n=Decimal(str(v))
        return n if n.is_finite() else None
    except (InvalidOperation,TypeError,ValueError):return None

def broker_fills(detail,qty):
    """Extract ONLY verified execution legs; limit quotes aren't fills."""
    if not isinstance(detail,dict):return None
    actual=_decimal(detail.get("filledQuantity"))
    if actual is None or actual!=_decimal(qty):return None
    total=Decimal(0);amount=Decimal(0)
    for activity in detail.get("orderActivityCollection") or []:
        if not isinstance(activity,dict):return None
        if activity.get("activityType") not in ("EXECUTION",None):continue
        for leg in activity.get("executionLegs") or []:
            if not isinstance(leg,dict):return None
            q,p=_decimal(leg.get("quantity")),_decimal(leg.get("price"))
            if q is None or p is None or q<=0 or p<=0:return None
            total+=q;amount+=q*p
    if total!=actual or total<=0:return None
    return {"filled_price":str((amount/total).quantize(Decimal("0.0001"))),
            "filled_quantity":str(total)}

def rows_from_live(journal):
    orders=journal.get("orders",[]) if isinstance(journal,dict) else []
    if not isinstance(orders,list):return []
    lots={};rows=[]
    for index,o in enumerate(orders[:10000]):
        if not isinstance(o,dict):continue
        sym=str(o.get("symbol",""))[:15]
        qty=_decimal(o.get("quantity"))
        price=_decimal(o.get("filled_price")) if o.get("state")=="FILLED" else None
        pnl=None
        if qty and price and qty>0:
            if o.get("action")=="BUY":
                lots.setdefault(sym,[]).append([qty,price])
            elif o.get("action")=="SELL":
                remainder=qty;cost=Decimal(0)
                newlots=[list(lot) for lot in lots.get(sym,[])]
                for lot in newlots:
                    used=min(remainder,lot[0]);cost+=used*lot[1]
                    lot[0]-=used;remainder-=used
                    if remainder<=0:break
                if remainder==0:pnl=float((qty*price-cost).quantize(Decimal("0.01")))
                lots[sym]=[lot for lot in newlots if lot[0]>0]
        rows.append({
          "index":index,"created_at":o.get("created_at",""),
          "symbol":sym,"action":o.get("action",""),
          "quantity":float(qty) if qty is not None else None,
          "limit_price":float(_decimal(o["limit_price"])) if _decimal(o.get("limit_price")) is not None else None,
          "filled_price":float(price) if price is not None else None,
          "filled_notional":float(qty*price) if qty is not None and price is not None else None,
          "gross_realized_pnl":pnl,"state":o.get("state",""),
          "reason":str(o.get("reason",""))[:1000],
          "order_id":str(o.get("order_id") or ""),"candle":o.get("candle")})
    return rows

def _col(n):
    s=""
    while n:
        n,r=divmod(n-1,26);s=chr(65+r)+s
    return s

def _cell(value,ref,style=0):
    if value is None or value=="":return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    value="".join(c for c in str(value)[:2400] if c in "\t\n\r" or ord(c)>=32)
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{escape(value)}</t></is></c>'

def _sheet(rows,widths):
    n=max(len(r) for r in rows)
    columns="".join(f'<col min="{i}" max="{i}" width="{min(75,max(10,w))}" customWidth="1"/>' for i,w in enumerate(widths[:n],1))
    lines=[]
    for i,record in enumerate(rows,1):
        cells="".join(_cell(val,f"{_col(j)}{i}",1 if i==1 else 2 if isinstance(val,(int,float)) else 0)
                      for j,val in enumerate(record,1))
        lines.append(f'<row r="{i}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
       '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
       f'<cols>{columns}</cols><sheetData>{"".join(lines)}</sheetData>'
       f'<autoFilter ref="A1:{_col(n)}{len(rows)}"/></worksheet>')

def excel_export(kind,trades,decisions=(),single=None):
    """Real xlsx; verified fill and purchase basis only, never fabricated P/L."""
    if kind not in ("Live","Paper"):raise ValueError("Unknown export mode")
    if single is not None:
        if type(single) is not int or single<0:raise ValueError("Invalid trade index")
        trades=[r for r in trades if r.get("index")==single]
        if not trades:raise LookupError("Trade not found")
    trades=list(trades)[:10000]
    tr=[["Created UTC","Symbol","Action","Shares","Order limit","Broker fill","Fill value","Gross realized P/L","Order status","Order ID","Reason / AI remarks","Signal candle"]]
    for r in trades:
        tr.append([r.get(x) for x in ("created_at","symbol","action","quantity","limit_price","filled_price","filled_notional","gross_realized_pnl","state","order_id","reason","candle")])
    lookup={(r.get("symbol"),r.get("candle")) for r in trades}
    dec=[["Evaluated UTC","Symbol","Decision","Model","Technical / quote signals","AI assessment","Dated sources","Risks / constraints"]]
    for e in decisions:
        if single is not None and (e.get("symbol"),e.get("candle")) not in lookup:continue
        headlines=e.get("headlines") if isinstance(e.get("headlines"),list) else []
        sources=" | ".join(str(n.get("source",""))+": "+str(n.get("title",""))+" "+str(n.get("published_at",""))+" "+str(n.get("url",""))
                         for n in headlines if isinstance(n,dict))
        dec.append([e.get("at"),e.get("symbol"),e.get("decision"),e.get("model"),str(e.get("signals","")),
                    e.get("summary"),sources,e.get("downside_risk")])
    info=[["AUTO TRADER · "+kind.upper()+" EXPORT",""],
          ["Generated UTC",datetime.now(timezone.utc).isoformat()],
          ["Trade rows",len(trades)],
          ["P/L convention","Gross only, before fees; blank when execution or original purchase basis not verified"],
          ["SPYD opening position","The bot does not know the original purchase cost, so its realized P/L may be blank."],
          ["AI evidence","Recorded model assessment, signals and public news; not private hidden reasoning."],
          ["Limit price","Never treated as an actual executed fill."],
          ["Missing values","Blank means unavailable or not applicable, never assumed zero."]]
    pages=[("Overview",_sheet(info,[33,100])),
           ("Trade Records",_sheet(tr,[26,16,14,12,18,18,18,21,17,22,68,23])),
           ("AI Evidence",_sheet(dec,[26,16,18,20,58,62,75,70]))]
    wb='<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
    rels='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    ct='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    for i,(title,_) in enumerate(pages,1):
        wb+=f'<sheet name="{escape(title)}" sheetId="{i}" r:id="rId{i}"/>'
        rels+=f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        ct+=f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    wb+='</sheets></workbook>'
    rels+='<Relationship Id="style" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    ct+='</Types>'
    styles='''<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF193F65"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>'''
    data=BytesIO()
    with ZipFile(data,"w",compression=ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",ct)
        z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="office" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",wb)
        z.writestr("xl/_rels/workbook.xml.rels",rels)
        z.writestr("xl/styles.xml",styles)
        for i,(_,page) in enumerate(pages,1):z.writestr(f"xl/worksheets/sheet{i}.xml",page)
    return data.getvalue()
