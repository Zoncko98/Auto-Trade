"""Interactive Ollama model discovery and optional install on a private-LAN host.

Uses Ollama's documented /api/tags and /api/pull endpoints. The selected
model downloads to the remote Ollama computer, not to TrueNAS.
"""
import argparse,json,sys
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import ipaddress

OPTIONS=[
 ("qwen3.5:4b","Balanced small chat model"),
 ("qwen3-vl:2b","Small vision-capable model"),
 ("qwen3-vl:8b","Larger vision model; more RAM/VRAM"),
 ("deepseek-r1:8b","Reasoning model; more RAM"),
]
def checked_url(value):
    p=urlparse(value)
    if p.scheme not in ("http","https") or not p.hostname or not p.port or p.username or p.password or p.path not in ("","/") or p.query or p.fragment:
        raise ValueError("Use http(s)://private-LAN-IP:11434")
    try:ip=ipaddress.ip_address(p.hostname)
    except ValueError:raise ValueError("Numeric private LAN IP required") from None
    if not (ip.is_private or ip.is_loopback):raise ValueError("Only private/local Ollama supported")
    return value.rstrip("/")

def tags(base,opener=urlopen):
    url=checked_url(base)
    with opener(Request(url+"/api/tags"),timeout=6) as res:
        document=json.loads(res.read(300000))
    return [x["name"] for x in document.get("models",[])
            if isinstance(x,dict) and isinstance(x.get("name"),str)]

def pull(base,model,opener=urlopen):
    url=checked_url(base)
    allow={name for name,_ in OPTIONS}
    if model not in allow:raise ValueError("Choose a listed model")
    req=Request(url+"/api/pull",data=json.dumps({"name":model,"stream":False}).encode(),
                headers={"Content-Type":"application/json"},method="POST")
    with opener(req,timeout=1200) as res:
        data=json.loads(res.read(16384))
    if data.get("status")!="success":raise RuntimeError("Ollama pull did not finish successfully")
    return True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",required=True)
    parser.add_argument("--list",action="store_true")
    parser.add_argument("--model",choices=[v[0] for v in OPTIONS])
    args=parser.parse_args()
    if args.list:
        print("Installed models:",", ".join(tags(args.url)) or "(none)")
        for i,(model,desc) in enumerate(OPTIONS,1):print(f"{i}. {model}: {desc}")
    elif args.model:
        print("Requesting model",args.model,"on",args.url)
        pull(args.url,args.model)
        print("Installed:",args.model)
    else:parser.print_help()

if __name__=="__main__":
    try:main()
    except (ValueError,RuntimeError,HTTPError,URLError,TimeoutError,OSError) as ex:
        print("Ollama installer:",str(ex),file=sys.stderr);sys.exit(2)
