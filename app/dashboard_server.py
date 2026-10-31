"""Authenticated LAN dashboard for the PAPER-ONLY TrueNAS bot.

No Docker socket, broker credentials, or TrueNAS administrator privileges.
Control commands are validated and written to a shared JSON document.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import http.cookies
import json
import os
import secrets
import ssl
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError

from live_dashboard import (installed_models, current_model, set_model,
    live_state, set_operator_mode)
from live_extension import (read_live_risk,set_live_risk,validate_risk,read_decisions,
                            rows_from_live,excel_export)
from dashboard_control import (
    MODES, checked_control, default_control, now_utc, read_control,
    validated_settings, write_atomic,
)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "web"
STATE_DIR = Path(os.environ.get("STATE_DIR", "/state"))
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "").encode()
INITIAL_CAPITAL = float(os.environ.get("PAPER_INITIAL_CAPITAL", "100"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
BIND_ADDRESS = os.environ.get("DASHBOARD_BIND", "0.0.0.0")
_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}


def _safe_load(path: Path, default):
    try:
        if not path.exists():
            return default
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("State file too large")
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, TypeError, UnicodeError):
        return default


def _state():
    account = _safe_load(STATE_DIR / "paper_account.json", None)
    is_initialized = isinstance(account, dict) and account.get("schema") == 1
    account = account if is_initialized else {}
    cash = float(account.get("cash", INITIAL_CAPITAL))
    reserved = float(account.get("reserved_profit", 0))
    positions = []
    unrealized = 0.0
    for symbol, pos in account.get("positions", {}).items():
        history = account.get("history", {}).get(symbol, [])
        entry = float(pos.get("entry_price", 0))
        quantity = float(pos.get("quantity", 0))
        last_price = float(history[-1]["price"]) if history else entry
        pnl = round((last_price - entry) * quantity, 2)
        unrealized += pnl
        positions.append({
            "symbol": symbol, "quantity": quantity, "entry_price": entry,
            "last_price": last_price, "market_value": round(quantity * last_price, 2),
            "unrealized_pnl": pnl,
        })
    equity = round(cash + reserved + sum(p["market_value"] for p in positions), 2)
    trades = account.get("trades", [])
    realized = round(sum(float(t.get("realized_pnl", 0)) for t in trades
                         if isinstance(t, dict)), 2)
    return {
        "initialized": is_initialized, "cash": round(cash, 2),
        "reserved_profit": round(reserved, 2), "equity": equity,
        "realized_pnl": realized, "unrealized_pnl": round(unrealized, 2),
        "positions": positions, "trade_count": len(trades),
        "review_count": len(account.get("reviews", [])),
        "day_halted": bool(account.get("halted", False)),
        "daily_target_reached": bool(account.get("daily_target_reached", False)),
        "day_start_equity": float(account.get("day_start_equity", INITIAL_CAPITAL)),
    }


def _runtime():
    runtime = _safe_load(STATE_DIR / "runtime_status.json", {})
    if not isinstance(runtime, dict):
        runtime = {}
    updated = runtime.get("updated_at", "")
    age = None
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        age = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    except (ValueError, TypeError):
        pass
    # Runtime heartbeat is written at most every 30 seconds by default.
    runtime["online"] = age is not None and age < 120
    runtime["heartbeat_age_sec"] = age
    return runtime


def _last_jsonl(path: Path, maximum: int = 400):
    # Limit both memory and output size for the dashboard.
    if not path.exists():
        return []
    items = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(line) > 8192:
                    continue
                try:
                    items.append(json.loads(line))
                    if len(items) > maximum:
                        items.pop(0)
                except ValueError:
                    continue
    except (OSError, UnicodeError):
        return []
    return items


def _page_of(items, params):
    page = max(1, min(100000, int(params.get("page", ["1"])[0])))
    page_size = max(1, min(100, int(params.get("limit", ["25"])[0])))
    items = items if isinstance(items, list) else []
    total = len(items)
    start = (page - 1) * page_size
    return {"items": list(reversed(items[max(0, total-start-page_size):max(0, total-start)])),
            "total": total, "page": page, "limit": page_size}


def _session_value():
    expiry = int(time.time()) + 8 * 3600
    nonce = secrets.token_urlsafe(24)
    message = f"{expiry}:{nonce}".encode()
    raw = base64.urlsafe_b64encode(message).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}", nonce


def _verify_session(value):
    try:
        raw, sig = value.split(".", 1)
        expected = hmac.new(SESSION_SECRET, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        message = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        expiry_s, nonce = message.decode().split(":", 1)
        if int(expiry_s) < time.time():
            return None
        return nonce if 16 <= len(nonce) <= 96 else None
    except (ValueError, UnicodeError, OverflowError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TradePilot/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Never log cookies, passwords, POST bodies or query strings.
        print(f"dashboard [{self.client_address[0]}] {fmt % args}", flush=True)

    def _headers(self, status, content_type, length, more=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")
        # Do not enforce HSTS with an untrusted self-signed LAN certificate.
        if more:
            for k, v in more.items():
                self.send_header(k, v)
        self.end_headers()

    def _json(self, status, obj, more=None):
        data = json.dumps(obj, allow_nan=False, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(data), more)
        self.wfile.write(data)

    def _excel(self,filename,data):
        self._headers(200,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            len(data),{"Content-Disposition":'attachment; filename="'+filename+'"'})
        self.wfile.write(data)

    def _body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Expected application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if not 1 <= length <= 4096:
            raise ValueError("Request too large or empty")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def _nonce(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            session = cookie.get("session")
            return _verify_session(session.value) if session else None
        except (http.cookies.CookieError, ValueError):
            return None

    def _csrf_ok(self):
        nonce = self._nonce()
        csrf = self.headers.get("X-CSRF-Token", "")
        expected = hmac.new(SESSION_SECRET, (nonce or "").encode(), hashlib.sha256).hexdigest()
        return bool(nonce) and hmac.compare_digest(expected, csrf)

    def _same_origin(self):
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        try:
            parsed = urlparse(origin)
            return parsed.scheme == "https" and parsed.netloc == host
        except ValueError:
            return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"status": "ok", "live_worker_separate": True})
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/local.js": ("local.js", "text/javascript; charset=utf-8"),
            "/forecast.js": ("forecast.js", "text/javascript; charset=utf-8"),
            "/app.css": ("app.css", "text/css; charset=utf-8"),
        }
        if path in assets:
            name, content_type = assets[path]
            try:
                data = (STATIC_DIR / name).read_bytes()
            except OSError:
                return self._json(500, {"error": "Static asset missing"})
            self._headers(200, content_type, len(data))
            return self.wfile.write(data)
        if not path.startswith("/api/"):
            return self._json(404, {"error": "Not found"})
        nonce = self._nonce()
        if path == "/api/session":
            if not nonce:
                return self._json(401, {"authenticated": False})
            csrf = hmac.new(SESSION_SECRET, nonce.encode(), hashlib.sha256).hexdigest()
            return self._json(200, {"authenticated": True, "csrf": csrf})
        if not nonce:
            return self._json(401, {"error": "Sign in required"})
        try:
            if path in ("/api/research/forecast","/api/research/models"):
                target = "/api/forecast" if path.endswith("forecast") else "/api/models"
                try:
                    forecast_url=os.getenv("FORECAST_API_URL","").rstrip("/")
                    if not forecast_url:return self._json(503,{"error":"Forecast service not configured"})
                    parsed=urlparse(forecast_url)
                    if parsed.scheme not in ("http","https") or not parsed.hostname or not parsed.port or parsed.path not in ("","/") or parsed.username or parsed.password:
                        raise ValueError("Invalid forecast endpoint")
                    from ipaddress import ip_address
                    try:
                        permitted=ip_address(parsed.hostname).is_private
                    except ValueError:
                        permitted=False
                    if not permitted:raise ValueError("Forecast service must use private LAN IP")
                    req=Request(forecast_url+target,headers={"Accept":"application/json"})
                    with urlopen(req,timeout=9) as response:
                        body=response.read(350001)
                    if len(body)>350000:
                        raise ValueError("Research response too large")
                    doc=json.loads(body)
                    if not isinstance(doc,dict):
                        raise ValueError("Invalid research data")
                except (URLError,TimeoutError,OSError,ValueError,TypeError):
                    return self._json(503,{"error":"AI workstation research service unavailable"})
                return self._json(200,doc)
            if path == "/api/live":
                return self._json(200, live_state(STATE_DIR))
            if path == "/api/live/risk":
                return self._json(200,read_live_risk(STATE_DIR))
            if path == "/api/live/decisions":
                return self._json(200,{"items":read_decisions(STATE_DIR,150)})
            if path in ("/api/live/export.xlsx","/api/paper/export.xlsx"):
                query=parse_qs(urlparse(self.path).query)
                if set(query)-{"index"}:
                    return self._json(400,{"error":"Unknown export filter"})
                one=None
                if "index" in query:
                    val=query["index"][0]
                    if not val.isdigit() or len(val)>6:
                        return self._json(400,{"error":"Invalid trade export index"})
                    one=int(val)
                if path.startswith("/api/live/"):
                    journal=_safe_load(STATE_DIR/"live"/"orders.json",{})
                    rows=rows_from_live(journal)
                    decisions=read_decisions(STATE_DIR,200)
                    kind="Live"
                else:
                    paper=_safe_load(STATE_DIR/"paper_account.json",{})
                    rows=[]
                    for i,t in enumerate(paper.get("trades",[])[:10000]):
                        if not isinstance(t,dict):continue
                        qty=t.get("quantity")
                        price=t.get("price")
                        rows.append({"index":i,"created_at":t.get("timestamp"),
                            "symbol":t.get("symbol"),"action":t.get("action"),
                            "quantity":qty,"limit_price":price,
                            "filled_price":price,
                            "filled_notional":round(float(qty)*float(price),4)
                                              if isinstance(qty,(int,float)) and isinstance(price,(int,float)) else None,
                            "gross_realized_pnl":t.get("realized_pnl") if t.get("action")=="PAPER_SELL" else None,
                            "state":"SIMULATED","order_id":"",
                            "reason":str(t.get("reason",""))[:1000],
                            "candle":None})
                    decisions=[{"at":r.get("timestamp"),"symbol":r.get("symbol"),
                        "decision":"APPROVED" if r.get("approved") else "REJECTED",
                        "model":r.get("model"),
                        "summary":r.get("reason"),"signals":r.get("risk_flags",[])}
                        for r in paper.get("reviews",[]) if isinstance(r,dict)]
                    kind="Paper"
                try:
                    content=excel_export(kind,rows,decisions,one)
                except LookupError:
                    return self._json(404,{"error":"Trade not found"})
                filename="autotrader-"+kind.lower()+"-trades.xlsx" if one is None else "autotrader-"+kind.lower()+"-trade-"+str(one)+".xlsx"
                return self._excel(filename,content)
            if path == "/api/local/models":
                try:
                    models=installed_models()
                except ValueError as exc:
                    return self._json(503, {"error":str(exc)})
                return self._json(200, {
                    "models":models,"selected":current_model(STATE_DIR),
                    "source":"Installed Ollama models on TrueNAS",
                })
            if path == "/api/status":
                try:
                    control = read_control(STATE_DIR / "control.json")
                except (OSError, ValueError, KeyError, TypeError):
                    control = default_control()
                    control["error"] = "Invalid control file: trading will fail closed"
                return self._json(200, {
                    "control": control, "runtime": _runtime(), "account": _state(),
                    "paper_only": True, "market_data_connected": False,
                })
            if path in ("/api/trades", "/api/reviews"):
                data = _safe_load(STATE_DIR / "paper_account.json", {})
                field = "trades" if path.endswith("trades") else "reviews"
                params = parse_qs(urlparse(self.path).query)
                return self._json(200, _page_of(data.get(field, []), params))
            if path == "/api/performance":
                return self._json(200, {"points": _last_jsonl(STATE_DIR / "performance.jsonl", 250)})
            if path == "/api/audit":
                return self._json(200, {"events": _last_jsonl(STATE_DIR / "settings_audit.jsonl", 100)})
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            return self._json(400, {"error": str(exc)[:150]})
        return self._json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._same_origin():
            return self._json(403, {"error": "Origin not allowed"})
        if path == "/api/login":
            ip = self.client_address[0]
            with _lock:
                now = time.monotonic()
                history = [t for t in _login_attempts.get(ip, []) if now - t < 900]
                if len(history) >= 5:
                    return self._json(429, {"error": "Too many attempts; retry later"})
            try:
                data = self._body()
                password = data.get("password", "")
                if not isinstance(password, str) or not hmac.compare_digest(password, PASSWORD):
                    with _lock:
                        _login_attempts[ip] = history + [time.monotonic()]
                    return self._json(401, {"error": "Invalid password"})
            except (ValueError, TypeError):
                return self._json(400, {"error": "Invalid login request"})
            with _lock:
                _login_attempts.pop(ip, None)
            cookie, nonce = _session_value()
            csrf = hmac.new(SESSION_SECRET, nonce.encode(), hashlib.sha256).hexdigest()
            return self._json(200, {"ok": True, "csrf": csrf}, {
                "Set-Cookie": f"session={cookie}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800",
            })
        if path == "/api/logout":
            if not self._csrf_ok():
                return self._json(403, {"error": "Invalid session or CSRF token"})
            return self._json(200, {"ok": True}, {
                "Set-Cookie": "session=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
            })
        if not self._csrf_ok():
            return self._json(403, {"error": "Invalid session or CSRF token"})
        if path == "/api/live/risk":
            try:
                payload=self._body()
                if set(payload)!={"revision","settings"}:
                    raise ValueError("Expected revision and risk settings")
                outcome=set_live_risk(STATE_DIR,payload["revision"],
                                      payload["settings"],write_atomic)
                return self._json(200,{"ok":True,"risk":outcome})
            except RuntimeError as exc:
                return self._json(409,{"error":str(exc)[:160]})
            except (ValueError,TypeError,KeyError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
        if path == "/api/local/model":
            try:
                data=self._body()
                if set(data)!={"model"}:
                    raise ValueError("Expected a model selection")
                models=installed_models()
                result=set_model(STATE_DIR,data["model"],models,write_atomic)
                return self._json(200,{"ok":True,"selection":result})
            except (ValueError,TypeError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
        if path == "/api/live/mode":
            try:
                data=self._body()
                if set(data)!={"mode"}:
                    raise ValueError("Expected an order permission mode")
                live=live_state(STATE_DIR)
                if not live["worker_online"] or not live["armed"]:
                    raise ValueError("The live Schwab worker is not active")
                result=set_operator_mode(STATE_DIR,data["mode"],write_atomic)
                return self._json(200,{"ok":True,"operator":result})
            except (ValueError,TypeError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
        if path not in ("/api/mode", "/api/settings"):
            return self._json(404, {"error": "Unknown endpoint"})
        try:
            body = self._body()
            revision = body.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool):
                raise ValueError("Expected a control revision")
            target = body.get("mode") if path == "/api/mode" else validated_settings(body.get("settings"))
            if path == "/api/mode" and target not in MODES:
                raise ValueError("Mode must be running, paused, or stopped")

            with _lock:
                # Interprocess lock prevents concurrent API writers from losing updates.
                lock_file = STATE_DIR / "control.lock"
                with lock_file.open("a+") as locked:
                    fcntl.flock(locked, fcntl.LOCK_EX)
                    try:
                        current = read_control(STATE_DIR / "control.json")
                        if revision != current["revision"]:
                            return self._json(409, {"error": "Settings changed; refresh and retry"})
                        proposed = dict(current)
                        if path == "/api/mode":
                            proposed["mode"] = target
                        else:
                            proposed["settings"] = target
                        proposed["revision"] = revision + 1
                        proposed["updated_at"] = now_utc()
                        checked_control(proposed)
                        write_atomic(STATE_DIR / "control.json", proposed)
                        with (STATE_DIR / "settings_audit.jsonl").open("a") as audit:
                            event = {
                                "timestamp": proposed["updated_at"],
                                "action": "mode_change" if path == "/api/mode" else "settings_change",
                                "revision": proposed["revision"],
                                "new_mode": proposed["mode"],
                                "settings": proposed["settings"],
                            }
                            audit.write(json.dumps(event, allow_nan=False) + "\n")
                            audit.flush()
                            os.fsync(audit.fileno())
                    finally:
                        fcntl.flock(locked, fcntl.LOCK_UN)
            return self._json(200, {"ok": True, "control": proposed})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return self._json(400, {"error": str(exc)[:160]})


def main():
    if len(PASSWORD) < 20 or len(SESSION_SECRET) < 32:
        raise SystemExit("Dashboard secrets must be configured; startup refused")
    if not (INITIAL_CAPITAL > 0 and INITIAL_CAPITAL < 1000000):
        raise SystemExit("Invalid paper initial capital")
    cert = os.environ.get("DASHBOARD_TLS_CERT", "/tls/cert.pem")
    key = os.environ.get("DASHBOARD_TLS_KEY", "/tls/key.pem")
    if not Path(cert).is_file() or not Path(key).is_file():
        raise SystemExit("HTTPS certificate and key are required")
    if not STATE_DIR.is_dir():
        raise SystemExit("STATE_DIR missing")
    httpd = ThreadingHTTPServer((BIND_ADDRESS, PORT), Handler)
    httpd.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert, keyfile=key)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    print(f"TradePilot dashboard HTTPS ready on {BIND_ADDRESS}:{PORT}", flush=True)
    httpd.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
