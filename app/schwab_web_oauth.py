"""User-driven Schwab OAuth from the authenticated Auto Trader GUI.

A browser signs in ONLY on Schwab; Auto Trader never handles broker passwords.
The redirect URL is pasted into the protected setup page to exchange the code.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, os, tempfile, time
from urllib.parse import urlparse,parse_qs
from unified_config import settings,credentials,atomic_save,SetupError
PENDING="schwab_oauth_pending.json"

def begin(state):
    from schwab.auth import get_auth_context
    config=settings(state); secret=credentials(state)
    if not config["schwab_app_key"] or not secret.get("schwab_app_secret"):
        raise SetupError("Save Schwab developer app credentials before connecting")
    callback=config["schwab_callback_url"]
    context=get_auth_context(config["schwab_app_key"],callback)
    atomic_save(Path(state)/PENDING,{
        "callback":callback,"state":context.state,
        "authorization_url":context.authorization_url,"created":time.time()
    })
    automatic=urlparse(callback).hostname!="127.0.0.1"
    return {"authorization_url":context.authorization_url,"callback_url":callback,
            "automatic_callback":automatic,
            "instructions":("Schwab will return automatically to the Auto Trader HTTPS page."
             if automatic else
             "The browser may show cannot connect at 127.0.0.1:8182 because no local listener is running. This is expected. Copy the FULL callback URL from the address bar (including code and state), return to Auto Trader, and paste it into the form. Never share that URL.")}

def finish(state,returned_url):
    from schwab.auth import AuthContext,client_from_received_url
    data=Path(state)/PENDING
    pending=json.loads(data.read_text(encoding="utf-8"))
    if time.time()-float(pending.get("created",0))>600:
        raise SetupError("Schwab authorization expired; start again")
    if not isinstance(returned_url,str) or len(returned_url)>5000:
        raise SetupError("Invalid Schwab redirected address")
    target=urlparse(pending["callback"])
    url=urlparse(returned_url)
    if (url.scheme!=target.scheme or url.netloc!=target.netloc or
        url.path!=target.path or url.fragment):
        raise SetupError("Schwab callback does not match the registered URL")
    params=parse_qs(url.query)
    if params.get("state")!=[pending["state"]] or "code" not in params:
        raise SetupError("OAuth callback state mismatch")
    cfg=settings(state);secret=credentials(state)
    token=Path(state)/"schwab_token.json"
    # Existing tokens cannot be overwritten by accident or during a running session.
    if token.exists() and token.stat().st_size>0:
        raise SetupError("Schwab is already connected. Reauthorization requires a separate token migration.")
    def write_token(document,*args,**kwargs):
        atomic_save(token,document)
    context=AuthContext(pending["callback"],pending["authorization_url"],pending["state"])
    client_from_received_url(cfg["schwab_app_key"],secret["schwab_app_secret"],
                             context,returned_url,write_token,enforce_enums=True)
    data.unlink(missing_ok=True)
    return {"connected":True}


def accounts(state):
    """List only masked account numbers + Schwab account hashes for GUI selection."""
    import re
    from schwab.auth import client_from_token_file
    cfg=settings(state);secret=credentials(state)
    token=Path(state)/"schwab_token.json"
    if not token.is_file() or not secret.get("schwab_app_secret"):
        raise SetupError("Connect your Schwab account first")
    client=client_from_token_file(str(token),cfg["schwab_app_key"],
                                  secret["schwab_app_secret"])
    response=client.get_account_numbers()
    if response.status_code!=200:raise SetupError("Schwab account lookup failed")
    result=response.json()
    if not isinstance(result,list) or len(result)>20:
        raise SetupError("Unexpected broker account response")
    choices=[]
    for item in result:
        if not isinstance(item,dict):continue
        raw=item.get("accountNumber");hashval=item.get("hashValue")
        if (not isinstance(raw,str) or not isinstance(hashval,str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{5,150}",hashval)):continue
        choices.append({"label":"Schwab account ending "+raw[-4:],"hash":hashval})
    return {"accounts":choices}
