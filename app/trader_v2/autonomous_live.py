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
from .account_exit_rules import (
    ManagedExitLot, ExitPolicy, exit_trigger, ExitParityUnavailable,
)
from .v1_order_inheritance import InheritedOrderLimits

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
                 realized_loss_provider=None,strategy_parity_provider=None,
                 exit_evidence_provider=None,exit_policy_provider=None,
                 v1_activity_provider=None):
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
        # Exit metadata must come from signed reconciled V1/V2 broker lots,
        # NEVER the whole account position list or estimated entry fills.
        self.exit_evidence_provider=exit_evidence_provider
        self.exit_policy_provider=exit_policy_provider
        # Signed V1 order counts, settlement and symbol-specific cooldown
        # must be inherited at the exact V1->V2 writer handoff.
        self.v1_activity_provider=v1_activity_provider
        self.controller=(
            StockController(include_continuation=True)
            if asset_class is AssetClass.STOCK else CryptoController())
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
            # Entry AI policy is evaluated after signal classification:
            # protective SELLs must not be prevented by an entry-only
            # model-policy setting. All account/funding/loss checks remain.
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
        try:
            if not callable(self.v1_activity_provider):
                raise ValueError("Legacy V1 activity provider required")
            inherited=self.v1_activity_provider(account,now)
            if (not isinstance(inherited,InheritedOrderLimits) or
                inherited.broker!=self.broker.provider_id or
                inherited.account!=self.writer_scope or
                inherited.signed_broker_history_fresh is not True or
                inherited.local_journal_terminal is not True):
                raise ValueError("Legacy signed V1 activity unavailable")
            entries+=inherited.entries_today
            exits+=inherited.exits_today
            # Schwab V1 additionally limits ALL order actions in a day.
            # Neither the shared V2 entry counter nor the exit counter
            # alone represents this separate saved user safety ceiling.
            if self.broker.provider_id=="schwab":
                if inherited.max_daily_total_orders is None:
                    raise ValueError("Schwab all-order cap not verified")
                if entries+exits>=inherited.max_daily_total_orders:
                    return self._status("V1_DAILY_TOTAL_ORDER_LIMIT",
                        "Schwab V1 total daily order cap already reached")
        except Exception:
            return self._status("V2_V1_ACTIVITY_UNVERIFIED",
                "Signed V1 trade counts, settlement and symbol cooldowns required")
        checked=0;eligible=0;first_error=None;prioritized=[]
        verified_exit_quotes={}
        # Every bot-managed holding must first be checked for V1-compatible
        # stop/profit/held-time protection BEFORE evaluating any fresh buys.
        # Missing cost basis, signed availability or quote provenance blocks
        # new entries as well as exits, rather than silently skipping a hold.
        managed=[sym for sym,qty in sorted(account.positions.items()) if qty>0]
        if managed and (not callable(self.exit_evidence_provider) or
                        not callable(self.exit_policy_provider)):
            return self._status("V2_EXIT_EVIDENCE_UNVERIFIED",
                "Broker-confirmed managed lot and original V1 exit policy required")
        for symbol in managed:
            try:
                reading=self.quote_feed(symbol)
                if not isinstance(reading,MarketSnapshot):
                    raise ExitParityUnavailable("SIGNED_EXIT_QUOTE_MISSING")
                evidence=self.exit_evidence_provider(symbol,account)
                exit_policy=self.exit_policy_provider(account)
                if not isinstance(evidence,ManagedExitLot) or not isinstance(exit_policy,ExitPolicy):
                    raise ExitParityUnavailable("V2_MANAGED_EXIT_PROVIDERS_UNVERIFIED")
                if (evidence.quantity!=account.positions[symbol] or
                    evidence.symbol!=symbol):
                    raise ExitParityUnavailable("V2_MANAGED_EXIT_QUANTITY_MISMATCH")
                technical=False
                try:
                    recent=accepted_bars(self.candle_feed(symbol),symbol,self.asset_class,now)
                    signal=self.controller.candidate(self.account_id,recent)
                    technical=bool(signal is not None and signal.side is OrderSide.SELL)
                except (LiveScanUnavailable,TypeError,ValueError):
                    if self.broker.provider_id=="schwab":
                        raise ExitParityUnavailable("V2_SCHWAB_HELD_CANDLES_UNVERIFIED")
                mode=exit_trigger(self.broker.provider_id,evidence,reading,
                    exit_policy,now=now,technical_reversal=technical)
                verified_exit_quotes[symbol]=reading
                if mode!="HOLD":
                    eligible+=1
                    prioritized.append(Candidate(
                        strategy="v1_exit_protection",version="compat-1",
                        account_id=self.account_id,symbol=symbol,
                        asset_class=self.asset_class,side=OrderSide.SELL,
                        signal_at=reading.observed_at,
                        evidence={"reason":mode,
                                  "broker_exit_rules":"SIGNED_BOT_LOT_AND_BID",
                                  "asset":self.asset_class.value}))
            except Exception:
                return self._status("V2_EXIT_EVIDENCE_UNVERIFIED",
                    "Held-position exit rules or signed broker bid not verified",
                    checked=checked,signals=eligible)
        # Protect risk-reducing exits before all new-entry candidates.
        prioritized.sort(key=lambda x:{
            "STOP_LOSS":0,"TAKE_PROFIT":1,"TRAILING_PROFIT":2,
            "PROFIT_REVERSAL":3,"V1_SCHWAB_BEARISH_CROSS":4
        }.get(x.evidence.get("reason"),9))
        for symbol in self.symbols:
            checked+=1
            try:
                candles=accepted_bars(self.candle_feed(symbol),symbol,self.asset_class,now)
                candidate=self.controller.candidate(self.account_id,candles)
                if candidate is None:continue
                held=account.positions.get(symbol,Decimal("0"))
                if candidate.side is OrderSide.SELL:
                    # A generic down-cross never overrides the broker's
                    # verified cost/hold/stop/peak exit policy above.
                    continue
                elif candidate.side is OrderSide.BUY:
                    if (held>0 or inherited.all_buys_blocked or
                        symbol in inherited.reentry_blocked_symbols):
                        continue
                    prioritized.append(candidate)
                eligible+=1
            except (LiveScanUnavailable,ValueError,TypeError,KeyError) as exc:
                if first_error is None:first_error=getattr(exc,"code","V2_CANDLES_UNAVAILABLE")
                continue
        if not prioritized:
            blocker=("V1_BUY_SETTLEMENT_COOLDOWN_ACTIVE"
                     if inherited.all_buys_blocked else
                     "No eligible closed-bar crossover or entry cooldown")
            return self._status("NO_VALIDATED_V2_SIGNAL",first_error or blocker,
                                checked=checked,signals=0)
        for candidate in prioritized:
            try:
                if candidate.side is OrderSide.BUY and (
                        policy.ai_mode!="REQUIRED" or self.reviewer is None):
                    return self._status("V2_RISK_POLICY_UNVERIFIED",
                        "Required validated model or entry AI policy not available",
                        checked=checked,signals=eligible)
                quote=verified_exit_quotes.get(candidate.symbol)
                if quote is None:quote=self.quote_feed(candidate.symbol)
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
