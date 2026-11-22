"""Robinhood Crypto V2 live adapter over existing signed official API client.

The adapter itself cannot start a trading worker. The LivePipeline requires an
independently verified and fresh single-writer handoff. No public Coinbase
quote, paper mark or V1 local journal row can authorize a V2 broker write.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN,ROUND_UP
from .models import (
    Account,AssetClass,Capability,AuthState,MarketSnapshot,OrderIntent,
    OrderSide,amount,utc
)
from .contracts import BrokerExecution
from .live_pipeline import LiveMigrationRejected
from .robinhood_signed_receipts import (
    RobinhoodReadOnlyReceiptAdapter,client_id,
    normalize_order,BrokerEvidenceUnavailable,signed_holding_quantity,
    signed_pair_limits
)
from .market_sources import robinhood_market_quote,MarketSourceError
from .robinhood_dual_quote import attest_quote,DualQuoteUnavailable

class RobinhoodLiveAdapter:
    provider_id="robinhood_crypto"

    def __init__(self,signed_client,account_id,risk_policy,symbol,*,clock=None,
                 verified_managed_positions=None,public_trade_feed=None):
        from robinhood_crypto_gateway import PAIR,ACCOUNT
        if not isinstance(account_id,str) or not ACCOUNT.fullmatch(account_id):
            raise ValueError("Verified selected Robinhood account required")
        if not isinstance(symbol,str) or not PAIR.fullmatch(symbol):
            raise ValueError("Valid Robinhood USD pair required")
        if not isinstance(risk_policy,dict) or (
            risk_policy.get("enabled") is not True or
            risk_policy.get("account")!=account_id):
            raise ValueError("Explicit per-account Robinhood operator permission required")
        self.client=signed_client
        self.account_id=account_id
        self.policy=risk_policy
        self.symbol=symbol
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.receipts=RobinhoodReadOnlyReceiptAdapter(signed_client,account_id)
        # Optional independently venue-timed feed for Robinhood v2 bid/ask
        # responses that omit exchange time and LAST. Not execution authority.
        self.public_trade_feed=public_trade_feed
        # This is managed BOT inventory verified from historical signed fills
        # and the canonical V2 fill journal, never all externally-held assets.
        # Default empty means sells are blocked until inventory provenance
        # can be verified. All broker holdings still count toward exposure.
        self.managed_positions=dict(verified_managed_positions or {})

    def _selected(self):
        rows=self.client.list_accounts()
        if not isinstance(rows,list):
            raise BrokerEvidenceUnavailable("SIGNED_ACCOUNTS_UNAVAILABLE")
        selected=[x for x in rows if isinstance(x,dict) and
                  x.get("account_number")==self.account_id]
        if len(selected)!=1:
            raise BrokerEvidenceUnavailable("ACCOUNT_SELECTION_AMBIGUOUS")
        account=selected[0]
        if (account.get("status")!="active" or
                account.get("is_api_tradable") is not True or
                account.get("buying_power_currency")!="USD"):
            raise BrokerEvidenceUnavailable("SIGNED_ACCOUNT_CANNOT_TRADE")
        return account

    def _pair(self):
        pairs=self.client.trading_pairs()
        if not isinstance(pairs,list):
            raise BrokerEvidenceUnavailable("SIGNED_TRADING_PAIRS_UNAVAILABLE")
        selected=[p for p in pairs if isinstance(p,dict) and p.get("symbol")==self.symbol]
        if len(selected)!=1 or selected[0].get("is_api_tradable") is not True:
            raise BrokerEvidenceUnavailable("SIGNED_PAIR_NOT_TRADABLE")
        return signed_pair_limits(selected[0])

    def _validated_quote(self,symbol,now):
        # Independently timed last first, then signed broker bid/ask:
        # the last read is never substituted for executable broker prices.
        external=None
        if self.public_trade_feed is not None:
            try:
                external=self.public_trade_feed(symbol.replace("-",""))
            except Exception:
                raise BrokerEvidenceUnavailable("INDEPENDENT_VENUE_TRADE_UNAVAILABLE") from None
        started=datetime.now(timezone.utc)
        try: raw=self.client.quote(symbol)
        except Exception:
            raise BrokerEvidenceUnavailable("SIGNED_BROKER_BID_ASK_READ_FAILED") from None
        completed=datetime.now(timezone.utc)
        try:
            reading=robinhood_market_quote(raw,symbol,now=completed)
            # Native broker-LAST readings require the same strict book
            # spread and 20-second signed-venue freshness as dual quotes.
            # A successful GET with a stale or excessively wide book cannot
            # become an executable order source.
            signed_age=(completed-reading.observed_at).total_seconds()
            if (reading.last is not None and reading.source_tradable and
                -2<=signed_age<=20 and reading.bid>0 and reading.ask>=reading.bid and
                (reading.ask-reading.bid)/reading.ask<=Decimal("0.015")):
                return MarketSnapshot(symbol,AssetClass.CRYPTO,
                    "robinhood_signed",reading.observed_at,reading.received_at,
                    reading.bid,reading.ask,reading.last,True)
        except (MarketSourceError,ValueError,TypeError):
            pass
        if external is None:
            raise BrokerEvidenceUnavailable("INDEPENDENT_VENUE_TRADE_REQUIRED")
        try:
            proof=attest_quote(raw,external,symbol,
                 request_started_at=started,request_completed_at=completed,
                 examined_at=datetime.now(timezone.utc))
        except (DualQuoteUnavailable,ValueError,TypeError,OverflowError):
            raise BrokerEvidenceUnavailable("BROKER_PUBLIC_DUAL_QUOTE_UNVERIFIED") from None
        # observed_at is the Coinbase trade time, NOT a broker venue
        # timestamp. Broker BID/ASK are separately signed and time-bounded.
        return MarketSnapshot(symbol,AssetClass.CRYPTO,
            "robinhood_dual_attested",proof.independent_trade_at,
            proof.examined_at,proof.signed_bid,proof.signed_ask,
            proof.external_last,True)

    def quote(self,now=None):
        now=utc(now or self.clock())
        self._selected()
        self._pair()
        return self._validated_quote(self.symbol,now)

    def _signed_holding_ask(self,symbol):
        """Conservative exposure-only valuation with original signed prices.

        Robinhood V2 best-price top-of-book normally has no venue timestamp or
        last trade. A timestamp requirement here previously made ANY existing
        external holding unmarkable, even when the broker signed a valid book.
        GET timing and a fresh, independent venue LAST are mandatory. For a
        narrowly crossed aggregate book, choose the HIGHER signed price for
        risk exposure; do not invert, normalize or approve either price as
        executable. An order still needs the separate STRICT quote gate.
        """
        from .market_sources import _sourced_time
        expected={"BTC-USD":"BTCUSD","ETH-USD":"ETHUSD"}.get(symbol)
        external=None
        if expected is not None and callable(self.public_trade_feed):
            try:external=self.public_trade_feed(expected)
            except Exception:pass
        started=datetime.now(timezone.utc)
        try:
            payload=self.client.quote(symbol)
        except Exception:
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_QUOTE_UNAVAILABLE") from None
        completed=datetime.now(timezone.utc)
        if not 0<=(completed-started).total_seconds()<=3:
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_QUOTE_TIMEOUT")
        # Original fully timestamped broker-native quote is sufficient to
        # mark exposure for *any* selected holding, including a coin without
        # a Coinbase ticker. This is the original signed source and remains
        # strict about provider venue time and NONCROSSED bid/ask.
        try:
            native=robinhood_market_quote(payload,symbol,now=completed)
            native_age=(completed-native.observed_at).total_seconds()
            if (native.source_tradable and -2<=native_age<=20 and
                native.bid>0 and native.ask>=native.bid and
                (native.ask-native.bid)/native.ask<=Decimal("0.015")):
                return native.ask
        except (MarketSourceError,ValueError,TypeError):
            pass
        # The newer V2 three-field response normally has no broker venue
        # timestamp; use conservative signed bid/ask plus independently
        # timed public LAST for exposure ONLY. Unsupported, unmarked coins
        # fail closed instead of disappearing from portfolio risk.
        if expected is None or external is None:
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_EXTERNAL_CHECK_UNAVAILABLE")
        if (not isinstance(payload,dict) or
            not isinstance(payload.get("results"),list)):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_SCHEMA_UNVERIFIED")
        matches=[row for row in payload["results"] if isinstance(row,dict)
                 and row.get("symbol")==symbol]
        if len(matches)!=1:
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_SYMBOL_UNVERIFIED")
        row=matches[0]
        try:
            bid=signed_holding_quantity(row.get("bid"))
            ask=signed_holding_quantity(row.get("ask"))
            if bid<=0 or ask<=0:raise ValueError
            signed_at=next((row[k] for k in
                ("quote_timestamp","timestamp","updated_at") if k in row),None)
            if signed_at is not None:
                _sourced_time(signed_at,completed,ttl=20)
        except Exception:
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_PRICE_UNVERIFIED") from None
        high=max(bid,ask);low=min(bid,ask)
        if (high-low)/high>Decimal("0.015"):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_MARK_SPREAD_UNVERIFIED")
        if (not isinstance(external,MarketSnapshot) or
            external.symbol!=expected or
            external.source!="coinbase_public_paper" or
            external.asset_class is not AssetClass.CRYPTO or
            external.market_open is not True or external.last is None):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_EXTERNAL_LAST_UNVERIFIED")
        if (not -2<=(completed-external.observed_at).total_seconds()<=20 or
            not -2<=(completed-external.received_at).total_seconds()<=20):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_EXTERNAL_LAST_STALE")
        if abs(high-external.last)/external.last>Decimal("0.015"):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDING_BROKER_PUBLIC_PRICE_DIFFERENCE")
        # HIGHER of the TWO signed broker prices increases counted exposure.
        # This cannot be used as a trade quote and never creates sell rights.
        return high

    def account(self,account_id):
        if account_id!=self.account_id:
            raise BrokerEvidenceUnavailable("SIGNED_ACCOUNT_MISMATCH")
        selected=self._selected()
        self._pair()
        buying=amount(selected.get("buying_power"),"broker USD buying power")
        holdings=self.client.positions(account_id)
        if not isinstance(holdings,list):
            raise BrokerEvidenceUnavailable("SIGNED_HOLDINGS_UNAVAILABLE")
        signed_positions={};market_exposure=Decimal("0")
        for holding in holdings:
            if not isinstance(holding,dict):
                raise BrokerEvidenceUnavailable("SIGNED_HOLDING_INVALID")
            asset=holding.get("asset_code")
            if not isinstance(asset,str) or not asset or len(asset)>12:
                raise BrokerEvidenceUnavailable("SIGNED_ASSET_ID_INVALID")
            symbol=asset+"-USD"
            if symbol in signed_positions:
                raise BrokerEvidenceUnavailable("DUPLICATE_SIGNED_HOLDING")
            try:qty=signed_holding_quantity(holding.get("total_quantity"))
            except (ValueError,TypeError):
                raise BrokerEvidenceUnavailable("SIGNED_POSITION_QUANTITY_INVALID") from None
            if qty==0:continue
            # All held assets count, including non-Coinbase-supported coins:
            # fresh signed bid/ask suffices for gross exposure only.
            try:
                ask=self._signed_holding_ask(symbol)
            except BrokerEvidenceUnavailable as exc:
                # Allowlisted source-specific reason survives into private
                # preflight status; never include signed broker response text.
                raise BrokerEvidenceUnavailable(exc.code) from None
            except (ValueError,TypeError):
                raise BrokerEvidenceUnavailable("SIGNED_POSITION_MARK_UNVERIFIED") from None
            signed_positions[symbol]=qty
            market_exposure+=qty*ask
        managed={}
        for symbol,raw in self.managed_positions.items():
            if not isinstance(symbol,str):
                raise BrokerEvidenceUnavailable("MANAGED_POSITION_IDENTITY_UNVERIFIED")
            try:qty=amount(raw,"verified bot position",False)
            except (ValueError,TypeError):
                raise BrokerEvidenceUnavailable("MANAGED_POSITION_QTY_UNVERIFIED") from None
            if signed_positions.get(symbol,Decimal("0"))<qty:
                raise BrokerEvidenceUnavailable("BROKER_HOLDINGS_BELOW_VERIFIED_BOT_INVENTORY")
            managed[symbol]=qty
        # This cash field represents VERIFIED broker USD *buying power* for
        # spot crypto risk sizing; the UI must NOT label it settled cash.
        # V2 canonical money uses cents/12 digits at most. Round invested
        # exposure UP and equity DOWN, so tiny external positions cannot be
        # dropped or increase an unsupported account's deployable budget.
        rounded_exposure=market_exposure.quantize(Decimal("0.01"),rounding=ROUND_UP)
        conservative_equity=buying+market_exposure.quantize(
            Decimal("0.01"),rounding=ROUND_DOWN)
        pair=self._pair()
        return Account(account_id,self.provider_id,
            Capability(frozenset({AssetClass.CRYPTO}),
                       fractional=True,min_notional=pair["min_order_amount"],
                       quantity_increment=pair["asset_increment"]),
            buying,conservative_equity,managed,AuthState.CONNECTED,True,
            rounded_exposure)

    def find_order(self,key):
        return self.receipts.find_order(key)

    def submit(self,intent:OrderIntent)->BrokerExecution:
        from robinhood_crypto_execution import (
            RobinhoodWriteRejected,RobinhoodWriteUncertain
        )
        if (not isinstance(intent,OrderIntent) or intent.account_id!=self.account_id
                or intent.symbol!=self.symbol or
                intent.asset_class is not AssetClass.CRYPTO):
            raise BrokerEvidenceUnavailable("LIVE_INTENT_IDENTITY_UNVERIFIED")
        pair=self._pair()
        if (intent.quantity%pair["asset_increment"]!=0 or
                intent.quantity>pair["max_order_size"] or
                intent.quantity*intent.limit_price<pair["min_order_amount"]):
            raise BrokerEvidenceUnavailable("BROKER_MINIMUM_OR_INCREMENT_NOT_MET")
        cap=amount(self.policy.get("max_order_usd"),"account max order",False)
        if intent.quantity*intent.limit_price>cap or cap>Decimal("25"):
            raise BrokerEvidenceUnavailable("PER_ACCOUNT_ORDER_CAP_EXCEEDED")
        current=self.quote()
        if intent.side is OrderSide.BUY:
            if intent.limit_price<current.ask or (
                    intent.limit_price/current.ask-1)>Decimal("0.005"):
                raise BrokerEvidenceUnavailable("LIVE_BUY_LIMIT_OUTSIDE_CURRENT_BROKER_SPREAD")
        else:
            if intent.limit_price>current.bid or (
                    1-intent.limit_price/current.bid)>Decimal("0.005"):
                raise BrokerEvidenceUnavailable("LIVE_SELL_LIMIT_OUTSIDE_CURRENT_BROKER_SPREAD")
        # LivePipeline must have persisted the original intent before reaching
        # this signed POST, and will treat any uncertain result as locked.
        uid=client_id(intent.key,intent.account_id)
        try:
            result=self.client.submit_order(intent.account_id,{
                "type":"limit","side":intent.side.value.lower(),
                "symbol":intent.symbol,"asset_quantity":str(intent.quantity),
                "limit_price":str(intent.limit_price),"client_order_id":uid,
                "risk_approved":True,"operator_approved":True,
            })
        except RobinhoodWriteRejected as error:
            raise LiveMigrationRejected("Definitive broker rejection") from error
        # Never fabricate a successful confirmation from a 200 response that
        # lacks a broker UUID; reconciliation must look up the original key.
        if not isinstance(result,dict) or not isinstance(result.get("id"),str):
            raise BrokerEvidenceUnavailable("SIGNED_ORDER_ACK_UNVERIFIED")
        ack={"client_order_id":uid,"account_number":self.account_id,
             "id":result["id"],"state":"open","filled_asset_quantity":"0"}
        # Any immediate fill in the POST response remains advisory; GET
        # reconciliation validates the actual cumulative fill and fees.
        return normalize_order(intent.key,intent.account_id,ack)
