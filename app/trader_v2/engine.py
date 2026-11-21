"""Shared V2 strategy → optional AI → risk → persistent intent → paper broker.

This module cannot import real brokerage clients and has NO live-order mode.
An uncertain submit is never repeated; only broker lookup may reconcile it.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import hashlib
from .contracts import TradingBroker,AIReviewer,BrokerExecution,inspect_paper_adapter
from .models import (AIReview,AIState,Account,Candidate,MarketSnapshot,
                     OrderIntent,OrderSide,OrderState,RiskPolicy,utc)
from .risk import evaluate_risk
from .simulation import SimulatedBroker,SimulationRejected
from .receipt_validation import receipt_failure
from .store import EventStore

@dataclass(frozen=True)
class PipelineResult:
    code:str
    reason:str
    intent_key:str|None=None
    order_state:str|None=None

def candidate_key(candidate:Candidate)->str:
    identity="|".join([candidate.account_id,candidate.strategy,candidate.version,
         candidate.symbol,candidate.asset_class.value,candidate.side.value,
         candidate.signal_at.isoformat()])
    return "v2_"+hashlib.sha256(identity.encode()).hexdigest()[:32]

class PaperPipeline:
    def __init__(self,broker:SimulatedBroker,store:EventStore,*,reviewer:AIReviewer|None=None):
        # A live broker adapter can never be slipped into this constructor.
        if type(broker) is not SimulatedBroker or not isinstance(store,EventStore):
            raise TypeError("V2 milestone-one pipeline only accepts SimulatedBroker")
        self.broker=broker
        self.store=store
        self.reviewer=reviewer

    def _result_existing(self,key):
        item=self.store.get(key)
        if item is None:return PipelineResult("UNKNOWN_INTENT","No local intent",key)
        state=OrderState(item["state"])
        if state in (OrderState.FILLED,OrderState.CANCELED,OrderState.REJECTED):
            return PipelineResult(state.value,"Existing persisted broker order",key,state.value)
        return self.reconcile(key)

    def reconcile(self,key)->PipelineResult:
        item=self.store.get(key)
        if item is None:return PipelineResult("UNKNOWN_INTENT","No recorded intent",key)
        state=OrderState(item["state"])
        if state in (OrderState.FILLED,OrderState.CANCELED,OrderState.REJECTED):
            return PipelineResult(state.value,"Confirmed terminal order",key,state.value)
        if state in (OrderState.PROPOSED,OrderState.RISK_APPROVED,OrderState.INTENT_PERSISTED):
            return PipelineResult("AWAITING_REVIEW","Persisted but not sent; new risk review required",key,state.value)
        try:
            actual=self.broker.find_order(key)
        except Exception:
            actual=None
        if actual is None:
            if state in (OrderState.SUBMITTING,OrderState.BROKER_ACCEPTED,
                         OrderState.PARTIALLY_FILLED):
                self.store.transition(key,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
                                     evidence={"reason":"BROKER_LOOKUP_UNAVAILABLE"})
            return PipelineResult("RECONCILIATION_REQUIRED",
                "Broker cannot verify original intent; never resend",key,
                self.store.get(key)["state"])
        return self._accept(key,actual)

    def _accept(self,key,receipt:BrokerExecution)->PipelineResult:
        item=self.store.get(key)
        if item is None:
            raise KeyError("Unknown persisted order intent")
        state=OrderState(item["state"])
        try:
            mismatch=receipt_failure(key,receipt,item["document"],self.store.events(key))
        except (ValueError,TypeError,KeyError):
            mismatch="BROKER_RECEIPT_EVIDENCE_UNVERIFIED"
        if mismatch:
            # Never mark an inconsistent provider acknowledgment as FILLED.
            # A later read-only lookup of the ORIGINAL order ID may resolve it.
            if state in (OrderState.SUBMITTING,OrderState.BROKER_ACCEPTED,
                         OrderState.PARTIALLY_FILLED):
                self.store.transition(key,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
                                      evidence={"reason":mismatch})
            return PipelineResult("RECONCILIATION_REQUIRED",mismatch,key,
                                  self.store.get(key)["state"])
        if state is OrderState.SUBMITTING or state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION:
            self.store.transition(key,OrderState.BROKER_ACCEPTED,
                evidence={"broker_order_id":receipt.broker_order_id})
            state=OrderState.BROKER_ACCEPTED
        if receipt.state=="FILLED":
            self.store.transition(key,OrderState.FILLED,
                evidence={"filled_quantity":str(receipt.filled_quantity),
                          "average_price":str(receipt.average_price),
                          "fees":str(receipt.fees)})
            return PipelineResult("FILLED","Simulated fill reconciled",key,"FILLED")
        if receipt.state=="PARTIALLY_FILLED":
            self.store.transition(key,OrderState.PARTIALLY_FILLED,
                evidence={"broker_order_id":receipt.broker_order_id,
                          "filled_quantity":str(receipt.filled_quantity),
                          "average_price":str(receipt.average_price),
                          "fees":str(receipt.fees)})
            return PipelineResult("PARTIALLY_FILLED","Await remaining fill",key,"PARTIALLY_FILLED")
        if receipt.state=="REJECTED":
            self.store.transition(key,OrderState.REJECTED,
                 evidence={"broker_order_id":receipt.broker_order_id,
                           "filled_quantity":str(receipt.filled_quantity),
                           "average_price":str(receipt.average_price),
                           "fees":str(receipt.fees)})
            return PipelineResult("REJECTED","Simulated broker rejection",key,"REJECTED")
        if receipt.state=="CANCELED":
            self.store.transition(key,OrderState.CANCELED,
                 evidence={"broker_order_id":receipt.broker_order_id,
                           "filled_quantity":str(receipt.filled_quantity),
                           "average_price":str(receipt.average_price),
                           "fees":str(receipt.fees)})
            return PipelineResult("CANCELED","Broker canceled order",key,"CANCELED")
        return PipelineResult("BROKER_ACCEPTED","Broker acknowledged original intent",key,
                              self.store.get(key)["state"])

    def evaluate(self,candidate:Candidate,quote:MarketSnapshot,policy:RiskPolicy,
                 *,now:datetime|None=None,daily_realized_loss=Decimal("0"),
                 entries_today=0,exits_today=0)->PipelineResult:
        if not isinstance(candidate,Candidate) or not isinstance(quote,MarketSnapshot):
            raise TypeError("Canonical candidate and quote required")
        explicit_clock=now is not None
        now=utc(now or datetime.now(timezone.utc))
        key=candidate_key(candidate)
        previous=self.store.get(key)
        if previous is not None:return self._result_existing(key)
        if self.store.pending(candidate.account_id):
            self.store.review(key,candidate.account_id,"RECONCILIATION_PENDING",
                "Existing unresolved account intent")
            return PipelineResult("BLOCKED","RECONCILIATION_PENDING",key)
        account=inspect_paper_adapter(self.broker,candidate.account_id)
        risk=evaluate_risk(account,candidate,quote,policy,now=now,
            daily_realized_loss=daily_realized_loss,entries_today=entries_today,
            exits_today=exits_today,estimated_fee_bps=self.broker.fee_bps)
        if risk.code!="PASS":
            self.store.review(key,candidate.account_id,risk.code,risk.reason)
            return PipelineResult("BLOCKED",risk.reason,key)

        if policy.ai_mode!="OFF":
            try:
                review=self.reviewer.review(candidate,quote) if self.reviewer else None
            except Exception:
                review=None
            # Re-check elapsed model time; the decision may legitimately complete
            # after the pre-review timestamp, but cannot be from the future.
            review_now=now if explicit_clock else utc(datetime.now(timezone.utc))
            if (not isinstance(review,AIReview) or review.symbol!=candidate.symbol
                    or review.reviewed_at>review_now+timedelta(seconds=2)
                    or review.expires_at<review_now):
                if policy.ai_mode=="REQUIRED":
                    self.store.review(key,candidate.account_id,"AI_UNAVAILABLE","AI review invalid or expired")
                    return PipelineResult("BLOCKED","AI_UNAVAILABLE",key)
                self.store.review(key,candidate.account_id,"AI_UNAVAILABLE","Optional review unavailable")
            elif review.state==AIState.VETO:
                self.store.review(key,candidate.account_id,"AI_VETO",review.reason[:180])
                return PipelineResult("BLOCKED","AI_VETO",key)
            elif review.state!=AIState.PASS and policy.ai_mode=="REQUIRED":
                self.store.review(key,candidate.account_id,"AI_UNAVAILABLE","Required model did not approve")
                return PipelineResult("BLOCKED","AI_UNAVAILABLE",key)

        intent=OrderIntent(key=key,account_id=candidate.account_id,strategy=candidate.strategy,
              symbol=candidate.symbol,asset_class=candidate.asset_class,side=candidate.side,
              quantity=risk.quantity,limit_price=risk.limit_price,proposed_at=now)
        item=self.store.prepare(intent,risk)
        if item["state"]!=OrderState.INTENT_PERSISTED.value:
            return self._result_existing(key)
        self.store.transition(key,OrderState.SUBMITTING,evidence={"mode":"SIMULATED_ONLY"})
        try:
            actual=self.broker.submit(intent)
        except SimulationRejected as exc:
            self.store.transition(key,OrderState.REJECTED,
                                  evidence={"reason":str(exc)[:150]})
            return PipelineResult("REJECTED",str(exc)[:150],key,"REJECTED")
        except Exception:
            self.store.transition(key,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
                                  evidence={"reason":"UNVERIFIED_POST_OUTCOME"})
            return PipelineResult("RECONCILIATION_REQUIRED",
                                  "Original broker submit outcome unknown",key,
                                  OrderState.UNKNOWN_REQUIRES_RECONCILIATION.value)
        return self._accept(key,actual)
