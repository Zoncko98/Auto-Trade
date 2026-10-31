#!/usr/bin/env python3
"""Interactive TrueNAS SCALE installer for the portable Auto Trader build.
Prepares private local configuration; does not enable live brokerage orders.
"""
from __future__ import annotations
import argparse, getpass, ipaddress, os, pathlib, re, secrets, shutil, subprocess, sys
from urllib.parse import urlparse

REPO=pathlib.Path(__file__).resolve().parents[1]
ENV_PATTERN=re.compile(r"^[A-Za-z0-9_:/@.!+\-=]{1,600}$")
SECRET_PATTERN=re.compile(r"^[A-Za-z0-9_:/@.!+\-=]{4,600}$")

def env_value(value, field):
    if value=="":return value
    if not isinstance(value,str) or not ENV_PATTERN.fullmatch(value):
        raise ValueError(f"{field}: unsupported characters for a safe env file (avoid $, #, spaces, quotes)")
    return value

def local_address(url, label="Ollama"):
    u=urlparse(url.strip())
    if u.scheme not in ("http","https") or not u.hostname or u.username or u.password or u.path not in ("","/") or u.query or u.fragment:
        raise ValueError(label+": must be http(s)://host:port without credentials, paths or query")
    if u.port is None:raise ValueError(label+": specify a TCP port")
    try:
        ip=ipaddress.ip_address(u.hostname)
        if not (ip.is_private or ip.is_loopback):
            raise ValueError(label+": local API must use a private-network IP")
    except ValueError as e:
        if "private-network" in str(e):raise
        if u.hostname not in ("localhost","host.docker.internal","local-ai") and not u.hostname.endswith(".local"):
            raise ValueError(label+": use a private IPv4/IPv6 address or trusted .local hostname") from None
    return u.geturl().rstrip("/")

def cloud_url(value):
    u=urlparse(value.strip())
    if u.scheme!="https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("External AI provider must use an HTTPS API base URL")
    return u.geturl().rstrip("/")

def prompt(label,default=None,secret=False):
    suffix=f" [{default}]" if default is not None and not secret else ""
    fn=getpass.getpass if secret else input
    val=fn(label+suffix+": ").strip()
    return val or (default if default is not None else "")

def safe_host(value):
    if value=="0.0.0.0":return value
    ip=ipaddress.ip_address(value)
    if not (ip.is_private or ip.is_loopback):raise ValueError("Use a LAN IP or 0.0.0.0")
    return value

def private_write(path,lines,overwrite=False):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.exists() and not overwrite:raise FileExistsError("Preserving existing private config: "+str(path))
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            for key,value in lines.items():f.write(key+"="+env_value(str(value),key)+"\n")
    finally:os.chmod(path,0o600)

def make_cert(folder,nas_host):
    crt=folder/"cert.pem";key=folder/"key.pem"
    if crt.exists() or key.exists():
        if crt.exists() and key.exists():return
        raise ValueError("One TLS file exists but not the other; repair manually")
    if not shutil.which("openssl"):raise RuntimeError("openssl command is required for HTTPS certificate generation")
    subprocess.run(["openssl","req","-x509","-newkey","rsa:3072","-sha256","-nodes",
                    "-days","365","-keyout",str(key),"-out",str(crt),
                    "-subj","/CN=auto-trader.local"],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600);crt.chmod(0o644)

def create_layout(data_dir,nas_ip,port,password,ai,schwab=None,dry_run=False,platform="truenas"):
    data_dir=pathlib.Path(data_dir).expanduser().resolve()
    if platform not in ("truenas","docker"):raise ValueError("Unsupported host platform")
    if platform=="truenas" and not dry_run and (len(data_dir.parts)<4 or data_dir.parts[1]!="mnt"):
        raise ValueError("TrueNAS installs require storage under /mnt/<POOL>/...")
    if REPO==data_dir or REPO in data_dir.parents:
        raise ValueError("Configuration must be outside the git checkout")
    safe_host(nas_ip)
    if not 1024<=int(port)<=65535:raise ValueError("Dashboard port must be >=1024")
    if len(password)<20 or not ENV_PATTERN.fullmatch(password):
        raise ValueError("Dashboard password must be >=20 chars using letters, digits or @!._+-=")
    mode=ai.get("provider")
    if mode not in ("none","ollama","openai-compatible"):raise ValueError("Unsupported AI provider")
    if mode=="ollama":
        ai_url=local_address(ai["url"])
        model=env_value(ai["model"],"LOCAL_AI_MODEL")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}",model):raise ValueError("Invalid Ollama model tag")
        ai_env={"AI_PROVIDER":"local","LOCAL_AI_URL":ai_url,"LOCAL_AI_MODEL":model}
    elif mode=="openai-compatible":
        model=env_value(ai["model"],"AI_API_MODEL")
        key=env_value(ai["key"],"AI_API_KEY")
        base=cloud_url(ai["base_url"])
        route=ai.get("path","/v1/chat/completions")
        if not re.fullmatch(r"/[A-Za-z0-9_./-]{1,150}",route) or ".." in route:
            raise ValueError("Invalid provider chat-completions path")
        ai_env={"AI_PROVIDER":"openai-compatible","AI_API_BASE_URL":base,"AI_API_CHAT_PATH":route,
                "AI_API_KEY":key,"AI_API_MODEL":model}
    else:ai_env={"AI_PROVIDER":"disabled"}
    forecast=ai.get("forecast_url","").strip()
    if forecast:forecast=local_address(forecast,"Forecast service")
    dashboard={"DASHBOARD_PASSWORD":password,"DASHBOARD_SESSION_SECRET":secrets.token_hex(40),
               "PAPER_INITIAL_CAPITAL":"100"}
    schwab=schwab or {}
    key=schwab.get("app_key","")
    app_secret=schwab.get("app_secret","")
    callback=schwab.get("callback","https://127.0.0.1:8182")
    if bool(key)!=bool(app_secret):
        raise ValueError("Both Schwab developer app key and app secret are needed")
    if key:
        env_value(key,"SCHWAB_APP_KEY")
        env_value(app_secret,"SCHWAB_APP_SECRET")
    cb=urlparse(callback)
    if cb.scheme!="https" or cb.hostname!="127.0.0.1" or not 1024<=int(cb.port or 0)<=65535 or cb.path not in ("","/"):
        raise ValueError("Schwab OAuth callback must match registered https://127.0.0.1:PORT")
    compose={"AUTOTRADER_DATA_DIR":str(data_dir),
             "NAS_BIND_IP":nas_ip,"DASHBOARD_HOST_PORT":str(port),
             "AI_OLLAMA_URL":ai_env.get("LOCAL_AI_URL","http://127.0.0.1:11434"),
             "FORECAST_API_URL":forecast}
    live=dict(ai_env,LIVE_TRADING="false",LIVE_MODE="AUTONOMOUS",LIVE_ACCOUNT_HASH="")
    schwab_env={"SCHWAB_APP_KEY":key,"SCHWAB_APP_SECRET":app_secret,"SCHWAB_CALLBACK_URL":callback}
    if dry_run:return {"compose":compose,"ai":ai_env,"schwab_configured":bool(key),"forecast_configured":bool(forecast)}
    folders=[data_dir,data_dir/"config",data_dir/"state",data_dir/"state"/"live",data_dir/"logs",data_dir/"tls"]
    for folder in folders:
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        folder.chmod(0o700)
    # On reinstall, NEVER silently destroy existing secrets or token.
    if any((data_dir/"config"/name).exists() for name in ("compose.env","dashboard.env","live.env","schwab.env")):
        raise FileExistsError("Installation already configured; back up and use a dedicated update procedure")
    make_cert(data_dir/"tls",nas_ip)
    private_write(data_dir/"config"/"compose.env",compose)
    private_write(data_dir/"config"/"dashboard.env",dashboard)
    private_write(data_dir/"config"/"live.env",live)
    private_write(data_dir/"config"/"schwab.env",schwab_env)
    private_write(data_dir/"config"/"paper.env",{"INITIAL_CAPITAL":"100","LOG_DIR":"/logs","STATE_DIR":"/state"})
    token=data_dir/"state"/"schwab_token.json"
    if not token.exists():token.touch(mode=0o600)
    token.chmod(0o600)
    return {"config_path":str(data_dir/"config"/"compose.env"),"schwab_configured":bool(key),
            "dashboard_url":"https://"+nas_ip+":"+str(port),"data_dir":str(data_dir)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run",action="store_true",help="Print usage instructions; no secrets created")
    parser.add_argument("--install",action="store_true",help="After setup, build and start the dashboard only")
    parser.add_argument("--platform",choices=("truenas","docker"),default="truenas",help="Host platform; generic Docker also covers many NAS and Linux servers")
    args=parser.parse_args()
    if args.dry_run:
        print("Setup wizard supports Ollama, OpenAI-compatible APIs, or AI disabled.")
        print("The dashboard is installed first. Live brokerage execution is never enabled at install.")
        return
    print("Auto Trader — portable Docker/TrueNAS setup",args.platform)
    print("No Schwab login passwords are collected; broker authorization happens through Schwab OAuth.")
    print("All private config and account tokens are stored outside this Git checkout.")
    path=prompt("Persistent host data location", "/mnt/tank/apps/auto-trader" if args.platform=="truenas" else "/srv/auto-trader-data")
    host=prompt("Server LAN IPv4 address (0.0.0.0 binds all interfaces)","0.0.0.0")
    port=prompt("HTTPS dashboard port","8765")
    password=prompt("Dashboard password (20+ characters)",secret=True)
    if password!=prompt("Confirm dashboard password",secret=True):
        raise ValueError("Passwords did not match")
    choice=prompt("AI provider: 1 Ollama / 2 OpenAI-compatible / 3 None","1")
    ai={"provider":{"1":"ollama","2":"openai-compatible","3":"none"}.get(choice,"none")}
    if ai["provider"]=="ollama":
        ai["url"]=prompt("Ollama LAN API URL","http://192.168.1.100:11434")
        ai["model"]=prompt("Ollama model tag","qwen3.5:4b")
    elif ai["provider"]=="openai-compatible":
        ai["base_url"]=prompt("Provider HTTPS base URL","https://api.openai.com")
        ai["path"]=prompt("Chat completions route","/v1/chat/completions")
        ai["model"]=prompt("Provider model identifier")
        ai["key"]=prompt("Provider API key (hidden)",secret=True)
    ai["forecast_url"]=prompt("Optional read-only forecast service URL (blank to skip)","")
    schwab={}
    if prompt("Configure Schwab developer app credentials now? y/N","n").lower()=="y":
        schwab["app_key"]=prompt("Schwab developer APP KEY (hidden)",secret=True)
        schwab["app_secret"]=prompt("Schwab developer APP SECRET (hidden)",secret=True)
        schwab["callback"]=prompt("Registered Schwab OAuth callback URL","https://127.0.0.1:8182")
    result=create_layout(path,host,port,password,ai,schwab,platform=args.platform)
    print("Private configuration prepared at",result["config_path"])
    if args.install:
        command=["docker","compose","--env-file",result["config_path"],"-f",str(REPO/"deploy"/"docker-compose.yml"),"up","-d","--build","dashboard"]
        subprocess.run(command,check=True)
        print("Dashboard container installed; live-trader profile remains disabled.")
    print("IMPORTANT: Brokerage execution remains DISABLED.")
    print("Run: docker compose --env-file",result["config_path"],"-f",REPO/"deploy"/"docker-compose.yml","up -d --build dashboard")
    print("Then browse",result["dashboard_url"],"(accept the local self-signed certificate).")
    if result["schwab_configured"]:
        print("For Schwab OAuth: run the interactive manual-flow command in INSTALL.md.")
        print("Authorization never asks the installer for your Schwab username or password.")
    else:print("Schwab not configured; paper-only dashboard is available.")
if __name__=="__main__":
    try:main()
    except (ValueError,FileExistsError,subprocess.CalledProcessError,OSError) as exc:
        print("Setup stopped:",exc,file=sys.stderr);raise SystemExit(2)
