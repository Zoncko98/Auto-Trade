"""Read-only reconciliation of the isolated V2 simulated crypto fills.

Only confirmed SIM- ledger rows are included. Realized returns use the exact
SimulatedBroker weighted-cost (including purchase fees), sale proceeds minus
sale fees, and verified cash/inventory. No market API, credential, broker order,
risk-policy mutation, or inferred live return.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json,sqlite3

from .paper_activity import _private_readonly,_stamp,_decimal,SYMBOLS
from .models import utc

STARTING_CASH=Decimal("1000")
TOLERANCE=Decimal("0.00001")


def _positive(v):
    x=_decimal(v)
    if x<=0:
        raise ValueError("NONPOSITIVE_SIM_EXECUTION")
    return x


def read_economics(directory, *, now=None):
    now=utc(now or datetime.now(timezone.utc))
    result={sym:{
        "symbol":sym,"scope":"CUMULATIVE_VERIFIED_SIMULATED_EXECUTIONS",
        "state":"SIMULATOR_LEDGER_UNAVAILABLE",
        "simulated_only":True,"live_orders_authorized":False,
        "completed_round_trips":None,"winning_round_trips":None,
        "simulated_fills":None,"simulated_buys":None,"simulated_sells":None,
        "total_assumed_fees_usd":None,
        "realized_net_pnl_usd":None,
        "remaining_quantity":None,
        "cash_reconciled":False,
        "slippage_attribution":"NOT_SEPARATELY_VERIFIED",
    } for sym in SYMBOLS}
    db=_private_readonly(directory,"sim.sqlite3")
    if db is None:
        return result
    try:
        rows=db.execute("""SELECT account_id,asset_class,cash,fractional,enabled
                           FROM sim_accounts WHERE account_id IN (?,?)""",
                        tuple(SYMBOLS.values())).fetchall()
        account_map={r[0]:r for r in rows}
        if len(account_map)!=2:
            raise ValueError("SIMULATOR_ACCOUNT_UNVERIFIED")
        position_rows=db.execute(
            """SELECT account_id,symbol,qty,average_cost
                 FROM sim_positions WHERE account_id IN (?,?)""",
            tuple(SYMBOLS.values())).fetchall()
        positions={}
        for account,sym,qty,basis in position_rows:
            if sym not in SYMBOLS or SYMBOLS[sym]!=account:
                raise ValueError("SIMULATOR_POSITION_IDENTITY_INVALID")
            if (account,sym) in positions:
                raise ValueError("SIMULATOR_DUPLICATE_POSITION")
            positions[(account,sym)]=(_positive(qty),_positive(basis))
        fills=db.execute(
            """SELECT key,account_id,intent_document,broker_order_id,
                      quantity,price,fee,created_at
                 FROM sim_orders WHERE account_id IN (?,?)
                 ORDER BY created_at ASC LIMIT 10001""",
            tuple(SYMBOLS.values())).fetchall()
        if len(fills)>10000:
            raise ValueError("SIMULATOR_FILL_JOURNAL_UNBOUNDED")
        work={sym:{"qty":Decimal(0),"basis":Decimal(0),
                   "cash":STARTING_CASH,"fees":Decimal(0),
                   "realized":Decimal(0),"f":0,"b":0,"s":0,
                   "wins":0,"rounds":0,"open_net":Decimal(0)}
              for sym in SYMBOLS}
        for key,account,document,order_id,qty_text,price_text,fee_text,created in fills:
            sym=next((s for s,a in SYMBOLS.items() if a==account),None)
            if sym is None or not isinstance(key,str) or not order_id=="SIM-"+key:
                raise ValueError("SIMULATOR_FILL_ID_UNVERIFIED")
            at=_stamp(created)
            if at>now+timedelta(seconds=2):
                raise ValueError("SIMULATOR_FUTURE_FILL")
            intent=json.loads(document)
            if (not isinstance(intent,dict)
                or intent.get("account_id")!=account
                or intent.get("symbol")!=sym
                or intent.get("asset_class")!="CRYPTO"
                or intent.get("side") not in ("BUY","SELL")):
                raise ValueError("SIMULATOR_FILL_DOCUMENT_MISMATCH")
            qty=_positive(qty_text)
            price=_positive(price_text)
            fee=_decimal(fee_text)
            if _positive(intent.get("quantity"))!=qty:
                raise ValueError("SIMULATOR_FILL_QUANTITY_MISMATCH")
            t=work[sym]
            t["f"]+=1;t["fees"]+=fee
            notional=qty*price
            if intent["side"]=="BUY":
                t["b"]+=1
                t["cash"]-=notional+fee
                if t["cash"]<-TOLERANCE:
                    raise ValueError("SIMULATOR_NEGATIVE_CASH")
                t["basis"]+=notional+fee
                t["qty"]+=qty
            else:
                t["s"]+=1
                if t["qty"]<qty or t["qty"]<=0:
                    raise ValueError("SIMULATOR_SELL_WITHOUT_VERIFIED_HOLDING")
                released=t["basis"]*qty/t["qty"]
                profit=notional-fee-released
                t["realized"]+=profit
                t["open_net"]+=profit
                t["cash"]+=notional-fee
                t["qty"]-=qty
                t["basis"]-=released
                if t["qty"]==0:
                    t["rounds"]+=1
                    if t["open_net"]>0:t["wins"]+=1
                    t["open_net"]=Decimal(0)
                    t["basis"]=Decimal(0)
        for sym,account in SYMBOLS.items():
            row=account_map[account]
            if row[1]!="CRYPTO" or row[3]!=1 or row[4]!=1:
                raise ValueError("SIMULATOR_ACCOUNT_CLASS_UNVERIFIED")
            t=work[sym]
            actual_cash=_decimal(row[2])
            if abs(actual_cash-t["cash"])>TOLERANCE:
                raise ValueError("SIMULATOR_CASH_RECONCILIATION_REQUIRED")
            held=positions.get((account,sym))
            if t["qty"]==0:
                if held is not None:raise ValueError("SIMULATOR_POSITION_MISMATCH")
            else:
                if (held is None or abs(held[0]-t["qty"])>TOLERANCE or
                    abs(held[1]-(t["basis"]/t["qty"]))>TOLERANCE):
                    raise ValueError("SIMULATOR_POSITION_MISMATCH")
            result[sym].update({
                "state":"SIMULATED_CASH_AND_POSITIONS_RECONCILED",
                "completed_round_trips":t["rounds"],
                "winning_round_trips":t["wins"],
                "simulated_fills":t["f"],
                "simulated_buys":t["b"],
                "simulated_sells":t["s"],
                "total_assumed_fees_usd":str(t["fees"].quantize(Decimal("0.01"))),
                "realized_net_pnl_usd":str(t["realized"].quantize(Decimal("0.01"))),
                "remaining_quantity":format(t["qty"],".8f"),
                "cash_reconciled":True,
            })
    except (ValueError,sqlite3.Error,TypeError,OverflowError,KeyError,
            InvalidOperation, json.JSONDecodeError):
        for row in result.values():
            row["state"]="SIMULATOR_RECONCILIATION_REQUIRED"
    finally:
        db.close()
    return result
