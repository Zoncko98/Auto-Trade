"""Robinhood diagnostic recorder. Shadow evaluation only; no order permissions.

A qualified technical candidate is a hypothetical opportunity, NOT a fill.
Coinbase feed marks are indicative and never presented as Robinhood execution.
Position excursions require reconciled bot cost and actual Robinhood bids.
"""
from __future__ import annotations
import json,os,sqlite3
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from pathlib import Path
from robinhood_order_journal import OrderJournal
from robinhood_fee_estimates import effective_sell_fee_pct

DB_NAME="strategy_diagnostics.sqlite3"
MAX_CANDIDATES=30000
HORIZON_SECONDS=3600

def val(x):
    try:
        d=Decimal(str(x))
        return d if d.is_finite() else None
    except (InvalidOperation,TypeError,ValueError):return None

def pos(x):
    d=val(x)
    return d if d is not None and d>0 else None

def utc(x):
    if not isinstance(x,str):return None
    try:
        t=datetime.fromisoformat(x.replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError,TypeError,OverflowError):return None

def daystamp(t):return t.astimezone(timezone.utc).isoformat()

def quote(row):
    """Use only the quote venue used to observe this technical signal."""
    if not isinstance(row,dict):return None
    bid=pos(row.get("diagnostic_bid"))
    ask=pos(row.get("diagnostic_ask"))
    if bid is None or ask is None or ask<bid:return None
    return bid,ask

def fee_pct(journal,account,side,floor=Decimal("0.25")):
    """Conservative observed fee envelope, distinct from broker's actual fee."""
    samples=[]
    for row in reversed(journal.load().get("orders",[])):
        if (not isinstance(row,dict) or row.get("account")!=account
                or row.get("side")!=side or row.get("status")!="filled"
                or row.get("fee_verified") is not True):continue
        q=pos(row.get("filled_quantity"));p=pos(row.get("average_fill_price"))
        fee=val(row.get("fee_charged"))
        if q is None or p is None or fee is None or fee<0 or q*p<1:continue
        rate=fee/(q*p)*100
        if rate<=10:
            samples.append(rate)
            if len(samples)>=8:break
    return max([floor]+[x*Decimal("1.05") for x in samples]),("BROKER_FILLS" if samples else "POLICY_FLOOR")

def shadow_signal(row,history,buy_fee,sell_fee):
    """Stricter counterfactual; NEVER wired into execution permission."""
    if row.get("technical_approved") is not True:
        return "LEGACY_NOT_QUALIFIED","Current strategy did not qualify"
    bidask=quote(row)
    if not bidask:return "INSUFFICIENT_PRICE_EVIDENCE","Missing comparable bid and ask"
    bid,ask=bidask
    momentum=val(row.get("momentum_pct"))
    spread=(ask-bid)/ask*100
    broker_spread=val(row.get("broker_spread_pct"))
    if broker_spread is None:
        if str(row.get("source","")).startswith("ROBINHOOD_"):
            broker_spread=spread
        else:
            return "SHADOW_REJECT_BROKER_SPREAD_UNVERIFIED","Robinhood quote spread missing"
    if momentum is None:return "INSUFFICIENT_PRICE_EVIDENCE","Missing momentum"
    if broker_spread<0 or broker_spread>Decimal("0.20") or spread>Decimal("0.20"):
        return "SHADOW_REJECT_SPREAD","Feed or Robinhood broker spread exceeds proposed 0.20% limit"
    if momentum>Decimal("1.5"):return "SHADOW_REJECT_CHASE","Price already climbed >1.5% over signal window"
    pts=[]
    now=utc(row.get("at"))
    for rec in history if isinstance(history,list) else []:
        if not isinstance(rec,dict):continue
        at=utc(rec.get("at"));mid=pos(rec.get("mid"))
        if at is not None and mid is not None and now is not None:
            sec=(now-at).total_seconds()
            if 0<sec<=900:pts.append((at,mid))
    pts=sorted(pts,key=lambda v:v[0])
    pts.append((now,(bid+ask)/2))
    if len(pts)<6 or (pts[-1][0]-pts[0][0]).total_seconds()<420:
        return "SHADOW_REJECT_COVERAGE","Need 6 samples over >=7 minutes"
    vals=[p for _,p in pts]
    # An actual pullback must precede recovery, not a monotone chase.
    # Find the strongest *interior* local trough after a previous high,
    # rather than the absolute minimum (which may be the oldest point of a
    # broader uptrend). This prevents missing a genuine intra-trend dip.
    troughs=[i for i in range(2,len(vals)-2)
             if vals[i]<=vals[i-1] and vals[i]<vals[i+1]]
    if not troughs:
        return "SHADOW_REJECT_NO_DIP","No established interior pullback low"
    low_index=max(troughs,key=lambda i:(max(vals[:i])/vals[i]-1))
    low=vals[low_index]
    pre_high=max(vals[:low_index])
    dip=(pre_high/low-1)*100
    recovery=(vals[-1]/low-1)*100
    if dip<Decimal("0.40") or recovery<Decimal("0.25"):
        return "SHADOW_REJECT_WEAK_RECOVERY","Pullback or rebound confirmation too small"
    if not (vals[-1]>vals[-2]>vals[-3]):
        return "SHADOW_REJECT_NOT_RISING","Two successive higher recovery observations required"
    # Historical resistance is evidence of possible upside, not a forecast.
    potential=(pre_high/ask-1)*100
    required=((Decimal(1)+buy_fee/100)*(Decimal(1)+Decimal("0.5")/100)
              /(Decimal(1)-sell_fee/100)-1)*100
    if potential<required:
        return "SHADOW_REJECT_REWARD_AFTER_FEES",(
            "Prior swing high offers "+str(potential.quantize(Decimal(".01")))+
            "% vs "+str(required.quantize(Decimal(".01")))+"% needed for +0.5% net")
    return "SHADOW_PASS_REBOUND","Dip, recovery, spread, and fee-aware reward checks passed (not a profit forecast)"

def connect(root):
    path=Path(root)/"robinhood"/DB_NAME
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
        os.close(fd)
    db=sqlite3.connect(str(path),timeout=3.0)
    os.chmod(path,0o600)
    db.execute("PRAGMA busy_timeout=2500")
    db.execute("""CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY, account TEXT NOT NULL, at TEXT NOT NULL,
        symbol TEXT NOT NULL, source TEXT, signal TEXT, spread_pct REAL,
        broker_spread_pct REAL, momentum_pct REAL, history_points INTEGER, history_seconds REAL,
        trend_up INTEGER, entry_ask TEXT, entry_bid TEXT, quote_venue TEXT,
        buy_fee_pct REAL, sell_fee_pct REAL, breakeven_move_pct REAL,
        target_move_pct REAL, shadow_result TEXT, shadow_reason TEXT,
        selection TEXT, ai_status TEXT, execution_status TEXT,
        max_favorable_pct REAL, max_adverse_pct REAL,
        max_favorable_net_pct REAL,max_adverse_net_pct REAL,
        last_net_pct REAL, samples INTEGER, last_at TEXT,
        closed INTEGER NOT NULL DEFAULT 0, coverage TEXT,
        horizon_status TEXT NOT NULL DEFAULT 'OBSERVING',
        horizon_net_pct REAL)""")
    db.execute("""CREATE INDEX IF NOT EXISTS candidate_active
        ON candidates(account,symbol,closed,at)""")
    db.execute("""CREATE TABLE IF NOT EXISTS positions (
        account TEXT NOT NULL, symbol TEXT NOT NULL, opened_at TEXT NOT NULL,
        cost_unit TEXT, sampled_quantity TEXT, first_sample_at TEXT,
        last_sample_at TEXT, max_favorable_net_pct REAL,
        max_adverse_net_pct REAL, last_net_pct REAL, samples INTEGER,
        status TEXT, coverage TEXT,
        PRIMARY KEY(account,symbol,opened_at))""")
    db.execute("""CREATE TABLE IF NOT EXISTS order_annotations (
        account TEXT NOT NULL,client_order_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,side TEXT NOT NULL,reason TEXT,
        recorded_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS filled_outcomes (
        account TEXT NOT NULL, client_order_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL, side TEXT NOT NULL, filled_at TEXT,
        filled_quantity TEXT, fill_price TEXT, actual_fee TEXT,
        fee_verified INTEGER, allocated_buy_cost TEXT,
        net_realized_pnl TEXT, net_return_pct REAL,
        held_minutes REAL,exit_reason TEXT,
        mfe_net_pct REAL,mae_net_pct REAL,coverage TEXT)""")
    return db

def capture(root,policy,observations,series,positions,broker_bids,submit_note=None,
            selected=None,ai_status=None,execution_status=None,now=None):
    """Persist after broker order path finishes; never enters trading decisions."""
    if not isinstance(policy,dict) or not isinstance(policy.get("account"),str) or not policy["account"]:
        return {"status":"NO_CONFIGURED_ACCOUNT"}
    account=policy["account"]
    now=now or datetime.now(timezone.utc)
    journal=OrderJournal(root)
    buy_fee,buy_source=fee_pct(journal,account,"buy")
    sell_fee,sell_source=fee_pct(journal,account,"sell")
    if buy_fee>=100 or sell_fee>=100:raise ValueError("Fee estimate out of bounds")
    # Required favorable move is ask-to-bid break-even including both side fees.
    breakeven=((1+buy_fee/100)/(1-sell_fee/100)-1)*100
    target=((1+buy_fee/100)*(1+Decimal("0.5")/100)/(1-sell_fee/100)-1)*100
    with connect(root) as db:
        if isinstance(submit_note,dict):
            client=submit_note.get("client_order_id")
            if isinstance(client,str) and 8<=len(client)<=180:
                db.execute("""INSERT OR IGNORE INTO order_annotations
                    (account,client_order_id,symbol,side,reason,recorded_at)
                    VALUES(?,?,?,?,?,?)""",(
                      account,client,str(submit_note.get("symbol") or "")[:22],
                      str(submit_note.get("side") or "")[:8],
                      str(submit_note.get("reason") or "")[:220],
                      daystamp(now)))
        valid=[row for row in observations if isinstance(row,dict)
               and isinstance(row.get("symbol"),str) and quote(row)]
        # Update previously recorded candidate excursions from comparable
        # quote VENUE. No fill or broker execution is implied.
        for row in valid:
            bid,ask=quote(row)
            sym=row["symbol"]
            source=str(row.get("source") or "")[:40]
            venue="COINBASE_INDICATIVE" if source.startswith("COINBASE_") else "ROBINHOOD_QUOTE"
            past=db.execute("""SELECT id,entry_ask,buy_fee_pct,sell_fee_pct,
                    max_favorable_pct,max_adverse_pct,samples,at,
                    max_favorable_net_pct,max_adverse_net_pct
                    FROM candidates WHERE account=? AND symbol=?
                    AND quote_venue=? AND closed=0 ORDER BY id DESC LIMIT 120""",
                    (account,sym,venue)).fetchall()
            for cid,entry,fee_buy,fee_sell,mfe,mae,samples,at,net_mfe,net_mae in past:
                opened=utc(at)
                if opened is None:continue
                age=(now-opened).total_seconds()
                if age<0:continue
                if age>HORIZON_SECONDS+300:
                    db.execute("""UPDATE candidates SET closed=1,
                        horizon_status='EXPIRED_NO_TIMELY_SAME_VENUE_QUOTE'
                        WHERE id=?""",(cid,))
                    continue
                start=pos(entry)
                if start is None:continue
                # Hypothetical buy at ask and exit at available bid, fee adjusted.
                gross=(bid/start-1)*100
                net=(bid*(1-Decimal(str(fee_sell))/100)/
                         (start*(1+Decimal(str(fee_buy))/100))-1)*100
                if age>5:
                    at_horizon=age>=HORIZON_SECONDS
                    db.execute("""UPDATE candidates SET
                        max_favorable_pct=?,max_adverse_pct=?,
                        max_favorable_net_pct=?,max_adverse_net_pct=?,
                        last_net_pct=?,samples=?,last_at=?,closed=?,
                        horizon_status=CASE WHEN ?=1
                            THEN 'OBSERVED_60M_PLUS_MINUS_5M' ELSE horizon_status END,
                        horizon_net_pct=CASE WHEN ?=1
                            THEN ? ELSE horizon_net_pct END WHERE id=?""",
                        (max(float(gross),mfe) if mfe is not None else float(gross),
                         min(float(gross),mae) if mae is not None else float(gross),
                         max(float(net),net_mfe) if net_mfe is not None else float(net),
                         min(float(net),net_mae) if net_mae is not None else float(net),
                         float(net),(samples or 0)+1,daystamp(now),
                         int(at_horizon),int(at_horizon),int(at_horizon),
                         float(net) if at_horizon else None,cid))
        count=0
        for row in valid:
            if row.get("technical_approved") is not True:continue
            bid,ask=quote(row)
            sym=row["symbol"];source=str(row.get("source") or "")[:40]
            venue="COINBASE_INDICATIVE" if source.startswith("COINBASE_") else "ROBINHOOD_QUOTE"
            result,reason=shadow_signal(row,series.get(sym,[]),buy_fee,sell_fee)
            spread=(ask-bid)/ask*100
            db.execute("""INSERT INTO candidates (
                account,at,symbol,source,signal,spread_pct,broker_spread_pct,momentum_pct,
                history_points,history_seconds,trend_up,
                entry_ask,entry_bid,quote_venue,buy_fee_pct,sell_fee_pct,
                breakeven_move_pct,target_move_pct,shadow_result,shadow_reason,
                selection,ai_status,execution_status,samples,last_at,coverage)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                account,daystamp(now),sym,source,str(row.get("signal") or "")[:40],
                float(spread),
                float(val(row.get("broker_spread_pct"))) if
                   val(row.get("broker_spread_pct")) is not None else
                   float(spread) if source.startswith("ROBINHOOD_") else None,
                float(val(row.get("momentum_pct")) or 0),
                int(row.get("history_points") or 0),float(val(row.get("history_span_seconds")) or 0),
                int(row.get("trend_up") is True),str(ask),str(bid),venue,
                float(buy_fee),float(sell_fee),float(breakeven),float(target),
                result,reason[:240],
                "WORKER_PRIMARY_CANDIDATE" if selected==sym else "NOT_SELECTED_OR_LOWER_RANK",
                str(ai_status)[:60] if selected==sym else "NOT_EVALUATED_IN_THIS_RECORD",
                str(execution_status)[:70] if selected==sym else "NO_ORDER_LINK",
                1,daystamp(now),"HYPOTHETICAL; VENUE-CONSISTENT SAMPLED QUOTES"))
            count+=1
        # Bounded event retention without silently dropping specific symbols.
        db.execute("""DELETE FROM candidates WHERE id IN (
            SELECT id FROM candidates ORDER BY id DESC LIMIT -1 OFFSET ?)""",
                   (MAX_CANDIDATES,))
        _position_samples(db,account,positions,broker_bids,sell_fee,now)
        _reconciled_fills(db,journal,account)
        return {"status":"RECORDED","new_candidates":count,
            "estimated_buy_fee_pct":float(buy_fee),"estimated_sell_fee_pct":float(sell_fee),
            "break_even_move_pct":float(breakeven),"net_0_5pct_target_move_pct":float(target),
            "fee_basis":buy_source+" / "+sell_source,"shadow_only":True}

def _position_samples(db,account,positions,broker_bids,sell_fee,now):
    if not isinstance(positions,dict) or not isinstance(broker_bids,dict):return
    for sym,state in positions.items():
        if not isinstance(state,dict) or state.get("cost_basis_verified") is not True:continue
        cost=pos(state.get("average_unit_cost"));qty=pos(state.get("quantity"))
        at=utc(state.get("opened_at"));bid=pos(broker_bids.get(sym))
        if cost is None or qty is None or at is None or bid is None or now<at:continue
        net=(bid*(1-sell_fee/100)/cost-1)*100
        stamp=daystamp(at)
        previous=db.execute("""SELECT cost_unit,max_favorable_net_pct,max_adverse_net_pct,
                    samples FROM positions
                    WHERE account=? AND symbol=? AND opened_at=?""",(account,sym,stamp)).fetchone()
        changed=previous is not None and previous[0]!=str(cost)
        if previous is not None and not changed:
            high=max(float(net),previous[1]) if previous[1] is not None else float(net)
            low=min(float(net),previous[2]) if previous[2] is not None else float(net)
            samples=(previous[3] or 0)+1
            coverage="BROKER_BID_SAMPLES_SINCE_OPEN_OBSERVED"
        else:
            high=low=float(net);samples=1
            coverage=("COST_BASIS_CHANGED; EXCURSIONS_RESET" if changed else
                      "OBSERVATIONS_BEGIN_AT_FIRST_BROKER_BID")
        db.execute("""INSERT INTO positions(account,symbol,opened_at,cost_unit,
                   sampled_quantity,first_sample_at,last_sample_at,max_favorable_net_pct,
                   max_adverse_net_pct,last_net_pct,samples,status,coverage)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account,symbol,opened_at) DO UPDATE SET
                    cost_unit=excluded.cost_unit,
                    sampled_quantity=excluded.sampled_quantity,
                    first_sample_at=CASE WHEN positions.cost_unit!=excluded.cost_unit
                        THEN excluded.first_sample_at ELSE positions.first_sample_at END,
                    last_sample_at=excluded.last_sample_at,
                    max_favorable_net_pct=excluded.max_favorable_net_pct,
                    max_adverse_net_pct=excluded.max_adverse_net_pct,
                    last_net_pct=excluded.last_net_pct,samples=excluded.samples,
                    status=excluded.status,coverage=excluded.coverage""",(
                    account,sym,stamp,str(cost),str(qty),daystamp(now),
                    daystamp(now),high,low,float(net),samples,"OPEN",coverage))
    active={(s,daystamp(utc(p.get("opened_at")))) for s,p in positions.items()
        if isinstance(p,dict) and utc(p.get("opened_at")) is not None}
    for sym,stamp in db.execute("SELECT symbol,opened_at FROM positions WHERE account=? AND status='OPEN'",(account,)):
        if (sym,stamp) not in active:
            db.execute("""UPDATE positions SET status='CLOSED_AS_OF_WORKER_SCAN'
                WHERE account=? AND symbol=? AND opened_at=?""",(account,sym,stamp))

def _reconciled_fills(db,journal,account):
    """Reconstruct verified lot costs; fill outcomes keyed by actual client IDs."""
    rows=journal.load()["orders"]
    inventory={}
    for row in rows:
        if not isinstance(row,dict) or row.get("account")!=account:continue
        sym=row.get("symbol")
        if not isinstance(sym,str):continue
        side=row.get("side");status=row.get("status")
        s=inventory.setdefault(sym,{"quantity":Decimal(0),"cost":Decimal(0),
            "verified":True,"opened":None})
        if side=="external_reduction" and status=="externally_reconciled":
            qty=pos(row.get("quantity"))
            if qty is None or qty>s["quantity"]:
                s["verified"]=False
            elif s["quantity"]>0:
                unit=s["cost"]/s["quantity"]
                s["quantity"]-=qty;s["cost"]-=unit*qty
                if s["quantity"]==0:s["opened"]=None
            continue
        if status!="filled" or side not in ("buy","sell"):continue
        q=pos(row.get("filled_quantity"));price=pos(row.get("average_fill_price"))
        fee=val(row.get("fee_charged"))
        verified=(row.get("fee_verified") is True and fee is not None and fee>=0)
        at=utc(row.get("filled_at"))
        client=row.get("client_order_id")
        if not isinstance(client,str) or not client:continue
        allocated=None;pnl=None;percent=None;held=None
        coverage="FILL_VERIFIED_PNL_UNAVAILABLE"
        if side=="buy":
            if q is not None and price is not None:
                if s["quantity"]==0:
                    # An earlier unverifiable closed lot must not contaminate
                    # the next independently verified acquisition.
                    s["opened"]=at;s["verified"]=True;s["cost"]=Decimal(0)
                s["quantity"]+=q
                s["cost"]+=q*price+(fee if verified else 0)
                s["verified"]=s["verified"] and verified
                coverage=("BUY_WITH_VERIFIED_FEE" if verified else
                          "BUY_FEE_NOT_VERIFIED")
        else:
            if (q is not None and price is not None and verified and
                    s["verified"] and s["quantity"]>=q and s["quantity"]>0):
                allocated=s["cost"]/s["quantity"]*q
                pnl=q*price-fee-allocated
                percent=float(pnl/allocated*100) if allocated>0 else None
                if at is not None and s["opened"] is not None:
                    held=max(0.0,(at-s["opened"]).total_seconds()/60)
                coverage="VERIFIED_NET_PNL_SAMPLED_EXCURSIONS_OPTIONAL"
            if q is not None and s["quantity"]>0 and q<=s["quantity"]:
                basis=s["cost"]/s["quantity"]*q
                s["quantity"]-=q;s["cost"]-=basis
                if s["quantity"]==0:
                    s["cost"]=Decimal(0);s["opened"]=None
            else:s["verified"]=False
        annotation=db.execute("""SELECT reason FROM order_annotations
                WHERE account=? AND client_order_id=?""",(account,client)).fetchone()
        # Latest recorded broker-bid observations for this symbol are bounded
        # evidence, not tick maxima or automatically linked to a closed order.
        excursions=None
        if side=="sell" and at:
            excursions=db.execute("""SELECT max_favorable_net_pct,max_adverse_net_pct,
                  first_sample_at,last_sample_at FROM positions WHERE account=?
                  AND symbol=? AND opened_at<=? AND first_sample_at<=?
                  ORDER BY opened_at DESC LIMIT 1""",
                  (account,sym,daystamp(at),daystamp(at))).fetchone()
            if excursions and utc(excursions[3]) and utc(excursions[3])>at:
                excursions=None
        note=(annotation[0] if annotation else
               "UNKNOWN: order predates direct diagnostic reason capture")
        db.execute("""INSERT INTO filled_outcomes(account,client_order_id,symbol,
             side,filled_at,filled_quantity,fill_price,actual_fee,fee_verified,
             allocated_buy_cost,net_realized_pnl,net_return_pct,held_minutes,
             exit_reason,mfe_net_pct,mae_net_pct,coverage)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(client_order_id) DO UPDATE SET
              filled_at=excluded.filled_at,filled_quantity=excluded.filled_quantity,
              fill_price=excluded.fill_price,actual_fee=excluded.actual_fee,
              fee_verified=excluded.fee_verified,
              allocated_buy_cost=excluded.allocated_buy_cost,
              net_realized_pnl=excluded.net_realized_pnl,
              net_return_pct=excluded.net_return_pct,held_minutes=excluded.held_minutes,
              exit_reason=excluded.exit_reason,
              mfe_net_pct=excluded.mfe_net_pct,mae_net_pct=excluded.mae_net_pct,
              coverage=excluded.coverage""",(
              account,client,sym,side,daystamp(at) if at else None,
              str(q) if q else None,str(price) if price else None,
              str(fee) if verified else None,int(verified),
              str(allocated) if allocated is not None else None,
              str(pnl) if pnl is not None else None,percent,held,note,
              excursions[0] if excursions else None,excursions[1] if excursions else None,
              coverage+("; EXCURSIONS_SAMPLED_NOT_TICK_EXTREMA"
                        if excursions else "; NO_MATCHED_BID_SAMPLES")))

def summary(root,account,limit=30):
    """Bounded account-scoped display; no order IDs, API credentials, or secrets."""
    if not isinstance(account,str) or not account:
        return {"status":"ACCOUNT_NOT_CONFIGURED","candidates":[],"positions":[]}
    path=Path(root)/"robinhood"/DB_NAME
    if not path.exists():
        return {"status":"AWAITING_NEW_OBSERVATIONS","candidates":[],"positions":[],
                "note":"No historical MFE/MAE can be reconstructed without samples"}
    # Authenticated dashboard reads do not mutate the diagnostics database.
    with sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=2) as db:
        db.execute("PRAGMA query_only=ON")
        candidates=db.execute("""SELECT at,symbol,source,spread_pct,broker_spread_pct,momentum_pct,
             buy_fee_pct,sell_fee_pct,breakeven_move_pct,target_move_pct,
             shadow_result,shadow_reason,selection,max_favorable_pct,max_adverse_pct,
             last_net_pct,samples,quote_venue,
             max_favorable_net_pct,max_adverse_net_pct,
             horizon_status,horizon_net_pct
             FROM candidates WHERE account=? ORDER BY id DESC LIMIT ?""",
             (account,min(max(int(limit),1),80))).fetchall()
        positions=db.execute("""SELECT symbol,opened_at,max_favorable_net_pct,
            max_adverse_net_pct,last_net_pct,samples,status,coverage FROM positions
            WHERE account=? ORDER BY last_sample_at DESC LIMIT 20""",(account,)).fetchall()
        outcomes=db.execute("""SELECT symbol,side,filled_at,actual_fee,net_realized_pnl,
            net_return_pct,held_minutes,exit_reason,mfe_net_pct,mae_net_pct,coverage
            FROM filled_outcomes WHERE account=? AND side='sell'
            ORDER BY filled_at DESC LIMIT 30""",(account,)).fetchall()
        totals=db.execute("""SELECT COUNT(*),
               SUM(CASE WHEN shadow_result='SHADOW_PASS_REBOUND' THEN 1 ELSE 0 END),
               SUM(CASE WHEN max_favorable_pct IS NOT NULL THEN 1 ELSE 0 END)
               FROM candidates WHERE account=?""",(account,)).fetchone()
    keys=["at","symbol","source","spread_pct","broker_spread_pct","momentum_pct","buy_fee_pct",
       "sell_fee_pct","breakeven_move_pct","target_move_pct","shadow_result",
       "shadow_reason","selection","mfe_gross_pct","mae_gross_pct",
       "last_hypothetical_net_pct","samples","quote_venue",
       "mfe_hypothetical_net_pct","mae_hypothetical_net_pct",
       "horizon_status","horizon_hypothetical_net_pct"]
    pkeys=["symbol","opened_at","mfe_estimated_net_pct","mae_estimated_net_pct",
           "last_estimated_net_pct","samples","status","coverage"]
    ekeys=["symbol","side","filled_at","verified_fee_usd",
           "verified_net_realized_pnl_usd","net_return_pct","holding_minutes",
           "exit_reason","mfe_sampled_net_pct","mae_sampled_net_pct","coverage"]
    return {"status":"READY","shadow_only":True,
        "tracked_candidates":totals[0],"shadow_pass_count":totals[1] or 0,
        "candidates_with_excursion_samples":totals[2] or 0,
        "candidates":[dict(zip(keys,r)) for r in candidates],
        "positions":[dict(zip(pkeys,r)) for r in positions],
        "exits":[dict(zip(ekeys,r)) for r in outcomes],
        "note":"Shadow predictions are not trades; MFE/MAE are observed samples, not intrabar extrema"}

def export_tables(root,account):
    """Bounded, account-only datasets for two additional XLSX report sheets."""
    candidate_rows=[["Evaluated UTC","Symbol","Quote venue","Source",
        "Feed entry spread %","Robinhood broker entry spread %","Momentum %","Technical coverage samples",
        "Technical history sec","Estimated buy fee %","Estimated sell fee %",
        "Fee-adjusted break-even move %","Move for +0.5% net %",
        "Shadow entry assessment (NOT live)","Shadow reason",
        "Selected by old engine","AI status observed","Execution status observed",
        "Max observed favorable GROSS move %","Max observed adverse GROSS move %",
        "Latest hypothetical net return %","Observed quote samples","Evidence",
        "Max observed hypothetical NET gain %","Max observed hypothetical NET loss %",
        "60-min mark coverage","Hypothetical 60-min net return %"]]
    trade_rows=[["Filled UTC","Symbol","Side","Verified actual fee USD",
        "Allocated purchase cost USD","Verified realized net P/L USD",
        "Verified net return %","Holding time minutes",
        "Directly captured order rationale","Max sampled favorable net % (Robinhood bids)",
        "Max sampled adverse net % (Robinhood bids)","Coverage"]]
    path=Path(root)/"robinhood"/DB_NAME
    if not path.exists():return candidate_rows,trade_rows
    with sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        for row in db.execute("""SELECT at,symbol,quote_venue,source,spread_pct,
            broker_spread_pct,momentum_pct,history_points,history_seconds,buy_fee_pct,sell_fee_pct,
            breakeven_move_pct,target_move_pct,shadow_result,shadow_reason,
            selection,ai_status,execution_status,
            max_favorable_pct,max_adverse_pct,last_net_pct,samples,coverage,
            max_favorable_net_pct,max_adverse_net_pct,horizon_status,horizon_net_pct
            FROM candidates WHERE account=? ORDER BY id DESC LIMIT 5000""",(account,)):
            candidate_rows.append(list(row))
        for row in db.execute("""SELECT filled_at,symbol,side,actual_fee,
            allocated_buy_cost,net_realized_pnl,net_return_pct,held_minutes,
            exit_reason,mfe_net_pct,mae_net_pct,coverage
            FROM filled_outcomes WHERE account=? ORDER BY filled_at DESC LIMIT 4000""",
            (account,)):
            cells=list(row)
            # Export financial numbers as numeric Excel cells, not text, so
            # they can be sorted, charted and summarized without conversion.
            for ix in (3,4,5):
                v=val(cells[ix])
                cells[ix]=float(v) if v is not None else None
            trade_rows.append(cells)
    return candidate_rows,trade_rows
