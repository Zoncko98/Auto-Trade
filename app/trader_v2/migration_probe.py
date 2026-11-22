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
from .robinhood_signed_receipts import (
    signed_holding_quantity,signed_pair_limits,BrokerEvidenceUnavailable)
from .market_sources import robinhood_market_quote,MarketSourceError
from .robinhood_dual_quote import attest_quote,DualQuoteUnavailable
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json

def _probe(state,client,policy,*,now=None,public_feed=None):
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
        "spot_buying_power_verified":False,
        "crypto_24x7_access_verified":False,
        "broker_session_verified":False,
        "quote_timestamp_verified_symbols":0,
        "independent_trade_crosscheck_symbols":0,
        "independent_broker_venue_timestamp_verified":False,
        "pairs_checked":0,"historical_fills_checked":0,
        "first_blocker":"BROKER_AUTH_UNVERIFIED",
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
        # Signed Robinhood spot Crypto API buying_power is the directly
        # executable USD spending allowance, NOT US-equity settled cash.
        # 0 is still a verified signed allowance (entry risk then blocks).
        amount(account.get("buying_power"),"USD buying power")
        report["account_verified"]=True
        report["spot_buying_power_verified"]=True
        report["funding_source"]="SIGNED_CRYPTO_SPOT_USD_BUYING_POWER_NOT_SETTLED_CASH"
    except Exception:
        report["first_blocker"]="SIGNED_ACCOUNT_OR_BUYING_POWER_READ_FAILED"
        return report
    try:
        holdings=client.positions(account_ref)
    except Exception as exc:
        # Provider exception CLASS only; never persist signed response text,
        # order IDs, holding assets, balances, tokens or credential material.
        report["holdings_failure_category"]="SIGNED_POSITIONS_REQUEST_FAILED"
        report["holdings_error_class"]=type(exc).__name__ if type(exc).__name__ in (
            "RobinhoodUnavailable","TimeoutError","ConnectionError","HTTPError",
            "ValueError","OSError") else "OTHER"
        report["first_blocker"]="SIGNED_HOLDINGS_UNVERIFIED"
        return report
    if not isinstance(holdings,list):
        report["holdings_failure_category"]="SIGNED_POSITIONS_NOT_LIST"
        report["first_blocker"]="SIGNED_HOLDINGS_UNVERIFIED"
        return report
    report["holdings_rows_observed"]=len(holdings)
    seen=set()
    for row in holdings:
        if not isinstance(row,dict):
            report["holdings_failure_category"]="SIGNED_HOLDING_ROW_NOT_OBJECT"
            break
        symbol=row.get("asset_code")
        if not isinstance(symbol,str) or not symbol:
            report["holdings_failure_category"]="SIGNED_HOLDING_ASSET_MISSING"
            break
        if symbol in seen:
            report["holdings_failure_category"]="SIGNED_HOLDING_DUPLICATE_ASSET"
            break
        seen.add(symbol)
        try:signed_holding_quantity(row.get("total_quantity"))
        except BrokerEvidenceUnavailable as exc:
            report["holdings_failure_category"]=exc.code
            break
    else:
        report["holdings_verified"]=True
    if not report["holdings_verified"]:
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
            # V1 has already normalized fills from signed broker executions.
            # Reuse EXACTLY its source-faithful weighted-average fallback
            # rather than assuming every response has an average_price field.
            signed_qty,signed_px,signed_fee,_=OrderJournal._fill_details(signed)
            try:
                if signed_qty is None or signed_px is None:
                    raise BrokerEvidenceUnavailable("SIGNED_FILL_ECONOMICS_UNAVAILABLE")
                signed_qty=signed_holding_quantity(signed_qty)
                signed_px=signed_holding_quantity(signed_px)
                local_qty=signed_holding_quantity(local.get("filled_quantity"))
                local_px=signed_holding_quantity(local.get("average_fill_price"))
                if min(signed_qty,signed_px,local_qty,local_px)<=0:
                    raise BrokerEvidenceUnavailable("HISTORICAL_ZERO_OR_INVALID_FILL")
                if signed_qty!=local_qty:
                    raise BrokerEvidenceUnavailable("HISTORICAL_SIGNED_V1_QUANTITY_DIFFERENCE")
                if signed_px!=local_px:
                    raise BrokerEvidenceUnavailable("HISTORICAL_SIGNED_V1_PRICE_DIFFERENCE")
                if signed_fee is None or local.get("fee_verified") is False:
                    raise BrokerEvidenceUnavailable("HISTORICAL_SIGNED_FEE_UNVERIFIED")
                local_fee=signed_holding_quantity(local.get("fee_charged"))
                signed_fee=signed_holding_quantity(signed_fee)
                if signed_fee!=local_fee:
                    raise BrokerEvidenceUnavailable("HISTORICAL_SIGNED_V1_FEE_DIFFERENCE")
            except BrokerEvidenceUnavailable as exc:
                # Never expose symbol, account, order UUID or amount.
                report["historical_fill_failure_category"]=exc.code
                report["first_blocker"]="HISTORICAL_V1_FILL_EVIDENCE_UNVERIFIED"
                return report
            report["historical_fills_checked"]+=1
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
            signed_pair_limits(meta)
            count+=1
        report["pairs_checked"]=count
        if count==0:
            report["first_blocker"]="SIGNED_PAIR_PERMISSIONS_UNVERIFIED"
            return report
        # Crypto has no US-equity RTH session: signed active account and
        # API-tradable pair permit 24x7 capability, subject to maintenance,
        # independent live bid/ask proof and fresh order-time checks.
        # No stock-market entitlement or past broker fill is fabricated.
        report["crypto_24x7_access_verified"]=report["account_verified"] is True
    except BrokerEvidenceUnavailable as exc:
        report["pair_failure_category"]=exc.code
        report["first_blocker"]="SIGNED_PAIR_INCREMENT_OR_MINIMUM_UNVERIFIED"
        return report
    except Exception:
        report["pair_failure_category"]="SIGNED_PAIR_SOURCE_READ_UNAVAILABLE"
        report["first_blocker"]="SIGNED_PAIR_INCREMENT_OR_MINIMUM_UNVERIFIED"
        return report
    quote_count=0
    signed_timestamps_verified=0
    independent_count=0
    quote_failures={}
    for symbol in ("BTC-USD","ETH-USD"):
        if symbol not in verified:continue
        # Fetch the independent public trade FIRST. A slow Coinbase GET
        # must not leave an otherwise valid signed Robinhood bid/ask stale
        # before cross-source attestation. Missing data never authorizes.
        public_trade=None
        public_error=False
        if public_feed is not None:
            try:
                public_trade=public_feed(symbol.replace("-",""))
            except Exception:
                public_error=True
        started=datetime.now(timezone.utc)
        try:
            raw=client.quote(symbol)
        except Exception:
            quote_failures[symbol]="SIGNED_BROKER_QUOTE_GET_UNAVAILABLE"
            continue
        completed=datetime.now(timezone.utc)
        try:
            quote=robinhood_market_quote(raw,symbol,now=completed)
            signed_timestamps_verified+=1
            signed_age=(completed-quote.observed_at).total_seconds()
            if (quote.last is not None and quote.source_tradable and
                    -2<=signed_age<=20 and quote.bid>0 and
                    quote.ask>=quote.bid and
                    (quote.ask-quote.bid)/quote.ask<=Decimal("0.015")):
                quote_count+=1
                continue
        except MarketSourceError as exc:
            # If the provider supplied a timestamp that is malformed or
            # stale, do not bypass it using an independent public trade.
            if exc.code in ("EXCHANGE_QUOTE_STALE_OR_FUTURE",
                            "QUOTE_TIMESTAMP_INVALID"):
                rows=raw.get("results",[]) if isinstance(raw,dict) else []
                if isinstance(rows,list) and any(
                    isinstance(x,dict) and x.get("symbol")==symbol and
                    any(k in x for k in ("timestamp","quote_timestamp","updated_at"))
                    for x in rows):
                    quote_failures[symbol]="SIGNED_BROKER_TIMESTAMP_INVALID_OR_STALE"
                    continue
            quote_failures[symbol]="SIGNED_BROKER_NATIVE_QUOTE_UNVERIFIED"
        except (ValueError,TypeError):
            quote_failures[symbol]="SIGNED_BROKER_NATIVE_QUOTE_UNVERIFIED"
        if public_trade is None:
            quote_failures[symbol]=("PUBLIC_TRADE_GET_UNAVAILABLE" if public_error
                                   else "INDEPENDENT_TRADE_NOT_CONFIGURED")
            continue
        try:
            proof=attest_quote(raw,public_trade,symbol,
                 request_started_at=started,
                 request_completed_at=completed,
                 examined_at=datetime.now(timezone.utc))
            if proof.public["independent_trade_timestamp_verified"]:
                independent_count+=1
                quote_failures.pop(symbol,None)
        except DualQuoteUnavailable as exc:
            quote_failures[symbol]=exc.code
        except (ValueError,TypeError,OverflowError):
            quote_failures[symbol]="BROKER_PUBLIC_CROSSCHECK_INVALID"
    report["quote_timestamp_verified_symbols"]=signed_timestamps_verified
    report["signed_last_trade_verified_symbols"]=quote_count
    report["independent_trade_crosscheck_symbols"]=independent_count
    # Structured allowlisted failure codes, never credentials, prices or IDs.
    report["quote_validation_failures"]=quote_failures
    # Independent broker-signed V2 quantity-specific estimate diagnostics.
    # This CAN identify crossed top-of-book versus an estimate, but cannot
    # substitute its quote or fee for execution/risk or unlock launch gates.
    from .robinhood_estimate_diagnostics import observed as estimate_observed
    report["signed_v2_estimate_diagnostics"]={
       symbol:estimate_observed(client,symbol)
       for symbol in ("BTC-USD","ETH-USD") if symbol in verified}
    if quote_count==0 and independent_count==0:
        report["first_blocker"]="BROKER_QUOTE_TIMESTAMP_OR_LAST_TRADE_UNVERIFIED"
        return report
    # Even a fresh signed quote does not establish a single-writer lease,
    # independently certified settled funding or broker market entitlement.
    report["first_blocker"]="V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED"
    return report

def run_once(state_dir,client=None,now=None,public_feed=None):
    base=Path(state_dir)
    now=utc(now or datetime.now(timezone.utc))
    from robinhood_policy import read_policy
    status={"schema":1,"broker":"robinhood_crypto",
        "checked_at":now.isoformat(),"mode":"AUTHENTICATED_SIGNED_READ_ONLY",
        "v2_live_order_authority":False,"cutover_ready":False,
        "first_blocker":"SIGNED_BROKER_PREFLIGHT_UNAVAILABLE"}
    signed_client_initialized_here=client is None
    try:
        policy=read_policy(base)
        if client is None:
            from robinhood_crypto_gateway import RobinhoodCryptoAdapter
            client=RobinhoodCryptoAdapter.from_state(base)
        if signed_client_initialized_here and public_feed is None:
            # Real production signed-client run uses an independent live
            # public ticker. Mock unit tests may supply their own feed.
            from .public_crypto import fetch_ticker
            public_feed=fetch_ticker
        status=_probe(base,client,policy,now=now,public_feed=public_feed)
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
