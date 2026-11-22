"""Account-scoped V1 worker placement, including V2 handoff exclusion.

Read selected original broker accounts and protected V1/V2 ownership state.
Does not arm V2, stop workers or call broker APIs; the unified parent uses the
decision to avoid respawning a legacy writer on an account owned by V2.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from .writer_ownership import inspect_ownership

@dataclass(frozen=True)
class V1WorkerPlacement:
    broker:str
    may_run:bool
    reason:str
    v1_scopes:int
    v2_scopes:int
    unverified_scopes:int
    def __post_init__(self):
        if (self.broker not in ("schwab","webull","robinhood_crypto") or
            type(self.may_run) is not bool or
            not isinstance(self.reason,str) or
            any(type(v) is not int or v<0 for v in
                (self.v1_scopes,self.v2_scopes,self.unverified_scopes))):
            raise ValueError("INVALID_V1_WORKER_PLACEMENT")


def _selected_accounts(state_dir,broker,config=None):
    root=Path(state_dir)
    if broker=="schwab":
        if not isinstance(config,dict):
            raise ValueError("SCHWAB_OWNER_CONFIG_UNVERIFIED")
        account=config.get("live_account_hash")
        if not isinstance(account,str) or not account:
            raise ValueError("SCHWAB_OWNER_ACCOUNT_UNVERIFIED")
        return (account,)
    if broker=="robinhood_crypto":
        from robinhood_policy import read_policy
        doc=read_policy(root)
        account=doc.get("account")
        # No account selected: V1 may still provide read-only monitoring;
        # its broker order code independently requires an approved account.
        if account is None or account=="":return ()
        if not isinstance(account,str):
            raise ValueError("ROBINHOOD_OWNER_ACCOUNT_UNVERIFIED")
        return (account,)
    if broker=="webull":
        from webull_trade_config import read
        policy=read(root)
        accounts=[]
        for enable_key,account_key in (
                ("trade_stocks","stock_account"),
                ("trade_crypto","crypto_account")):
            if policy[enable_key]:
                account=policy[account_key]
                if not isinstance(account,str) or not account:
                    raise ValueError("WEBULL_OWNER_ACCOUNT_UNVERIFIED")
                if account not in accounts:accounts.append(account)
        return tuple(accounts)
    raise ValueError("V1_WORKER_BROKER_UNRECOGNIZED")


def v1_worker_placement(state_dir,broker,*,config=None):
    """Fail closed for a protected owner if it cannot be independently read.

    Webull's original V1 worker can legitimately service stock and crypto
    accounts in one process; it may run for another V1-owned account, but
    every V1 broker POST must independently lock/check the exact account.
    """
    try:
        scopes=_selected_accounts(state_dir,broker,config)
    except Exception:
        return V1WorkerPlacement(broker,False,"V1_SELECTED_ACCOUNT_UNVERIFIED",0,0,1)
    if not scopes:
        return V1WorkerPlacement(broker,True,"V1_MONITOR_ONLY_NO_SELECTED_ACCOUNT",0,0,0)
    owners=[]
    for account in scopes:
        try:
            saved=inspect_ownership(state_dir,broker,account)
            owner=saved.get("owner") if isinstance(saved,dict) else None
            if owner not in ("V1","V2"):
                owner=None
        except Exception:
            owner=None
        owners.append(owner)
    v1=owners.count("V1");v2=owners.count("V2")
    bad=len(owners)-v1-v2
    if bad:
        return V1WorkerPlacement(broker,False,"V1_WRITER_OWNERSHIP_UNVERIFIED",
                                 v1,v2,bad)
    if v1:
        return V1WorkerPlacement(broker,True,
             "V1_EXCLUSIVE_WRITER" if not v2 else "V1_OTHER_ACCOUNT_ONLY",
             v1,v2,0)
    return V1WorkerPlacement(broker,False,"V2_ACCOUNT_OWNER_NO_V1_RESTART",0,v2,0)
