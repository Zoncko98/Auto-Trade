"""V2 canonical LIVE order coordinator, fail-closed until a broker handoff.

Unlike PaperPipeline this class can accept a real broker adapter, but it needs
a fresh, account-specific single-writer handoff proof and a signed-executable
quote. Nothing creates or enables one by importing this module. The existing
V1 broker workers remain authoritative until the handoff is independently
proved and the operator has authorized that account.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from typing import Callable
from .contracts import TradingBroker,AIReviewer,BrokerExecution,inspect_paper_adapter
from .engine import PaperPipeline,PipelineResult,candidate_key
from .models import (
    AIReview,AIState,Account,Candidate,MarketSnapshot,
    OrderIntent,OrderState,OrderSide,RiskPolicy,RiskDecision,utc,valid_id
)
from .risk import evaluate_risk
from .store import EventStore,IntentConflict
from .simulation import SimulatedBroker
from .writer_ownership import account_writer_scope,WriterOwnershipError,ACCOUNT
from pathlib import Path

SIGNED_SOURCES={
    # Validated source provenance is distinct from actual cutover permission.
    # The dual source uses a signed broker top of book and an independently
    # timestamped external LAST; it is NOT a native broker venue timestamp.
    "robinhood_crypto":frozenset(("robinhood_signed","robinhood_dual_attested")),
    "schwab":frozenset(("schwab_signed",)),
    "webull":frozenset(("webull_signed",)),
}
class LiveMigrationRejected(RuntimeError):
    """Definitive refusal of a broker order before it is accepted."""

@dataclass(frozen=True)
class WriterHandoff:
    broker:str
    account_id:str
    generation:str
    checked_at:datetime
    expires_at:datetime
    operator_armed:bool
    v1_writer_stopped:bool
    local_orders_resolved:bool
    broker_open_orders_resolved:bool
    account_verified:bool
    settled_funding_verified:bool
    session_verified:bool
    def __post_init__(self):
        if self.broker not in SIGNED_SOURCES:
            raise ValueError("Invalid live broker identity")
        valid_id(self.account_id);valid_id(self.generation)
        object.__setattr__(self,"checked_at",utc(self.checked_at))
        object.__setattr__(self,"expires_at",utc(self.expires_at))
        if not self.checked_at<=self.expires_at<=self.checked_at+timedelta(seconds=120):
            raise ValueError("Cutover proof must be fresh and short-lived")
        if any(type(getattr(self,k)) is not bool for k in (
                "operator_armed","v1_writer_stopped","local_orders_resolved",
                "broker_open_orders_resolved","account_verified",
                "settled_funding_verified","session_verified")):
            raise ValueError("Invalid broker-cutover proof type")
    def verified(self,broker,account,now):
        now=utc(now)
        return (self.broker==broker and self.account_id==account and
            self.checked_at-timedelta(seconds=2)<=now<=self.expires_at and
            self.operator_armed and self.v1_writer_stopped and
            self.local_orders_resolved and self.broker_open_orders_resolved and
            self.account_verified and self.settled_funding_verified and
            self.session_verified)

class LivePipeline(PaperPipeline):
    """Uses shared V2 receipt state machine, never the simulated broker.

    A no-op or mock gate can test the state machine offline; a production
    coordinator must supply a real gate backed by broker proof and an
    exclusive supervisor lease. There is intentionally no default permit.
    """
    def __init__(self,broker:TradingBroker,store:EventStore,gate:Callable,
                 *,ownership_root,reviewer:AIReviewer|None=None):
        if (isinstance(broker,SimulatedBroker) or
                not isinstance(broker,TradingBroker) or
                not isinstance(store,EventStore) or not callable(gate)):
            raise TypeError("Real broker adapter, durable event store and handoff gate required")
        if broker.provider_id not in SIGNED_SOURCES:
            raise TypeError("Broker not eligible for V2 live migration")
        self.broker=broker
        self.store=store
        self.gate=gate
        self.reviewer=reviewer
        if not isinstance(ownership_root,(str,Path)):
            raise TypeError("Persistent account ownership root required")
        self.ownership_root=Path(ownership_root)
        # Schwab's broker account hash may include +/= that are disallowed in
        # canonical V2 journal IDs. V1 locks the raw hash. Use that same raw
        # source account ID for the EXCLUSIVE V1/V2 writer lock rather than
        # acquiring a second alias lock that V1 will not recognize.
        raw=getattr(broker,"writer_scope_account",None)
        if raw is not None and (not isinstance(raw,str) or
                               ACCOUNT.fullmatch(raw) is None or ".." in raw):
            raise TypeError("Unverified raw writer account identity")
        self.writer_scope_account=raw

    def _handoff(self,candidate,now,generation=None):
        try:
            proof=self.gate()
        except Exception:
            return None
        if (not isinstance(proof,WriterHandoff) or
                not proof.verified(self.broker.provider_id,candidate.account_id,now) or
                (generation is not None and proof.generation!=generation)):
            return None
        return proof

    def evaluate(self,candidate:Candidate,quote:MarketSnapshot,policy:RiskPolicy,
                 *,now:datetime|None=None,daily_realized_loss=Decimal("0"),
                 entries_today:int=0,exits_today:int=0)->PipelineResult:
        if not isinstance(candidate,Candidate) or not isinstance(quote,MarketSnapshot):
            raise TypeError("Canonical candidate and signed quote required")
        if not isinstance(policy,RiskPolicy):
            raise TypeError("Account-specific RiskPolicy required")
        explicit=now is not None
        now=utc(now or datetime.now(timezone.utc))
        key=candidate_key(candidate)
        prior=self.store.get(key)
        if prior is not None:
            # Existing intent is reconciled by its original key; a duplicate
            # signal never resubmits an uncertain POST.
            return self._result_existing(key)
        proof=self._handoff(candidate,now)
        if proof is None:
            return PipelineResult("BLOCKED","V1_TO_V2_SINGLE_WRITER_HANDOFF_UNVERIFIED",key)
        try:
            with account_writer_scope(self.ownership_root,self.broker.provider_id,
                                      self.writer_scope_account or candidate.account_id,
                                      owner="V2",generation=proof.generation):
                return self._evaluate_owned(candidate,quote,policy,now,explicit,
                           key,proof,daily_realized_loss,entries_today,exits_today)
        except WriterOwnershipError:
            return PipelineResult("BLOCKED","ACCOUNT_WRITER_OWNERSHIP_UNVERIFIED",key)

    def _evaluate_owned(self,candidate,quote,policy,now,explicit,key,proof,
                        daily_realized_loss,entries_today,exits_today):
        """Invoked while holding SAME exclusive lock as V1 broker POST."""
        expected_source=SIGNED_SOURCES[self.broker.provider_id]
        if quote.source not in expected_source:
            return PipelineResult("BLOCKED","EXECUTABLE_BROKER_QUOTE_UNVERIFIED",key)
        if self.store.pending(candidate.account_id):
            return PipelineResult("BLOCKED","ACCOUNT_RECONCILIATION_PENDING",key)
        try:
            account=inspect_paper_adapter(self.broker,candidate.account_id)
            # Multi-pair broker accounts must use the exact symbol's signed
            # minimum notional and quantity increment. The generic account
            # capability (typically the first pair) cannot authorize a
            # different pair's precision or order minimum.
            exact=getattr(self.broker,"account_for_symbol",None)
            if exact is not None:
                if not callable(exact):
                    raise ValueError("INVALID_SYMBOL_ACCOUNT_PROVIDER")
                account=exact(candidate.account_id,candidate.symbol)
                if (not isinstance(account,Account) or
                    account.broker!=self.broker.provider_id or
                    account.account_id!=candidate.account_id):
                    raise ValueError("SYMBOL_ACCOUNT_IDENTITY_UNVERIFIED")
        except Exception:
            return PipelineResult("BLOCKED","SIGNED_BROKER_ACCOUNT_UNAVAILABLE",key)
        risk=evaluate_risk(account,candidate,quote,policy,now=now,
             daily_realized_loss=daily_realized_loss,
             entries_today=entries_today,exits_today=exits_today)
        if risk.code!="PASS":
            self.store.review(key,candidate.account_id,risk.code,risk.reason)
            return PipelineResult("BLOCKED",risk.reason,key)
        # A validated protective SELL must not wait on an optional or
        # unavailable AI model. Deterministic risk/session/held limits apply.
        if candidate.side is OrderSide.BUY and policy.ai_mode!="OFF":
            try:
                ai=self.reviewer.review(candidate,quote) if self.reviewer else None
            except Exception:
                ai=None
            reviewed_now=now if explicit else utc(datetime.now(timezone.utc))
            valid=(isinstance(ai,AIReview) and ai.symbol==candidate.symbol
                   and ai.reviewed_at<=reviewed_now+timedelta(seconds=2)
                   and ai.expires_at>=reviewed_now)
            if valid and ai.state==AIState.VETO:
                self.store.review(key,candidate.account_id,"AI_VETO",ai.reason[:180])
                return PipelineResult("BLOCKED","AI_VETO",key)
            if policy.ai_mode=="REQUIRED" and (
                not valid or ai.state!=AIState.PASS):
                self.store.review(key,candidate.account_id,"AI_UNAVAILABLE",
                                  "Required validated review unavailable")
                return PipelineResult("BLOCKED","AI_UNAVAILABLE",key)
        intent=OrderIntent(key,candidate.account_id,candidate.strategy,
                           candidate.symbol,candidate.asset_class,candidate.side,
                           risk.quantity,risk.limit_price,now)
        try:
            record=self.store.prepare(intent,risk)
        except IntentConflict:
            return PipelineResult("BLOCKED","ACCOUNT_RECONCILIATION_PENDING",key)
        if record["state"]!=OrderState.INTENT_PERSISTED.value:
            return self._result_existing(key)
        # Renew both handoff proof and signed quote freshness after model/risk.
        if not explicit:
            now=utc(datetime.now(timezone.utc))
        if (self._handoff(candidate,now,proof.generation) is None
                or (now-quote.observed_at).total_seconds()< -2
                or (now-quote.observed_at).total_seconds()>policy.max_snapshot_age_seconds):
            # This is unambiguously PRE-POST: no broker write was attempted.
            # Abort the original intent durably so a lost handoff does not
            # permanently jam account reconciliation. If journaling fails,
            # leave INTENT_PERSISTED unresolved instead of guessing success.
            try:
                self.store.transition(key,OrderState.REJECTED,
                    evidence={"reason":"HANDOFF_OR_QUOTE_EXPIRED_PRE_POST",
                              "broker_post_attempted":False})
            except Exception:
                return PipelineResult("RECONCILIATION_REQUIRED",
                    "PRE_POST_INTENT_TERMINAL_WRITE_UNVERIFIED",key,
                    OrderState.INTENT_PERSISTED.value)
            return PipelineResult("BLOCKED","HANDOFF_OR_QUOTE_EXPIRED_BEFORE_ORDER",key,
                                  OrderState.REJECTED.value)
        self.store.transition(key,OrderState.SUBMITTING,
            evidence={"mode":"LIVE_V2_SINGLE_WRITER",
                      "broker":self.broker.provider_id,
                      "handoff_generation":proof.generation})
        try:
            receipt=self.broker.submit(intent)
        except LiveMigrationRejected:
            self.store.transition(key,OrderState.REJECTED,
                     evidence={"reason":"BROKER_DEFINITIVE_REJECTION"})
            return PipelineResult("REJECTED","BROKER_DEFINITIVE_REJECTION",key,
                                  OrderState.REJECTED.value)
        except Exception:
            self.store.transition(key,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
                evidence={"reason":"UNCERTAIN_LIVE_BROKER_WRITE"})
            return PipelineResult("RECONCILIATION_REQUIRED",
                "Original broker POST outcome unknown; do not retry",key,
                OrderState.UNKNOWN_REQUIRES_RECONCILIATION.value)
        result=self._accept(key,receipt)
        if result.code=="FILLED":
            return PipelineResult(result.code,"Broker fill evidence reconciled",
                                  result.intent_key,result.order_state)
        return result
