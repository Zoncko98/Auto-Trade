"""One-time, interactive Schwab authorization inside the optional live-worker container.

The user signs into Schwab only in their own browser. This program never asks
for a Schwab username or password and never enables live trading.
"""
from pathlib import Path
import os,sys
from urllib.parse import urlparse

def read_config(path):
    values={}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            if "=" not in line:raise ValueError("Malformed Schwab app configuration")
            key,value=line.split("=",1)
            if key not in ("SCHWAB_APP_KEY","SCHWAB_APP_SECRET","SCHWAB_CALLBACK_URL"):raise ValueError("Unexpected Schwab setting")
            values[key]=value.strip()
    return values

def main():
    config=read_config(os.environ.get("SCHWAB_ENV_FILE","/run/secrets/schwab.env"))
    key=config.get("SCHWAB_APP_KEY")
    secret=config.get("SCHWAB_APP_SECRET")
    callback=config.get("SCHWAB_CALLBACK_URL")
    if not key or not secret:raise ValueError("Configure your Schwab developer key and secret first")
    url=urlparse(callback or "")
    if url.scheme!="https" or url.hostname!="127.0.0.1" or not (1024<=int(url.port or 0)<=65535):
        raise ValueError("Schwab callback must be the same registered loopback HTTPS callback")
    token=Path(os.environ.get("SCHWAB_TOKEN_FILE","/state/schwab_token.json"))
    if token.exists() and token.stat().st_size>0:
        print("A nonempty token already exists; refusing to replace it automatically.")
        print("Use the separate reauthorization procedure after backing up your token.")
        return
    print("Follow Schwab's authorization link in your own browser.")
    print("Sign in ONLY on Schwab's website, then paste the final redirected URL here.")
    print("This setup NEVER starts the trading worker or sends orders.")
    from schwab.auth import client_from_manual_flow
    client_from_manual_flow(key,secret,callback,str(token),enforce_enums=True)
    token.chmod(0o600)
    if not token.is_file() or token.stat().st_size==0:
        raise RuntimeError("No Schwab token was created")
    print("Schwab OAuth token stored privately. Live trading is still disabled.")

if __name__=="__main__":
    try:main()
    except (ValueError,RuntimeError,OSError) as exc:
        print("Schwab setup stopped:",str(exc),file=sys.stderr)
        raise SystemExit(2)
