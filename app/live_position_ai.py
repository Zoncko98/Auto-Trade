"""Advisory recurring AI evidence for held positions; never authorizes SELL orders."""
from datetime import datetime, timezone, timedelta
from ai_research import approve_entry, research_evidence

REVIEW_INTERVAL=timedelta(minutes=15)

def should_review(last, now):
    if now.tzinfo is None:
        return False
    try:
        stamp=datetime.fromisoformat(last.replace("Z","+00:00"))
        return stamp.tzinfo is None or not (stamp<=now<stamp+REVIEW_INTERVAL)
    except (ValueError,TypeError,AttributeError):
        return True

def review_held(positions, now, previous=None, reviewer=approve_entry, evidence=research_evidence):
    """Return fresh advisory records, reusing current validated news-classifier gate.

    The BUY-veto output is explicitly NOT interpreted as a SELL instruction.
    A failed AI review never inhibits rule-based protective selling.
    """
    previous=previous if isinstance(previous,dict) else {}
    reports={}
    for symbol in sorted(positions):
        old=previous.get(symbol,{})
        if isinstance(old,dict) and not should_review(old.get("at"),now):
            reports[symbol]=old
            continue
        try:
            approved,reason=reviewer(symbol,now)
            detail=evidence(symbol,now) if approved else {}
            reports[symbol]={"at":now.isoformat(),"symbol":symbol,
                "status":"evidence_positive" if approved else "review_required",
                "summary":str(reason)[:350],
                "model":str(detail.get("model","unavailable"))[:96],
                "execution_authorized":False}
        except Exception:
            reports[symbol]={"at":now.isoformat(),"symbol":symbol,
                "status":"ai_unavailable","summary":"AI review failed; protective exits remain active",
                "execution_authorized":False}
    return reports
