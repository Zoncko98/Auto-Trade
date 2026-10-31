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

def _url_matches_registered_callback(registered,received):
    """A browser may add '/' to an empty root path; never relax host, port or scheme."""
    if (registered.scheme!="https" or received.scheme!="https"
        or registered.netloc!=received.netloc
        or registered.username or registered.password
        or received.username or received.password
        or received.fragment or received.params or registered.query):
        return False
    if registered.path in ("","/") and received.path in ("","/"):
        return True
    return registered.path==received.path

def _callback_origin(url):
    """Safe error message excludes all query parameters and authorization codes."""
    if not url.scheme or not url.netloc:
        return "invalid URL"
    return url.scheme+"://"+url.netloc+(url.path or "")

def finish(state,returned_url):
    from schwab.auth import AuthContext,client_from_received_url
    data=Path(state)/PENDING
    pending=json.loads(data.read_text(encoding="utf-8"))
    if time.time()-float(pending.get("created",0))>600:
        raise SetupError("Schwab authorization expired; start again")
    if not isinstance(returned_url,str) or len(returned_url)>5000:
        raise SetupError("Invalid Schwab redirected address")
    returned_url=returned_url.strip()
    if not returned_url or any(ord(ch)<32 for ch in returned_url):
        raise SetupError("Invalid Schwab redirected address")
    target=urlparse(pending["callback"])
    url=urlparse(returned_url)
    if not _url_matches_registered_callback(target,url):
        # Print only redirect base addresses, NEVER the code or OAuth state.
        raise SetupError("Schwab callback address mismatch. Expected "+
                         _callback_origin(target)+" but received "+
                         _callback_origin(url)+
                         ". Check the registered callback address in the Schwab Developer Portal, save it, and start a NEW connection.")
    params=parse_qs(url.query,keep_blank_values=True)
    if "error" in params:
        raise SetupError("Schwab did not authorize this connection. Start a new sign-in.")
    if params.get("state")!=[pending["state"]]:
        raise SetupError("Schwab sign-in session mismatch. Start a NEW connection using the latest Schwab sign-in link.")
    if len(params.get("code",[]))!=1 or not params["code"][0]:
        raise SetupError("Schwab callback did not contain a valid authorization code.")
    cfg=settings(state);secret=credentials(state)
    token=Path(state)/"schwab_token.json"
    # Existing tokens cannot be overwritten by accident or during a running session.
    if token.exists() and token.stat().st_size>0:
        raise SetupError("Schwab is already connected. Reauthorization requires a separate token migration.")
    def write_token(document,*args,**kwargs):
        atomic_save(token,document)
    context=AuthContext(pending["callback"],pending["authorization_url"],pending["state"])
    try:
        client_from_received_url(cfg["schwab_app_key"],secret["schwab_app_secret"],
                                 context,returned_url,write_token,enforce_enums=True)
    except Exception:
        raise SetupError("Schwab token exchange failed. Confirm your developer app is Ready For Use and the callback registered there exactly matches the one in Auto Trader. Start a NEW connection; the old code cannot be reused.") from None
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
