"""Single-image Auto Trader runtime: one Docker app, isolated child processes.

Only the dashboard starts on a fresh install. After user-owned GUI setup,
read-only broker monitoring and the paper simulator can be enabled in the UI.
Live execution requires a separate explicit live permission, a broker token,
and its existing broker preflight/order safeguards.
"""
from __future__ import annotations
import os, secrets, signal, subprocess, sys, time
from pathlib import Path
from unified_config import pairing_code, settings,credentials,configured

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
    env["AI_PROVIDER"]=config["ai_provider"]
    env["AI_OLLAMA_URL"]=config.get("ollama_url","")
    env["AI_MODEL"]=config["ai_model"]
    env["LOCAL_AI_URL"]=config.get("ollama_url","")
    env["LOCAL_AI_MODEL"]=config["ai_model"]
    env["DASHBOARD_LOCAL_AI_URL"]=config.get("ollama_url","")
    env["OAUTH_AI_URL"]=config.get("oauth_bridge_url","")
    env["OAUTH_AI_MODEL"]=config.get("oauth_model","")
    env["OAUTH_AI_BRIDGE_TOKEN"]=secret.get("oauth_bridge_token","")
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
                for name,command in (
                   ("paper",["/app/bot.py"]),
                   ("market",["/app/broker_market_data.py"])):
                    child=CHILDREN.get(name)
                    if enabled[name] and (child is None or child.poll() is not None):
                        if child and child.poll() is not None:
                            # Prevent a malformed config from causing rapid restart loops.
                            if getattr(child,"exit_checked",False):continue
                            child.exit_checked=True;continue
                        spawn(name,command,runtime_env)
                    if not enabled[name]:stop_process(name)
                if enabled["live"]:
                    if live_started_signature is None:
                        live_env=dict(runtime_env,LIVE_TRADING="true",LIVE_MODE="AUTONOMOUS",
                                      LIVE_ACCOUNT_HASH=cfg["live_account_hash"])
                        spawn("live",["/app/live_worker.py","--run"],live_env)
                        live_started_signature=str(cfg["live_account_hash"])
                    elif CHILDREN.get("live") and CHILDREN["live"].poll() is not None:
                        # Never auto-restart a dead broker worker after an exception.
                        print("Live worker stopped; operator review required.",flush=True)
                else:
                    stop_process("live");live_started_signature=None
            except (OSError,ValueError,TypeError,KeyError) as exc:
                print("Invalid stored app settings; optional workers stopped.",flush=True)
                for name in ("paper","market","live"):stop_process(name)
        else:
            for name in ("paper","market","live"):stop_process(name)
        time.sleep(4)
    for name in ("live","market","paper","dashboard"):stop_process(name)
    return 0

if __name__=="__main__":sys.exit(main())
