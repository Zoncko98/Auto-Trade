"""Read-only Robinhood Crypto V2 signed order receipt translator.

This is the exact-order reconciliation side of migration, not a live writer.
Existing Robinhood client performs signed GETs. No keys or broker writes are
created here. Unknown provider states or incomplete fills NEVER imply a fill.
"""
from __future__ import annotations
from decimal import Decimal
from uuid import uuid5, NAMESPACE_URL
from typing import Mapping
from .contracts import BrokerExecution
from .models import OrderIntent, amount

class BrokerEvidenceUnavailable(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code=code

def client_id(intent_key: str, account_id: str) -> str:
    """Deterministic UUID for V2 client_order_id, stable after restart."""
    from .models import valid_id
    valid_id(intent_key); valid_id(account_id)
    return str(uuid5(NAMESPACE_URL, "auto-trader-v2|robinhood_crypto|"+account_id+"|"+intent_key))

def _money(value, field, positive=False):
    try:
        result=amount(value,field,not positive)
    except (ValueError,TypeError):
        raise BrokerEvidenceUnavailable("BROKER_"+field.upper()+"_INVALID") from None
    return result

def _match_order(rows, key, account_id):
    if not isinstance(rows, list):
        raise BrokerEvidenceUnavailable("BROKER_ORDER_HISTORY_UNAVAILABLE")
    identity=client_id(key,account_id)
    matches=[r for r in rows if isinstance(r,dict) and r.get("client_order_id")==identity]
    if len(matches)>1:
        raise BrokerEvidenceUnavailable("DUPLICATE_BROKER_ORDER_IDENTITY")
    if not matches:return None
    row=matches[0]
    broker_account=row.get("account_number")
    if broker_account is not None and broker_account!=account_id:
        raise BrokerEvidenceUnavailable("BROKER_ORDER_WRONG_ACCOUNT")
    return row

def normalize_order(key: str, account_id: str, payload: Mapping) -> BrokerExecution:
    """Trust only exact signed broker lookup input and explicitly present fields."""
    if not isinstance(payload,dict) or payload.get("client_order_id")!=client_id(key,account_id):
        raise BrokerEvidenceUnavailable("BROKER_CLIENT_ORDER_ID_UNVERIFIED")
    if payload.get("account_number") not in (None,account_id):
        raise BrokerEvidenceUnavailable("BROKER_ACCOUNT_MISMATCH")
    broker_id=payload.get("id")
    if not isinstance(broker_id,str) or not broker_id:
        raise BrokerEvidenceUnavailable("BROKER_ORDER_UUID_UNVERIFIED")
    raw=payload.get("state",payload.get("status"))
    if not isinstance(raw,str):
        raise BrokerEvidenceUnavailable("BROKER_ORDER_STATE_UNVERIFIED")
    state=raw.lower()
    if state not in {
        "open","pending","queued","confirmed","partially_filled",
        "filled","canceled","cancelled","rejected","failed","expired",
    }:
        raise BrokerEvidenceUnavailable("BROKER_ORDER_STATE_UNKNOWN")
    raw_filled=payload.get("filled_asset_quantity")
    if raw_filled is None:
        # A signed open order may omit its cumulative quantity. Final statuses
        # must carry authoritative fill evidence, even if it is zero.
        if state in ("filled","partially_filled","canceled","cancelled","rejected","failed","expired"):
            raise BrokerEvidenceUnavailable("BROKER_FILL_QUANTITY_MISSING")
        filled=Decimal("0")
    else:
        filled=_money(raw_filled,"filled_quantity")
    if state=="filled" and filled==0:
        raise BrokerEvidenceUnavailable("BROKER_FULL_FILL_QUANTITY_ZERO")
    if state=="partially_filled" and filled==0:
        raise BrokerEvidenceUnavailable("BROKER_PARTIAL_FILL_QUANTITY_ZERO")
    if filled:
        price=payload.get("average_price")
        if price is None:
            executions=payload.get("executions")
            if not isinstance(executions,list) or not executions:
                raise BrokerEvidenceUnavailable("BROKER_FILL_PRICE_MISSING")
            prices=[]
            for e in executions:
                if not isinstance(e,dict):
                    raise BrokerEvidenceUnavailable("BROKER_EXECUTION_INVALID")
                qty=_money(e.get("quantity"),"execution_quantity",True)
                px=_money(e.get("effective_price"),"execution_price",True)
                prices.append((qty,px))
            if sum((q for q,_ in prices),Decimal("0"))!=filled:
                raise BrokerEvidenceUnavailable("BROKER_EXECUTION_QTY_MISMATCH")
            price=sum((q*p for q,p in prices),Decimal("0"))/filled
        price=_money(price,"average_price",True)
        # Missing fees are not zero. Until the fee field can be verified,
        # no final economics or FILLED transition is claimed.
        fee=payload.get("fee_charged")
        if fee is None:raise BrokerEvidenceUnavailable("BROKER_FEES_UNVERIFIED")
        fees=_money(fee,"fees")
    else:
        price=Decimal("0");fees=Decimal("0")
        if payload.get("fee_charged") not in (None,"0",0,"0.0"):
            raise BrokerEvidenceUnavailable("BROKER_ZERO_FILL_FEE_CONFLICT")
    if state in ("filled",):
        normalized="FILLED"
    elif state=="partially_filled" or (filled>0 and state in ("open","pending","queued","confirmed")):
        normalized="PARTIALLY_FILLED"
    elif state in ("canceled","cancelled","expired"):
        normalized="CANCELED"
    elif state in ("rejected","failed"):
        normalized="REJECTED"
    else:
        normalized="BROKER_ACCEPTED"
    try:
        return BrokerExecution(key,normalized,broker_id,filled,price,fees)
    except (ValueError,TypeError):
        raise BrokerEvidenceUnavailable("BROKER_RECEIPT_INVALID") from None

class RobinhoodReadOnlyReceiptAdapter:
    provider_id="robinhood_crypto"
    def __init__(self, signed_client, account_id):
        if not isinstance(account_id,str) or not account_id:
            raise ValueError("Missing selected Robinhood account")
        self._client=signed_client
        self.account_id=account_id

    def find_order(self,key):
        # Only signed GET, no mutation. Authenticated full order history may
        # differ from an eventual lookup-by-UUID; ambiguous => fail closed.
        rows=self._client.orders(self.account_id)
        match=_match_order(rows,key,self.account_id)
        return normalize_order(key,self.account_id,match) if match else None

    def submit(self,*args,**kwargs):
        raise BrokerEvidenceUnavailable("V2_LIVE_ORDER_WRITER_NOT_CUT_OVER")
