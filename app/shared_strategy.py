"""Identical candidate selection for simulated and brokerage accounts."""
from autonomous_selector import UNIVERSE,ranked_candidates,choose_entry

def select_entry(quote_rows,candle_provider,now,excluded=(),universe=UNIVERSE):
    """Pure strategy selection; cannot place orders or modify an account."""
    excluded=set(excluded)
    ranked=[r for r in ranked_candidates(quote_rows,now,universe=universe)
            if r[1] not in excluded]
    candidate=choose_entry(ranked,candle_provider,now,can_buy=True) if ranked else None
    return candidate,ranked
