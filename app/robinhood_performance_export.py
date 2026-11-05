"""Authenticated Robinhood performance workbook from recorded broker reconciliation.

Read-only reporting. Filled prices, quantities, fees and sell cost basis are
verified independently of quoted limits. Never infer a fill from order acceptance.
Never label a time-correlated AI decision as a causally linked order.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile,ZIP_DEFLATED
from live_extension import _sheet
from robinhood_order_journal import OrderJournal

MAX_ORDERS=10000
MAX_DECISIONS=100
MIME="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def _decimal(value):
    try:
        n=Decimal(str(value))
        return n if n.is_finite() else None
    except (ValueError,TypeError,InvalidOperation):
        return None

def _positive(value):
    n=_decimal(value)
    return n if n is not None and n>0 else None

def _float(n):
    return float(n) if n is not None else None

def _utc(value):
    if not isinstance(value,str):return None
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo is not None else None
    except (ValueError,TypeError,OverflowError):return None

def _text(value,limit=450):
    if value is None:return ""
    return str(value).replace("\x00","")[:limit]

def _read_json(path,default,maximum):
    try:
        if path.stat().st_size>maximum:
            raise ValueError("Report source is larger than the safe export limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError("Robinhood report source unavailable or malformed") from exc

def _evidence(row,decisions):
    """Time-and-symbol evidence is explicitly a proximity match, never an order join."""
    at=_utc(row.get("created_at"))
    symbol=row.get("symbol")
    side=row.get("side")
    if not at or not isinstance(symbol,str) or side not in ("buy","sell"):
        return "","","","NONE"
    key="entry_candidate_symbol" if side=="buy" else "exit_candidate_symbol"
    eligible=[]
    for item in decisions:
        if not isinstance(item,dict) or item.get(key)!=symbol:continue
        status=str(item.get("execution_status") or "")
        if side=="buy" and status not in ("ORDER_ACCEPTED","SUBMITTED_UNCONFIRMED"):continue
        if side=="sell" and status not in ("SELL_ORDER_ACCEPTED","SELL_SUBMITTED_UNCONFIRMED"):continue
        stamp=_utc(item.get("at"))
        if stamp is None:continue
        age=abs((stamp-at).total_seconds())
        if age<=180:eligible.append((age,item))
    if not eligible:return "","","","NONE"
    item=min(eligible,key=lambda x:x[0])[1]
    return (_text(item.get("execution_reason"),450),
            _text(item.get("ai_reason"),450),
            _text(item.get("ai_review_status"),65),
            "TIME_SYMBOL_ONLY (not order-ID linked)")

def _pack(sheets):
    """Small standard-library OOXML export, matching the existing app export."""
    if len(sheets)>12:raise ValueError("Too many report tabs")
    wb=('<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>')
    rels='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    types=('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
    for i,(name,_,_) in enumerate(sheets,1):
        wb+=f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        rels+=f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        types+=f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    wb+='</sheets></workbook>'
    rels+=('<Relationship Id="style" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    types+='</Types>'
    styles=('''<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF193F65"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>''')
    data=BytesIO()
    with ZipFile(data,"w",compression=ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",types)
        z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="office" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",wb)
        z.writestr("xl/_rels/workbook.xml.rels",rels)
        z.writestr("xl/styles.xml",styles)
        for i,(_,records,widths) in enumerate(sheets,1):
            z.writestr(f"xl/worksheets/sheet{i}.xml",_sheet(records,widths))
    output=data.getvalue()
    if len(output)>14_000_000:raise ValueError("Robinhood workbook exceeds download limit")
    return output

def build_robinhood_performance_workbook(state,now=None):
    """Export recorded account-scoped bot orders; never call or mutate broker API."""
    root=Path(state)
    timestamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    from robinhood_policy import read_policy
    policy=read_policy(root)
    account=policy.get("account")
    if not isinstance(account,str) or not account:
        raise ValueError("No configured Robinhood reporting account")
    raw=OrderJournal(root).load()
    if len(raw["orders"])>MAX_ORDERS:
        raise ValueError("Robinhood journal exceeds safe report limit")
    orders=[o for o in raw["orders"] if isinstance(o,dict) and o.get("account")==account]
    history=_read_json(root/"robinhood"/"decision_history.json",[],2_000_000)
    if not isinstance(history,list):raise ValueError("Decision history is malformed")
    decisions=[d for d in history[-MAX_DECISIONS:] if isinstance(d,dict)]
    ledger={}
    assets=defaultdict(lambda:{"buys":0,"sells":0,"wins":0,"losses":0,
       "breakevens":0,"pnl":Decimal(0),"pnl_known":0,"fees":Decimal(0),"fee_count":0})
    days=defaultdict(lambda:{"buys":0,"sells":0,"wins":0,"losses":0,
       "breakevens":0,"pnl":Decimal(0),"known":0,"fees":Decimal(0),"fee_count":0})
    trades=[["Intent created UTC","Filled UTC","Symbol","Side","Journal status",
       "Requested qty","Limit price USD (not fill)","Broker-filled qty",
       "Actual avg fill USD","Filled notional USD","Verified broker fee USD",
       "Net realized P/L USD","Net return on allocated cost %","Trade outcome",
       "Held since first open buy (min)","Recorded execution rationale (approx.)",
       "Recorded AI/technical rationale (approx.)","Review status",
       "Decision evidence linkage","Broker error / journal reason","Fee / P&L coverage",
       "Broker order ID","Bot client order ID"]]
    exits=[["Sell filled UTC","Symbol","Quantity","Actual sell price USD",
       "Allocated purchase cost incl. buy fees USD","Sale proceeds after sell fees USD",
       "Verified sell fee USD","Net realized P/L USD","Net return %",
       "Outcome","Holding time (min)","Exit trigger / rationale (time-linked)",
       "Entry rationale from nearby decision","Decision evidence confidence",
       "Calculation coverage"]]
    rejected=[["Event UTC","Source","Symbol","Side / candidate",
       "Status / review","Recorded reason","AI model","Execution classification",
       "Order client ID"]]
    total_filled_buys=total_filled_sells=0
    known_exits=win=loss=flat=0
    verified_total=Decimal(0)
    sell_returns=[]
    missing_bases=0
    external_count=0
    for row in orders:
        side=row.get("side")
        status=str(row.get("status") or "")
        sym=_text(row.get("symbol"),30)
        at=row.get("filled_at") or row.get("created_at") or row.get("resolved_at")
        day=_utc(row.get("filled_at"))
        date=day.date().isoformat() if day else ""
        q=_positive(row.get("filled_quantity")) if status=="filled" else None
        price=_positive(row.get("average_fill_price")) if status=="filled" else None
        fee=_decimal(row.get("fee_charged")) if status=="filled" and row.get("fee_verified") is True else None
        if fee is not None and fee<0:fee=None
        notional=q*price if q is not None and price is not None else None
        asset=assets[sym]
        record_day=days[date] if date else None
        observed_fee=fee is not None
        if observed_fee:
            asset["fees"]+=fee;asset["fee_count"]+=1
            if record_day is not None:
                record_day["fees"]+=fee;record_day["fee_count"]+=1
        broker_reason,ai_reason,ai_status,linkage=_evidence(row,decisions)
        journal_reason=_text(row.get("submission_error") or row.get("note"),350)
        pnl=None
        allocated=None
        proceeds=None
        pct=None
        hold_mins=None
        coverage=("VERIFIED BROKER FILL + FEE" if q is not None and price is not None
                  and fee is not None else "UNVERIFIED FILL OR FEE" if status=="filled"
                  else "NOT A FILLED ORDER")
        outcome=""
        if side in ("buy","sell") and status=="filled":
            state_row=ledger.setdefault(sym,{"quantity":Decimal(0),"cost":Decimal(0),
                  "verified":True,"opened_at":None})
            if side=="buy":
                total_filled_buys+=1
                asset["buys"]+=1
                if record_day is not None:record_day["buys"]+=1
                if q is None or price is None:
                    state_row["verified"]=False
                    coverage="BUY FILL DETAILS INCOMPLETE"
                else:
                    if state_row["quantity"]==0:state_row["opened_at"]=day
                    state_row["quantity"]+=q
                    # Track estimated acquisition cost without guessing missing broker fees.
                    state_row["cost"]+=notional+(fee or Decimal(0))
                    if fee is None:state_row["verified"]=False
            else:
                total_filled_sells+=1
                asset["sells"]+=1
                if record_day is not None:record_day["sells"]+=1
                valid=(q is not None and price is not None and fee is not None
                    and state_row["verified"] and q<=state_row["quantity"]
                    and state_row["quantity"]>0)
                if valid:
                    avg=state_row["cost"]/state_row["quantity"]
                    allocated=avg*q
                    proceeds=notional-fee
                    pnl=proceeds-allocated
                    pct=pnl/allocated*Decimal(100) if allocated>0 else None
                    coverage="NET P/L VERIFIED: FILL, FEES, PURCHASE BASIS"
                    outcome=("WIN" if pnl>0 else "LOSS" if pnl<0 else "BREAKEVEN")
                    known_exits+=1
                    verified_total+=pnl
                    if pnl>0:win+=1;asset["wins"]+=1
                    elif pnl<0:loss+=1;asset["losses"]+=1
                    else:flat+=1;asset["breakevens"]+=1
                    if pct is not None:sell_returns.append(pct)
                    asset["pnl"]+=pnl;asset["pnl_known"]+=1
                    if record_day is not None:
                        record_day["known"]+=1
                        record_day["pnl"]+=pnl
                        if pnl>0:record_day["wins"]+=1
                        elif pnl<0:record_day["losses"]+=1
                        else:record_day["breakevens"]+=1
                    if day and state_row["opened_at"]:
                        hold_mins=round((day-state_row["opened_at"]).total_seconds()/60,2)
                else:
                    missing_bases+=1
                    coverage="NET P/L NOT VERIFIED: missing fill/fee/basis"
                # Even if a sell lacks provable P/L, remove only a credible quantity.
                if q is not None and q<=state_row["quantity"] and state_row["quantity"]>0:
                    basis_unit=state_row["cost"]/state_row["quantity"]
                    state_row["quantity"]-=q
                    state_row["cost"]-=basis_unit*q
                    if state_row["quantity"]==0:
                        state_row["cost"]=Decimal(0);state_row["opened_at"]=None
                else:state_row["verified"]=False
                exits.append([row.get("filled_at"),sym,_float(q),_float(price),
                    _float(allocated),_float(proceeds),_float(fee),_float(pnl),
                    _float(pct),outcome,hold_mins,broker_reason,ai_reason,
                    linkage,coverage])
        elif side=="external_reduction" and status=="externally_reconciled":
            external_count+=1
            state_row=ledger.get(sym)
            external_qty=_positive(row.get("quantity"))
            if state_row and external_qty is not None:
                if state_row["quantity"]>=external_qty and state_row["quantity"]>0:
                    avg=state_row["cost"]/state_row["quantity"]
                    state_row["quantity"]-=external_qty
                    state_row["cost"]-=avg*external_qty
                    if state_row["quantity"]==0:
                        state_row["cost"]=Decimal(0);state_row["opened_at"]=None
                else:state_row["verified"]=False
            coverage="EXTERNAL BROKER SALE: NOT BOT P/L"
        if side in ("buy","sell","external_reduction"):
            trades.append([row.get("created_at"),row.get("filled_at"),sym,
              side.upper(),status,_float(_positive(row.get("quantity"))),
              _float(_positive(row.get("limit_price"))),
              _float(q) if side!="external_reduction" else _float(_positive(row.get("quantity"))),
              _float(price),_float(notional),_float(fee),
              _float(pnl),_float(pct),outcome,hold_mins,
              broker_reason,ai_reason,ai_status,linkage,journal_reason,coverage,
              _text(row.get("broker_order_id"),85),
              _text(row.get("client_order_id"),85)])
        if status in ("rejected","failed","canceled","cancelled","expired"):
            rejected.append([row.get("resolved_at") or row.get("created_at"),
                "BOT ORDER JOURNAL",sym,_text(side,20).upper(),status,
                journal_reason,"","BROKER / JOURNAL ORDER",_text(row.get("client_order_id"),85)])

    scans=[["Evaluated UTC","Primary signal","Entry candidate",
        "Entry momentum %","AI review result","AI model",
        "AI explanation","Execution status","Recorded execution reason",
        "Risk preflight","Market data source","Ranked entry candidates",
        "AI review total sec","Exit candidate","Exit trigger / signal",
        "Evidence completeness"]]
    candidates=[["Scan UTC","Symbol","Candidate outcome","Review type",
        "Model","Review seconds","Model inference seconds","Recorded rationale",
        "News status","Entry ranking source"]]
    for entry in decisions:
        at=entry.get("at")
        scans.append([at,_text(entry.get("signal"),130),
            _text(entry.get("entry_candidate_symbol"),30),
            _float(_decimal(entry.get("entry_momentum_pct"))),
            _text(entry.get("ai_review_status"),65),
            _text(entry.get("ai_model"),80),
            _text(entry.get("ai_reason"),550),
            _text(entry.get("execution_status"),70),
            _text(entry.get("execution_reason"),550),
            _text(entry.get("risk_check"),90),
            _text(entry.get("market_data_source"),65),
            _text(entry.get("ranked_entry_candidates"),270),
            _float(_decimal(entry.get("ai_review_duration_seconds"))),
            _text(entry.get("exit_candidate_symbol"),30),
            _text(entry.get("exit_signal_reason"),240),
            "RETAINED SCAN; NOT FULL BROKER ORDER HISTORY"])
        reviews=entry.get("ai_candidate_reviews")
        for rev in reviews if isinstance(reviews,list) else []:
            if not isinstance(rev,dict):continue
            candidates.append([at,_text(rev.get("symbol"),30),
                _text(rev.get("outcome"),65),_text(rev.get("review_type"),80),
                _text(rev.get("model"),85),_float(_decimal(rev.get("elapsed_seconds"))),
                _float(_decimal(rev.get("model_inference_seconds"))),
                _text(rev.get("reason"),550),_text(rev.get("news_status"),70),
                "Candidate review retained; no unique broker order join"])
        execution=str(entry.get("execution_status") or "")
        ai_state=str(entry.get("ai_review_status") or "")
        if execution.startswith("BLOCKED") or execution.startswith("SELL_BLOCKED") or (
            execution=="NOT_ARMED" and (ai_state in ("AI_NO_TRADE","AI_UNAVAILABLE",
               "NEWS_EVIDENCE_MISSING","NEWS_FEED_UNAVAILABLE",
               "AI_REVIEW_BLOCKED","MIXED_AI_REJECTIONS"))):
            rejected.append([at,"RECORDED SCAN",_text(entry.get("entry_candidate_symbol")
                or entry.get("exit_candidate_symbol"),30),
                "SCAN / CANDIDATE",ai_state or execution,
                _text(entry.get("execution_reason") or entry.get("ai_reason"),500),
                _text(entry.get("ai_model"),80),execution,""])
    asset_rows=[["Symbol","Filled buy orders","Filled sell orders",
      "Sells with verified net P/L","Winning exits","Losing exits","Breakeven exits",
      "Win rate on verified exits %","Verified net realized P/L USD",
      "Verified fees USD","Fee record count","Known P/L coverage"]]
    for symbol,a in sorted(assets.items()):
        denom=a["pnl_known"]
        asset_rows.append([symbol,a["buys"],a["sells"],denom,a["wins"],
           a["losses"],a["breakevens"],round(a["wins"]/denom*100,2) if denom else None,
           _float(a["pnl"]) if denom else None,_float(a["fees"]) if a["fee_count"] else None,
           a["fee_count"],str(denom)+" of "+str(a["sells"])+" sell fills"])
    day_rows=[["UTC date","Filled buys","Filled sells","Verified exits",
         "Wins","Losses","Breakevens","Win rate on verified exits %",
         "Verified net realized P/L USD","Cumulative verified P/L USD",
         "Verified fees USD","Fee observations"]]
    cumulative=Decimal(0)
    for date,day in sorted(days.items()):
        cumulative+=day["pnl"]
        day_rows.append([date,day["buys"],day["sells"],day["known"],
            day["wins"],day["losses"],day["breakevens"],
            round(day["wins"]/day["known"]*100,2) if day["known"] else None,
            _float(day["pnl"]) if day["known"] else None,
            _float(cumulative),_float(day["fees"]) if day["fee_count"] else None,
            day["fee_count"]])
    open_rows=[["Symbol","Bot journal quantity","Allocated cost basis USD",
        "Average unit cost USD incl. verified buy fees","Cost basis complete",
        "Last opened UTC","Unrealized P/L USD","Provenance"]]
    for sym,position in sorted(ledger.items()):
        if position["quantity"]<=0:continue
        good=position["verified"]
        open_rows.append([sym,_float(position["quantity"]),
            _float(position["cost"]) if good else None,
            _float(position["cost"]/position["quantity"]) if good else None,
            "VERIFIED" if good else "INCOMPLETE",
            position["opened_at"].isoformat() if position["opened_at"] else "",
            None,"BOT JOURNAL ONLY; not fresh broker holdings or mark price"])
    all_verified_fees=sum((a["fees"] for a in assets.values()),Decimal(0))
    fee_observations=sum(a["fee_count"] for a in assets.values())
    denom=known_exits
    overview=[["AUTO TRADER · ROBINHOOD PERFORMANCE","Value"],
      ["Generated UTC",timestamp.isoformat()],
      ["Export scope","Configured Robinhood Crypto account; bot journal only"],
      ["Recorded bot order rows",len(orders)],
      ["Broker-confirmed filled buys",total_filled_buys],
      ["Broker-confirmed filled sells",total_filled_sells],
      ["Sell fills with verified P/L",known_exits],
      ["Sell fills lacking verified P/L",missing_bases],
      ["Winning verified sells",win],
      ["Losing verified sells",loss],
      ["Breakeven verified sells",flat],
      ["Verified win rate %",round(win/denom*100,2) if denom else None],
      ["Verified net realized P/L USD",_float(verified_total) if denom else None],
      ["Average verified sell return %",_float(sum(sell_returns)/len(sell_returns))
          if sell_returns else None],
      ["Verified broker fees USD",_float(all_verified_fees) if fee_observations else None],
      ["Number of verified fee records",fee_observations],
      ["External/manual reductions excluded from bot P/L",external_count],
      ["Retained scan evidence",len(decisions)],
      ["Unrealized P/L","Unavailable: no fresh broker quote fetched for export"],
      ["Win/loss meaning","Per filled SELL with complete quantity, price, buy-cost and fee evidence"],
      ["Buy/sell rationale","Nearest symbol+time scan is contextual, not proof of causal attribution"],
      ["Incomplete P/L","Blank, never assumed $0; see Trade Ledger coverage"],
      ["Performance guarantee","Historical records only; no prediction of future returns"]]
    methodology=[["Field / source","How to interpret it"],
      ["Data sources","Robinhood bot order_intents.json (broker-reconciled rows), decision_history.json (last 100 scans), risk account scope"],
      ["Broker verification","Filled status + filled_quantity + average_fill_price indicate reconciled broker execution; order acknowledgment alone does not"],
      ["Realized P/L","Filled sell proceeds minus verified sell fee minus weighted-average bot acquisition cost including verified buy fees"],
      ["Net return %","Verified net realized P/L divided by allocated weighted-average purchase cost, times 100"],
      ["Fees","Only broker-reconciled fee_verified=true values counted in verified fee and P/L calculations"],
      ["Missing P/L","A sell is excluded from verified profitability when buy history, fee, or filled price/quantity is not provable"],
      ["Multi-buys","Multiple buys of a symbol are pooled using weighted-average bot-owned cost"],
      ["Manual/external sells","External reductions affect reconstructed bot quantity but are not treated as bot orders or assigned invented P/L"],
      ["Open positions","Journal cost basis is not broker-current valuation; do not use as unrealized P/L"],
      ["Decision history retention","Only most recent 100 scanner evaluations are retained; older trade explanations may not be recoverable"],
      ["Decision match confidence","Nearest retained scan with matching symbol/side and <=180-second intent-time separation; no order ID join; never causal proof"],
      ["Rejected versus skipped","A rejected broker submission differs from AI NO_TRADE or no technical signal. The Diagnostics sheet identifies source"],
      ["Order limit","Requested limit price is not a broker-executed fill; never used to calculate realized profit"],
      ["Reporting time zone","UTC; daily amounts grouped by verified sell fill timestamps"],
      ["Privacy","One authenticated account scope; no API secret, private key, or user credential exported"],
      ["Historical evidence","Recorded trade rationale and AI summary only, not internal hidden model reasoning"],
      ["Metric limitation","Win rate is among covered filled sells, not among buys, all candidates, or all trading opportunities"],
      ["Fee-adjusted candidates","Each technically qualified scanned candidate is evaluated as a shadow hypothetical; never a submitted or simulated broker order"],
      ["MFE/MAE capture starts at deployment","Sampled gains/losses are incomplete when candidate/position quotes were not observed, cannot be reconstructed for earlier trades"],
      ["Entry diagnostics","Legacy orders are not affected by counterfactual spread, dip-reversal, and estimated-fee filters"],
      ["Exact exit explanation","Only new order annotations keyed by client_order_id prove the recorded exit trigger; earlier exits remain UNKNOWN"]]
    sheets=[
      ("Overview",overview,[44,98]),
      ("Trade Ledger",trades,[26,26,17,18,23,20,23,20,21,22,21,23,21,18,22,75,75,35,43,75,58,41,42]),
      ("Closed Exits",exits,[26,18,19,22,22,25,22,25,21,17,22,75,75,44,62]),
      ("Asset Analysis",asset_rows,[18,20,20,24,19,19,19,24,26,23,19,30]),
      ("Daily Results",day_rows,[17,18,18,18,13,13,17,25,25,26,23,19]),
      ("Open Cost Basis",open_rows,[18,23,24,30,24,27,24,75]),
      ("Scan Evidence",scans,[26,40,24,20,28,30,75,32,75,40,30,50,24,23,63,67]),
      ("Candidate Reviews",candidates,[26,19,30,29,24,20,26,75,25,62]),
      ("Blocked and Rejected",rejected,[26,27,21,24,27,78,30,36,48]),
      ("Methodology",methodology,[38,100])
    ]
    from robinhood_strategy_diagnostics import export_tables
    candidates,executions=export_tables(root,account)
    sheets.extend([
        ("Fee-adjusted Candidates",candidates,
         [26,20,27,28,19,24,19,19,20,23,23,24,25,37,65,
          30,30,34,26,26,26,20,68,25,25,34,27]),
        ("Execution Diagnostics",executions,
         [26,20,14,24,26,27,24,22,75,27,27,74])
    ])
    return _pack(sheets)
