"""Production V2 Robinhood migration preflight using only existing signed GETs.

This checks actual account authorization, holdings, order history, open order
hazards, pair increments and quote timing. It never signs a POST, imports
credentials into logs or changes V1 broker journals. An unavailable check
blocks cutover rather than authorizing a live V2 worker.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import argparse
import time
import os
from .models import amount,utc
from .market_sources import robinhood_market_quote,MarketSourceError
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json

def _probe(state,client,policy,*,now=None):
    now=utc(now or datetime.now(timezone.utc))
    report={
        "schema":1,"broker":"robinhood_crypto","checked_at":now.isoformat(),
        "mode":"AUTHENTICATED_SIGNED_READ_ONLY",
        "v2_live_orders_submitted":0,
        "v2_live_order_authority":False,
        "cutover_ready":False,
        "account_verified":False,"holdings_verified":False,
        "broker_history_verified":False,"local_journal_matched":False,
        "broker_open_order_count":None,"local_unresolved_count":None,
        "funding_source":"UNVERIFIED","settled_cash_verified":False,
        "broker_session_verified":False,
        "quote_timestamp_verified_symbols":0,
        "pairs_checked":0,"first_blocker":"BROKER_AUTH_UNVERIFIED",
    }
    if not isinstance(policy,dict) or policy.get("enabled") is not True:
        report["first_blocker"]="V1_ACCOUNT_OPERATOR_PERMISSION_NOT_ARMED"
        return report
    account_ref=policy.get("account")
    if not isinstance(account_ref,str) or not account_ref:
        report["first_blocker"]="ACCOUNT_SELECTION_REQUIRED"
        return report
    try:
        accounts=client.list_accounts()
        selected=[a for a in accounts if isinstance(a,dict)
                  and a.get("account_number")==account_ref]
        if (len(selected)!=1 or selected[0].get("status")!="active"
            or selected[0].get("is_api_tradable") is not True or
            selected[0].get("buying_power_currency")!="USD"):
            report["first_blocker"]="SIGNED_ACCOUNT_UNAVAILABLE_OR_INELIGIBLE"
            return report
        account=selected[0]
        amount(account.get("buying_power"),"USD buying power")
        report["account_verified"]=True
        report["funding_source"]="SIGNED_USD_BUYING_POWER_NOT_SETTLED_CASH"
    except Exception:
        report["first_blocker"]="SIGNED_ACCOUNT_OR_BUYING_POWER_READ_FAILED"
        return report
    try:
        holdings=client.positions(account_ref)
        if not isinstance(holdings,list):raise ValueError
        seen=set()
        for row in holdings:
            if not isinstance(row,dict):raise ValueError
            symbol=row.get("asset_code")
            if (not isinstance(symbol,str) or not symbol or symbol in seen):
                raise ValueError
            seen.add(symbol)
            amount(row.get("total_quantity"),"signed holding")
        report["holdings_verified"]=True
    except Exception:
        report["first_blocker"]="SIGNED_HOLDINGS_UNVERIFIED"
        return report
    try:
        broker_orders=client.orders(account_ref)
        if not isinstance(broker_orders,list):raise ValueError
        broker_ids=set()
        signed_by_client={}
        broker_pending=0
        for row in broker_orders:
            if not isinstance(row,dict):raise ValueError
            cid=row.get("client_order_id")
            if not isinstance(cid,str) or not cid or cid in broker_ids:raise ValueError
            broker_ids.add(cid)
            signed_by_client[cid]=row
            status=row.get("state",row.get("status"))
            if not isinstance(status,str):raise ValueError
            if status.lower() not in ("filled","canceled","cancelled","rejected",
                  "expired","failed","open","queued","pending","confirmed",
                  "partially_filled"):
                raise ValueError
            if status.lower() not in ("filled","canceled","cancelled","rejected","expired","failed"):
                broker_pending+=1
        report["broker_open_order_count"]=broker_pending
        report["broker_history_verified"]=True
    except Exception:
        report["first_blocker"]="SIGNED_BROKER_ORDER_HISTORY_UNVERIFIED"
        return report
    try:
        from robinhood_order_journal import OrderJournal,FINAL
        records=OrderJournal(state).load()["orders"]
        unverified=[r for r in records if isinstance(r,dict) and
                    r.get("account")==account_ref and r.get("status") not in FINAL]
        report["local_unresolved_count"]=len(unverified)
        if any(r.get("client_order_id") not in broker_ids for r in unverified):
            report["first_blocker"]="LOCAL_INTENT_NOT_FOUND_IN_SIGNED_BROKER_HISTORY"
            return report
        # Previously final BOT fills also require exact signed broker evidence.
        # A locally asserted filled state does not prove the fill independently.
        for local in records:
            if not isinstance(local,dict) or local.get("account")!=account_ref:
                continue
            if local.get("status")!="filled":
                continue
            signed=signed_by_client.get(local.get("client_order_id"))
            if not isinstance(signed,dict) or str(signed.get("state","")).lower()!="filled":
                report["first_blocker"]="HISTORICAL_V1_FILL_MISSING_FROM_SIGNED_BROKER"
                return report
            try:
                signed_qty=amount(signed.get("filled_asset_quantity"),
                                  "signed historical fill",False)
                local_qty=amount(local.get("filled_quantity"),
                                 "saved historical fill",False)
                signed_px=amount(signed.get("average_price"),
                                 "signed historical price",False)
                if signed_qty!=local_qty or signed_px<=0:
                    raise ValueError
            except (ValueError,TypeError):
                report["first_blocker"]="HISTORICAL_V1_FILL_QTY_OR_PRICE_MISMATCH"
                return report
        report["local_journal_matched"]=True
    except Exception:
        report["first_blocker"]="LOCAL_V1_ORDER_JOURNAL_UNVERIFIED"
        return report
    if report["broker_open_order_count"] or report["local_unresolved_count"]:
        report["first_blocker"]="OPEN_BROKER_OR_LOCAL_ORDER_RECONCILIATION_REQUIRED"
        return report
    try:
        pairs=client.trading_pairs()
        verified={p.get("symbol"):p for p in pairs if isinstance(p,dict)
                  and p.get("is_api_tradable") is True}
        if not isinstance(pairs,list):raise ValueError
        from .models import AssetClass
        count=0
        for symbol in ("BTC-USD","ETH-USD"):
            meta=verified.get(symbol)
            if not meta:continue
            for field in ("min_order_amount","asset_increment","max_order_size"):
                amount(meta.get(field),field,False)
            count+=1
        report["pairs_checked"]=count
        if count==0:
            report["first_blocker"]="SIGNED_PAIR_PERMISSIONS_UNVERIFIED"
            return report
    except Exception:
        report["first_blocker"]="SIGNED_PAIR_INCREMENT_OR_MINIMUM_UNVERIFIED"
        return report
    quote_count=0
    for symbol in ("BTC-USD","ETH-USD"):
        if symbol not in verified:continue
        try:
            quote=robinhood_market_quote(client.quote(symbol),symbol,now=now)
            if quote.last is not None and quote.bid>0 and quote.ask>=quote.bid:
                quote_count+=1
        except Exception:
            pass
    report["quote_timestamp_verified_symbols"]=quote_count
    if quote_count==0:
        report["first_blocker"]="BROKER_QUOTE_TIMESTAMP_OR_LAST_TRADE_UNVERIFIED"
        return report
    # Even a fresh signed quote does not establish a single-writer lease,
    # independently certified settled funding or broker market entitlement.
    report["first_blocker"]="V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED"
    return report

def run_once(state_dir,client=None,now=None):
    base=Path(state_dir)
    now=utc(now or datetime.now(timezone.utc))
    from robinhood_policy import read_policy
    status={"schema":1,"broker":"robinhood_crypto",
        "checked_at":now.isoformat(),"mode":"AUTHENTICATED_SIGNED_READ_ONLY",
        "v2_live_order_authority":False,"cutover_ready":False,
        "first_blocker":"SIGNED_BROKER_PREFLIGHT_UNAVAILABLE"}
    try:
        policy=read_policy(base)
        if client is None:
            from robinhood_crypto_gateway import RobinhoodCryptoAdapter
            client=RobinhoodCryptoAdapter.from_state(base)
        status=_probe(base,client,policy,now=now)
    except Exception:
        pass
    target=base/"v2"/"broker_migration"
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    if target.stat().st_mode & 0o077:
        raise PermissionError("Private V2 migration directory required")
    _atomic_json(target/"robinhood_crypto.json",status)
    return status

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",default=os.getenv("STATE_DIR","/state"))
    args=parser.parse_args()
    result=run_once(args.state_dir)
    print("V2 signed broker migration probe:",result["first_blocker"],flush=True)

if __name__=="__main__":main()
