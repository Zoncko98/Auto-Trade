"""Single-image Auto Trader runtime: one Docker app, isolated child processes.

Only the dashboard starts on a fresh install. After user-owned GUI setup,
read-only broker monitoring and the paper simulator can be enabled in the UI.
Live execution requires a separate explicit live permission, a broker token,
and its existing broker preflight/order safeguards.
"""
from __future__ import annotations
import json, os, secrets, signal, subprocess, sys, tempfile, time
from pathlib import Path
from unified_config import pairing_code, settings,credentials,configured
from schwab_auth_health import reauth_required

STATE=Path(os.getenv("STATE_DIR","/state"))
LOGS=Path(os.getenv("LOG_DIR","/logs"))
CHILDREN={}
_STOP=False

def persistent_secret(name,length=48):
    path=STATE/name
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w") as f:f.write(secrets.token_urlsafe(length))
    except FileExistsError:pass
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe persistent secret permissions")
    return path.read_text().strip()

def certificate():
    ssl_dir=STATE/"tls"
    ssl_dir.mkdir(mode=0o700,exist_ok=True)
    cert=ssl_dir/"cert.pem";key=ssl_dir/"key.pem"
    if not cert.exists() or not key.exists():
        subprocess.run(["openssl","req","-x509","-nodes","-newkey","rsa:2048",
           "-days","365","-keyout",str(key),"-out",str(cert),
           "-subj","/CN=auto-trader.local"],check=True,
           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=18)
        os.chmod(key,0o600)
    if key.stat().st_mode & 0o077:raise RuntimeError("Unsafe TLS private-key permissions")
    return cert,key

# Replacements may have a new working broker order outside the old journal.
_LIVE_TERMINAL = frozenset({"FILLED","CANCELED","REJECTED","EXPIRED"})

def live_journal_safe_for_restart(state_dir):
    """Never restart an autonomous live worker with an ambiguous broker order."""
    path=Path(state_dir)/"live"/"orders.json"
    try:
        if not path.is_file() or path.stat().st_size>4_000_000:
            return False,"JOURNAL_MISSING_OR_OVERSIZE"
        doc=json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(doc,dict) or doc.get("version")!=1
                or doc.get("halted") is not False):
            return False,"JOURNAL_INVALID_OR_HALTED"
        orders=doc.get("orders")
        if (not isinstance(orders,list) or
                any(not isinstance(o,dict) or o.get("state") not in _LIVE_TERMINAL
                    for o in orders)):
            return False,"BROKER_ORDER_RECONCILIATION_REQUIRED"
        return True,"ALL_BROKER_ORDERS_TERMINAL"
    except (OSError,ValueError,TypeError):
        return False,"JOURNAL_UNVERIFIED"

def live_supervisor_event(state,reason,attempts=0,exit_code=None):
    """Atomic owner-only, nonsecret health evidence for the Schwab dashboard."""
    path=STATE/"live"/"supervisor_status.json"
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    payload={"version":1,"state":str(state)[:45],
             "reason":str(reason)[:90],"recovery_attempts_last_hour":attempts,
             "last_exit_code":exit_code if type(exit_code) is int else None,
             "at":time.time()}
    # The supervisor loops every four seconds. Avoid repeatedly fsyncing
    # identical health records when a broker outage lasts for hours.
    try:
        previous=json.loads(path.read_text(encoding="utf-8"))
        if all(previous.get(k)==payload.get(k) for k in
               ("state","reason","recovery_attempts_last_hour","last_exit_code")):
            return
    except (OSError,ValueError,TypeError):
        pass
    raw=json.dumps(payload,separators=(",",":"),allow_nan=False).encode()
    fd,temp=tempfile.mkstemp(prefix=".supervisor-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as out:
            os.fchmod(out.fileno(),0o600)
            out.write(raw);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def stop_process(name):
    child=CHILDREN.pop(name,None)
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=12)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)

def spawn(name,args,env):
    print("Auto Trader starting "+name,flush=True)
    CHILDREN[name]=subprocess.Popen([sys.executable,"-u",*args],
         env=env,cwd="/app")

def terminate(_sig,_frame):
    global _STOP
    _STOP=True

def build_env(config,secret):
    env=dict(os.environ)
    env["STATE_DIR"]=str(STATE)
    env["LOG_DIR"]=str(LOGS)
    env["PAPER_INITIAL_CAPITAL"]=str(config["paper_capital"])
    env["INITIAL_CAPITAL"]=str(config["paper_capital"])
    env["LIVE_TRADING"]="false"
    env["LIVE_MODE"]="DISABLED"
    env["SCHWAB_ENV_FILE"]=str(STATE/"config"/"schwab.env")
    env["SCHWAB_TOKEN_FILE"]=str(STATE/"schwab_token.json")
    env["LIVE_STATE_DIR"]=str(STATE/"live")
    env["BROKER_MARKET_STATE_DIR"]=str(STATE/"live")
    env["FORECAST_API_URL"]=config.get("forecast_url","")
    env["AI_PROVIDER"]="local" if config["ai_provider"]=="ollama" else config["ai_provider"]
    env["AI_OLLAMA_URL"]=config.get("ollama_url","")
    env["AI_MODEL"]=config["ai_model"]
    env["LOCAL_AI_URL"]=config.get("ollama_url","")
    env["LOCAL_AI_MODEL"]=config["ai_model"]
    env["DASHBOARD_LOCAL_AI_URL"]=config.get("ollama_url","")
    env["OAUTH_AI_URL"]=config.get("oauth_bridge_url","")
    env["OAUTH_AI_MODEL"]=config.get("oauth_model","")
    env["OAUTH_AI_BRIDGE_TOKEN"]=secret.get("oauth_bridge_token","")
    return env

def paper_environment(runtime_env):
    """Paper and live use identical news AI configuration and stock signals."""
    env=dict(runtime_env)
    env["AI_REVIEW_TIMEOUT_SECONDS"]="18"
    # Shared news classifier takes LOCAL_AI_URL and LOCAL_AI_MODEL, matching
    # Schwab. Legacy paper monitoring also expects an Ollama generate route.
    base=env.get("LOCAL_AI_URL") or env.get("AI_OLLAMA_URL","")
    if env.get("AI_PROVIDER") in ("local","ollama") and base:
        env["AI_OLLAMA_URL"]=base.rstrip("/")+"/api/generate"
    else:
        env["AI_OLLAMA_URL"]=""
        env["AI_MODEL"]=""
    env["PAPER_PUBLIC_MARKET_DATA"]="true"
    env["PAPER_SYMBOLS"]="SPY,QQQ,AAPL,MSFT,BTCUSD,ETHUSD"
    return env

def main():
    STATE.mkdir(parents=True,exist_ok=True)
    LOGS.mkdir(parents=True,exist_ok=True)
    (STATE/"live").mkdir(parents=True,exist_ok=True)
    password=persistent_secret(".fallback_password")
    session=persistent_secret(".session_secret")
    cert,key=certificate()
    code=pairing_code(STATE)
    if code:
        print("\n"+"="*65,flush=True)
        print("Auto Trader first-run setup: use your TrueNAS app logs to obtain this pairing code.",flush=True)
        print("ONE-TIME SETUP CODE: "+code,flush=True)
        print("Open the HTTPS Auto Trader port and enter this code to create your own administrator account.",flush=True)
        print("No paper, market-data, or live worker will start until configured.",flush=True)
        print("="*65+"\n",flush=True)
    signal.signal(signal.SIGTERM,terminate)
    signal.signal(signal.SIGINT,terminate)
    env=dict(os.environ,STATE_DIR=str(STATE),LOG_DIR=str(LOGS),
             DASHBOARD_PASSWORD=password,DASHBOARD_SESSION_SECRET=session,
             DASHBOARD_TLS_CERT=str(cert),DASHBOARD_TLS_KEY=str(key),
             DASHBOARD_BIND="0.0.0.0",DASHBOARD_PORT="8765")
    spawn("dashboard",["/app/dashboard_server.py"],env)
    live_started_signature=None
    live_stop_logged=False
    live_last_spawn_at=0.0
    live_recovery_attempts=[]
    paper_last_spawn=0.0
    webull_last_spawn=0.0
    webull_feed_last_spawn=0.0
    while not _STOP:
        dash=CHILDREN.get("dashboard")
        if dash is None or dash.poll() is not None:
            print("Dashboard exited; stopping unified application.",flush=True)
            break
        enabled={"paper":False,"market":False,"live":False}
        if configured(STATE):
            try:
                cfg=settings(STATE);sec=credentials(STATE)
                broker_ready=(STATE/"schwab_token.json").is_file() and (STATE/"config"/"schwab.env").is_file()
                enabled["paper"]=cfg["paper_enabled"]
                enabled["market"]=cfg["market_enabled"] and broker_ready
                # Live only after an explicit operator approval and account-hash setup.
                enabled["live"]=bool(cfg.get("live_enabled",False) and
                  cfg.get("live_confirmed",False) and broker_ready and
                  cfg.get("live_account_hash"))
                if enabled["live"]:enabled["market"]=False
                runtime_env=build_env(cfg,sec)
                rh_ready=(STATE/"config"/"robinhood_crypto.json").is_file()
                rh=CHILDREN.get("robinhood")
                if rh_ready and (rh is None or rh.poll() is not None):
                    spawn("robinhood",["/app/robinhood_worker.py"],runtime_env)
                if not rh_ready:stop_process("robinhood")
                wb_ready=(STATE/"config"/"webull_openapi.json").is_file()
                wb=CHILDREN.get("webull")
                if wb_ready and (wb is None or wb.poll() is not None):
                    if time.monotonic()-webull_last_spawn>=120 or wb is None and webull_last_spawn==0:
                        webull_last_spawn=time.monotonic()
                        spawn("webull",["/app/webull_worker.py"],runtime_env)
                if not wb_ready:stop_process("webull")
                feed=CHILDREN.get("webull-feed")
                if wb_ready:
                    if feed is None or feed.poll() is not None:
                        if time.monotonic()-webull_feed_last_spawn>=20 or webull_feed_last_spawn==0:
                            webull_feed_last_spawn=time.monotonic()
                            spawn("webull-feed",["/app/webull_streaming.py"],runtime_env)
                else:
                    stop_process("webull-feed")
                for name,command in (
                   ("paper",["/app/live_worker.py","--account","paper","--run"]),
                   ("market",["/app/broker_market_data.py"])):
                    child=CHILDREN.get(name)
                    if name=="paper":
                        if not enabled[name]:
                            stop_process("paper")
                        elif child is None or (child.poll() is not None and time.monotonic()-paper_last_spawn>=120):
                            if child is not None:
                                print("Paper worker exited with code "+str(child.poll())+
                                      "; retrying paper worker only.",flush=True)
                                CHILDREN.pop("paper",None)
                            paper_last_spawn=time.monotonic()
                            spawn("paper",command,paper_environment(runtime_env))
                        continue
                    if enabled[name] and (child is None or child.poll() is not None):
                        if child and child.poll() is not None:
                            # Prevent a malformed config from causing rapid restart loops.
                            if getattr(child,"exit_checked",False):continue
                            child.exit_checked=True;continue
                        spawn(name,command,runtime_env)
                    if not enabled[name]:stop_process(name)
                if enabled["live"]:
                    if live_started_signature is None:
                        if reauth_required(STATE):
                            live_supervisor_event("REAUTH_REQUIRED",
                                "SCHWAB_OAUTH_REAUTH_REQUIRED")
                        else:
                            live_env=dict(runtime_env,LIVE_TRADING="true",LIVE_MODE="AUTONOMOUS",
                                          LIVE_ACCOUNT_HASH=cfg["live_account_hash"])
                            spawn("live",["/app/live_worker.py","--account","schwab","--run"],live_env)
                            live_started_signature=str(cfg["live_account_hash"])
                            live_stop_logged=False
                            live_last_spawn_at=time.monotonic()
                            live_supervisor_event("STARTED","OPERATOR_AUTHORIZED")
                    elif CHILDREN.get("live") and CHILDREN["live"].poll() is not None:
                        child=CHILDREN["live"]
                        exit_code=child.poll()
                        if not live_stop_logged:
                            print("Schwab worker exited; evaluating broker-order journal "
                                  "before any recovery.",flush=True)
                            live_supervisor_event("EXITED","VERIFYING_JOURNAL",
                                len(live_recovery_attempts),exit_code)
                            live_stop_logged=True
                        safe,why=live_journal_safe_for_restart(STATE)
                        now=time.monotonic()
                        live_recovery_attempts=[t for t in live_recovery_attempts
                                                if now-t<3600]
                        if not safe:
                            live_supervisor_event("RECONCILIATION_REQUIRED",why,
                                len(live_recovery_attempts),exit_code)
                        elif reauth_required(STATE):
                            # Do not burn the restart budget on a known revoked
                            # refresh token. A new token is still subject to
                            # full broker and order-journal preflight.
                            live_supervisor_event("REAUTH_REQUIRED",
                                "SCHWAB_OAUTH_REAUTH_REQUIRED",
                                len(live_recovery_attempts),exit_code)
                        elif len(live_recovery_attempts)>=3:
                            live_supervisor_event("MANUAL_REVIEW_REQUIRED",
                                "RESTART_BUDGET_EXHAUSTED",len(live_recovery_attempts),exit_code)
                        elif now-live_last_spawn_at>=120:
                            # The operator's existing live approval remains
                            # necessary. The worker will authenticate, reconcile
                            # and recheck cash, candles, AI, risk and broker orders
                            # before any submission. No unresolved order replay.
                            live_env=dict(runtime_env,LIVE_TRADING="true",LIVE_MODE="AUTONOMOUS",
                                          LIVE_ACCOUNT_HASH=cfg["live_account_hash"])
                            live_recovery_attempts.append(now)
                            live_supervisor_event("RECOVERING",why,
                                len(live_recovery_attempts),exit_code)
                            spawn("live",["/app/live_worker.py","--account","schwab","--run"],live_env)
                            live_last_spawn_at=now
                            live_stop_logged=False
                        else:
                            live_supervisor_event("RETRY_BACKOFF",why,
                                len(live_recovery_attempts),exit_code)
                    elif CHILDREN.get("live") and CHILDREN["live"].poll() is None:
                        live_supervisor_event("RUNNING",
                            "ORDER_GATE_CHECKS_APPLY",len(live_recovery_attempts))
                else:
                    if live_started_signature is not None:
                        live_supervisor_event("DISABLED","USER_OR_CONFIGURATION_DISABLED")
                    stop_process("live");live_started_signature=None
                    live_stop_logged=False
                    live_recovery_attempts=[]
            except (OSError,ValueError,TypeError,KeyError) as exc:
                print("Invalid stored app settings; optional workers stopped.",flush=True)
                for name in ("paper","market","live"):stop_process(name)
        else:
            for name in ("paper","market","live"):stop_process(name)
        time.sleep(4)
    for name in ("webull-feed","webull","robinhood","live","market","paper","dashboard"):stop_process(name)
    return 0

if __name__=="__main__":sys.exit(main())
