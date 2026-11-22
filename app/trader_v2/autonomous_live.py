"""Shared V2 autonomous live broker scan and execution coordinator.

This is the replacement for three independent entry-only brokers, but accepts
only an account-matched short-lived WriterHandoff, EXACT V2 ownership generation,
signed current Account, a conservative account risk policy, validated complete
closed candles and genuine signed broker order quotes. Existing unresolved
intents are reconciled by their ORIGINAL ID instead of re-posted.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import json,sqlite3

from .models import (AssetClass,OrderSide,OrderState,
    Account,Candidate,Candle,RiskPolicy,MarketSnapshot,utc)
from .strategies import StockController,CryptoController
from .store import EventStore
from .live_pipeline import LivePipeline,WriterHandoff
from .writer_ownership import inspect_ownership,WriterOwnershipError
from .contracts import TradingBroker

class LiveScanUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def accepted_bars(candles,symbol,asset_class,now):
    required=9 if asset_class is AssetClass.CRYPTO else 6
    if not isinstance(candles,list) or len(candles)<required or len(candles)>240:
        raise LiveScanUnavailable("V2_COMPLETED_MARKET_BARS_UNAVAILABLE")
    if asset_class not in (AssetClass.CRYPTO,AssetClass.STOCK):
        raise LiveScanUnavailable("V2_ASSET_CLASS_UNSUPPORTED")
    period=60 if asset_class is AssetClass.CRYPTO else 300
    selected=candles[-9:] if asset_class is AssetClass.CRYPTO else candles[-6:]
    previous=None
    for bar in selected:
        if not isinstance(bar,Candle) or not bar.closed or bar.symbol!=symbol:
            raise LiveScanUnavailable("V2_COMPLETED_BAR_IDENTITY_UNVERIFIED")
        at=utc(bar.observed_at)
        if previous is not None and (at-previous).total_seconds()!=period:
            raise LiveScanUnavailable("V2_COMPLETED_BAR_GAP_OR_DUPLICATE")
        previous=at
    age=(now-selected[-1].observed_at).total_seconds()
    maxage=90 if asset_class is AssetClass.CRYPTO else 900
    if not 0<=age<=maxage:
        raise LiveScanUnavailable("V2_COMPLETED_BAR_STALE_OR_FUTURE")
    return candles

def canonical_counts(store,account,now):
    if not isinstance(store,EventStore):
        raise TypeError("Durable journal is required")
    with store._connect() as db:
        rows=db.execute("SELECT document,created_at FROM intents WHERE account_id=?",
                        (account,)).fetchall()
    entries=exits=0
    for document,at in rows:
        try:
            payload=json.loads(document)
            when=utc(datetime.fromisoformat(at))
            if when.date()!=now.date():continue
            if payload["side"]=="BUY":entries+=1
            elif payload["side"]=="SELL":exits+=1
            else:raise ValueError
        except (ValueError,TypeError,KeyError):
            raise LiveScanUnavailable("V2_DAILY_ORDER_COUNT_UNVERIFIED") from None
    return entries,exits

class AutonomousLiveScan:
    def __init__(self,broker:TradingBroker,account_id:str,*,state_dir,
                 symbols,asset_class:AssetClass,candle_feed,quote_feed,
                 gate,reviewer=None,clock=None,policy_provider=None,
                 realized_loss_provider=None,strategy_parity_provider=None):
        if not isinstance(broker,TradingBroker) or broker.provider_id not in (
                "schwab","webull","robinhood_crypto"):
            raise TypeError("Canonical signed live broker required")
        if not isinstance(account_id,str) or not account_id:
            raise ValueError("Selected account required")
        if not isinstance(asset_class,AssetClass) or not isinstance(symbols,(list,tuple)):
            raise ValueError("One canonical asset class and configured symbols required")
        if not 1<=len(symbols)<=32 or not all(isinstance(s,str) and s for s in symbols):
            raise ValueError("Bounded, explicit symbol set required")
        if not callable(candle_feed) or not callable(quote_feed) or not callable(gate):
            raise TypeError("Signed real price, market bars and account grant required")
        self.broker=broker;self.account_id=account_id
        self.state=Path(state_dir)
        self.symbols=tuple(dict.fromkeys(symbols))
        self.asset_class=asset_class
        self.candle_feed=candle_feed
        self.quote_feed=quote_feed
        self.gate=gate
        self.reviewer=reviewer
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.policy_provider=policy_provider
        # Mandatory account daily loss from signed broker and V1+V2 ledger.
        self.realized_loss_provider=realized_loss_provider
        # Full V1→V2 per-account exit/cooldown and adopted inventory checks.
        # A valid WriterHandoff by itself is NOT strategy equivalence.
        self.strategy_parity_provider=strategy_parity_provider
        self.controller=(
            StockController() if asset_class is AssetClass.STOCK else CryptoController())
        self.writer_scope=getattr(broker,"writer_scope_account",None) or account_id

    def _authority(self,now):
        try:
            proof=self.gate()
            if not isinstance(proof,WriterHandoff) or not proof.verified(
                    self.broker.provider_id,self.account_id,now):
                return None
            saved=inspect_ownership(self.state,self.broker.provider_id,self.writer_scope)
            if saved["owner"]!="V2" or saved["generation"]!=proof.generation:
                return None
            return proof
        except (WriterOwnershipError,ValueError,TypeError,OSError):
            return None

    def _status(self,state,reason,*,checked=0,signals=0,order_key=None):
        return {"broker":self.broker.provider_id,
            "checked_at":utc(self.clock()).isoformat(),
            "mode":"V2_LIVE_EXECUTION_GATED",
            "state":state,"reason":reason,
            "symbols_scanned":checked,"candidate_count":signals,
            "last_order_key":order_key,
            "live_order_authority_claimed":False,
            "broker_order_filled":state=="FILLED"}

    def run_once(self):
        now=utc(self.clock())
        proof=self._authority(now)
        if proof is None:
            return self._status("V2_OWNER_PROOF_UNAVAILABLE",
                                "V1 account owner or fresh signed broker handoff not verified")
        if not callable(self.strategy_parity_provider):
            return self._status("V2_STRATEGY_PARITY_UNVERIFIED",
                "Existing V1 exit, cooldown and managed inventory parity not certified")
        try:
            if self.strategy_parity_provider() is not True:
                raise ValueError
        except Exception:
            return self._status("V2_STRATEGY_PARITY_UNVERIFIED",
                "Existing V1 exit, cooldown and managed inventory parity not certified")
        # Must not create a V2 order journal before the exact V1-to-V2
        # transfer has already happened for this same physical account.
        try:
            store=EventStore(self.state/"v2"/"events.sqlite3")
            pipeline=LivePipeline(self.broker,store,self.gate,
                                  ownership_root=self.state,reviewer=self.reviewer)
            # Recovery always precedes another candidate and never posts.
            pending=store.pending(self.account_id)
            if pending:
                for row in pending[:6]:
                    pipeline.reconcile(row["key"])
                still=store.pending(self.account_id)
                if still:
                    return self._status("V2_ORIGINAL_ORDER_UNRESOLVED",
                        "Signed broker receipt must settle before another order")
        except Exception:
            return self._status("V2_RECONCILIATION_UNAVAILABLE",
                "V2 original broker order journal cannot be reconciled")
        try:
            account=self.broker.account(self.account_id)
            if (not isinstance(account,Account) or
                account.account_id!=self.account_id or
                account.broker!=self.broker.provider_id or
                not account.trading_enabled):
                raise ValueError
        except Exception:
            return self._status("V2_ACCOUNT_UNAVAILABLE",
                "Current signed account, holdings, permissions or funds unavailable")
        try:
            if self.policy_provider is None:
                from .conservative_risk_map import mapping
                derived=mapping(self.state,self.broker.provider_id,account,
                                signed_account_verified=True)
                policy=derived.get("policy")
            else:
                policy=self.policy_provider(account)
            if not isinstance(policy,RiskPolicy):
                raise ValueError
            # Required AI must be available for any new long entry.
            if policy.ai_mode!="REQUIRED":
                raise ValueError
            if not callable(self.realized_loss_provider):
                raise ValueError
            loss=self.realized_loss_provider(account)
            if isinstance(loss,bool) or not isinstance(loss,Decimal) or not loss.is_finite():
                raise ValueError
            loss=max(Decimal("0"),loss)
            entries,exits=canonical_counts(store,self.account_id,now)
        except Exception:
            return self._status("V2_RISK_POLICY_UNVERIFIED",
                "Signed account risk or validated AI entry configuration unavailable")
        checked=0;eligible=0;first_error=None;prioritized=[]
        for symbol in self.symbols:
            checked+=1
            try:
                candles=accepted_bars(self.candle_feed(symbol),symbol,self.asset_class,now)
                candidate=self.controller.candidate(self.account_id,candles)
                if candidate is None:continue
                held=account.positions.get(symbol,Decimal("0"))
                if candidate.side is OrderSide.SELL:
                    if held<=0:continue
                    prioritized.insert(0,candidate)
                elif candidate.side is OrderSide.BUY:
                    if held>0:continue
                    prioritized.append(candidate)
                eligible+=1
            except (LiveScanUnavailable,ValueError,TypeError,KeyError) as exc:
                if first_error is None:first_error=getattr(exc,"code","V2_CANDLES_UNAVAILABLE")
                continue
        if not prioritized:
            return self._status("NO_VALIDATED_V2_SIGNAL",first_error or "No eligible closed-bar crossover",
                                checked=checked,signals=0)
        for candidate in prioritized:
            try:
                if candidate.side is OrderSide.BUY and self.reviewer is None:
                    return self._status("V2_RISK_POLICY_UNVERIFIED",
                        "Required validated model not available for an entry",
                        checked=checked,signals=eligible)
                quote=self.quote_feed(candidate.symbol)
                if (not isinstance(quote,MarketSnapshot) or
                    quote.symbol!=candidate.symbol or
                    quote.asset_class!=candidate.asset_class or not quote.market_open):
                    raise LiveScanUnavailable("SIGNED_EXECUTABLE_QUOTE_UNVERIFIED")
                result=pipeline.evaluate(candidate,quote,policy,
                    daily_realized_loss=loss,
                    entries_today=entries,exits_today=exits)
                return self._status(result.code,result.reason,
                    checked=checked,signals=eligible,order_key=result.intent_key)
            except Exception:
                # Broker/transport exceptions may include signed headers.
                # Report a bounded code, never exception text or secrets.
                return self._status("V2_NO_VALID_MARKET_SOURCE",
                    "Current signed executable broker quote or session not verified",
                    checked=checked,signals=eligible)
        return self._status("NO_ELIGIBLE_V2_ORDER",
            "All order entry/exit rules remain enforced",
            checked=checked,signals=eligible)
