"""Observable trade decision evidence; does not expose model thoughts."""
from decimal import Decimal

def comparisons(ranked, selected):
    return [{"symbol":sym,"rank":i+1,"score":str(score),
             "outcome":"selected" if sym==selected else "screened_not_selected",
             "note":"Screening rank only; entry signal not necessarily evaluated"}
             for i,(score,sym,bid,ask) in enumerate(ranked[:8])]

def explanation(symbol,technical,ai_reason,alternatives=(),risk_flags=(),when=None,invalidation=None):
    if invalidation is not None:
        v=Decimal(str(invalidation))
        if not v.is_finite() or v<=0: raise ValueError("Invalid invalidation level")
    return {"symbol":symbol,"technical_evidence":technical,"ai_assessment":ai_reason,
            "risk_flags":list(risk_flags)[:8],"alternatives":list(alternatives)[:8],
            "invalidation_level":str(invalidation) if invalidation is not None else None,
            "invalidation_note":"Not available from verified data" if invalidation is None else "Thesis invalidation, not a stop order",
            "as_of":when,"confidence_probability":None}
