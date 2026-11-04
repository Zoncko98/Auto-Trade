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
from collections import deque
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
from profile_auth import verify as verify_profile_password, rotate as rotate_profile_password, revision as profile_revision, ProfileError
from update_status import update_information, public_update_information, installed_version
from broker_market_data import read_snapshot as broker_market_snapshot
from broker_workspace import (workspace_summary as broker_workspace_summary,
                              robinhood_status, robinhood_portfolio,
                              resolve_robinhood_orphan, install_robinhood_credentials)
from ai_readiness import (summary as ai_readiness_summary,
    verify_ollama_model, effective_selected_model)
from forecast_engine import (forecast as selected_forecast,
    connection as selected_forecast_connection, models as selected_forecast_models)
from forecast_connection import (
    ForecastConnectionError, connection_status as forecast_connection_status,
    research_doc as forecast_research_doc, probe as forecast_probe,
    resolve_url as forecast_resolve_url)
from unified_config import (configured as app_configured, initialize as initialize_app,
    credentials as app_credentials,
    public_summary as integration_summary, save as save_integrations,
    pairing_code as pairing_code_for_setup, settings as integration_settings,
    username as profile_username, SetupError)
from live_access import toggle as toggle_live_access
from schwab_web_oauth import (begin as begin_schwab_auth,
    finish as finish_schwab_auth, accounts as schwab_accounts)
from dashboard_control import (
    MODES, checked_control, default_control, now_utc, read_control,
    validated_settings, write_atomic,
)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(os.environ.get("DASHBOARD_STATIC_DIR",str(APP_DIR / "web")))
STATE_DIR = Path(os.environ.get("STATE_DIR", "/state"))
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "").encode()
INITIAL_CAPITAL = float(os.environ.get("PAPER_INITIAL_CAPITAL", "100"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
BIND_ADDRESS = os.environ.get("DASHBOARD_BIND", "0.0.0.0")
_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
_change_attempts: dict[str, list[float]] = {}
_setup_attempts: dict[str, list[float]] = {}
UNIFIED_APP = os.environ.get("AUTO_UNIFIED_APP","false").lower() == "true"


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



def _performance_points(path: Path, days: int, maximum: int = 1200):
    """Read a bounded, date-filtered tail without loading the entire history."""
    from datetime import timedelta
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    points = deque(maxlen=maximum)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(line) > 8192:
                    continue
                try:
                    point = json.loads(line)
                    if not isinstance(point, dict) or isinstance(point.get("equity"), bool):
                        continue
                    equity = float(point["equity"])
                    if not (float("-inf") < equity < float("inf")):
                        continue
                    timestamp = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        continue
                    if cutoff and timestamp < cutoff:
                        continue
                    points.append({"timestamp": timestamp.isoformat(), "equity": equity})
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
    except (OSError, UnicodeError):
        return []
    return list(points)


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
    message = f"{expiry}:{profile_revision(STATE_DIR)}:{nonce}".encode()
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
        expiry_s,rev_s,nonce = message.decode().split(":", 2)
        if int(expiry_s) < time.time() or int(rev_s)!=profile_revision(STATE_DIR):
            return None
        return nonce if 16 <= len(nonce) <= 96 else None
    except (ValueError, UnicodeError, OverflowError, OSError, ProfileError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TradePilot/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Schwab OAuth codes can appear in callback query strings. Never log
        # client-supplied URLs, POST bodies, cookies, or provider credentials.
        print(f"dashboard [{self.client_address[0]}] {self.command} request", flush=True)

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
            return self._json(200, {"status":"ok","unified":UNIFIED_APP,
                "setup_complete":(app_configured(STATE_DIR) if UNIFIED_APP else True)})
        if UNIFIED_APP and path == "/api/setup/status":
            return self._json(200,{"setup_needed":not app_configured(STATE_DIR)})
        if UNIFIED_APP and path == "/schwab/callback":
            # The callback may be a cross-site browser navigation from Schwab,
            # so it authenticates with OAuth state, not the SameSite cookie.
            # Only serve callbacks matching the exact registered LAN URL.
            configured_url=integration_settings(STATE_DIR).get("schwab_callback_url","")
            expected=urlparse(configured_url)
            if expected.hostname=="127.0.0.1" or expected.path!="/schwab/callback" or self.headers.get("Host","")!=expected.netloc:
                return self._json(404,{"error":"This is not the registered Schwab callback"})
            try:
                finish_schwab_auth(STATE_DIR,"https://"+expected.netloc+self.path)
                html=b"<!doctype html><title>Schwab connected</title><h1>Schwab account connected</h1><p>Return to your Auto Trader dashboard. Live trading remains OFF until you enable it.</p>"
                self._headers(200,"text/html; charset=utf-8",len(html))
                return self.wfile.write(html)
            except Exception:
                html=b"<!doctype html><title>Schwab connection incomplete</title><h1>Schwab connection was not completed</h1><p>Return to Auto Trader, check the registered callback URL and try again.</p>"
                self._headers(400,"text/html; charset=utf-8",len(html))
                return self.wfile.write(html)
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/setup.html": ("setup.html","text/html; charset=utf-8"),
            "/setup.js": ("setup.js","text/javascript; charset=utf-8"),
            "/integrations.html": ("integrations.html","text/html; charset=utf-8"),
            "/broker-schwab.html": ("broker-schwab.html","text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/ui-audit.js": ("ui-audit.js", "text/javascript; charset=utf-8"),
            "/local.js": ("local.js", "text/javascript; charset=utf-8"),
            "/forecast.js": ("forecast.js", "text/javascript; charset=utf-8"),
            "/brokers.js": ("brokers.js","text/javascript; charset=utf-8"),
            "/app.css": ("app.css", "text/css; charset=utf-8"),
            "/workspace.css": ("workspace.css", "text/css; charset=utf-8"),
            "/assets/brands/alpaca-official-light.png": ("assets/brands/alpaca-official-light.png", "image/png"),
        }
        if path in assets:
            name, content_type = assets[path]
            if UNIFIED_APP and not app_configured(STATE_DIR) and path in ("/","/index.html"):
                name="setup.html"
            if path in ("/integrations.html","/broker-schwab.html") and not self._nonce():
                return self._json(401,{"error":"Sign in required"})
            if path=="/setup.html" and (not UNIFIED_APP or app_configured(STATE_DIR)):
                return self._json(404,{"error":"Setup is unavailable"})
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
            if UNIFIED_APP and path == "/api/ai/readiness":
                cfg=integration_settings(STATE_DIR)
                model=effective_selected_model(cfg,STATE_DIR)
                # The shared model selection overrides the installation
                # default in local_ai_gateway; report what workers actually use.
                result=ai_readiness_summary({**cfg,"ai_model":model})
                result["model"]=model
                if cfg.get("ai_provider")=="ollama" and cfg.get("ollama_url"):
                    result.update(verify_ollama_model(cfg["ollama_url"],model))
                return self._json(200,result)
            if UNIFIED_APP and path == "/api/profile/webull-margin":
                from webull_account_preferences import read
                try:
                    setting=read(STATE_DIR)
                    return self._json(200,dict(setting,
                        live_orders_enabled=False,
                        margin_borrowing_enabled=False))
                except (ValueError,OSError):
                    return self._json(503,{"error":"Webull margin preference unavailable"})
            if UNIFIED_APP and path == "/api/webull/trader":
                from webull_trade_config import read
                from webull_risk import read as read_risk
                from webull_journal import WebullJournal
                policy=read(STATE_DIR)
                risk=read_risk(STATE_DIR)
                try:
                    worker=json.loads((Path(STATE_DIR)/"webull"/"worker_status.json").read_text())
                    if not isinstance(worker,dict):worker={}
                except (OSError,ValueError,TypeError):worker={}
                try:
                    journal=WebullJournal(STATE_DIR)
                    orders=journal.recent(30)
                except (OSError,ValueError,TypeError):orders=[]
                from webull_trade_config import LIVE_EXECUTION_VERIFIED
                from webull_account_preferences import read as read_webull_account_preferences
                from webull_worker import account_readiness
                allow_margin=read_webull_account_preferences(STATE_DIR)["allow_margin_accounts"]
                if isinstance(worker.get("broker_accounts"),list):
                    worker["account_readiness"]=[
                        account_readiness(a,allow_margin) for a in worker["broker_accounts"]
                        if isinstance(a,dict) and isinstance(a.get("account_id"),str)]
                from webull_streaming import feed_status
                return self._json(200,{"policy":policy,"risk":risk,
                    "worker":worker,"stream_status":feed_status(STATE_DIR),"orders":orders,
                    "execution_validated":LIVE_EXECUTION_VERIFIED,
                    "activation_available":risk.get("saved") is True,
                    "execution_enabled":policy.get("enabled") is True,
                    "operator_authorized_unvalidated":policy.get("enabled") is True and not LIVE_EXECUTION_VERIFIED})
            if UNIFIED_APP and path == "/api/webull/evidence":
                try:
                    evidence=json.loads((Path(STATE_DIR)/"webull"/"decision_history.json").read_text())
                    if not isinstance(evidence,list):evidence=[]
                except (OSError,ValueError,TypeError):evidence=[]
                return self._json(200,{"items":evidence[-40:][::-1]})
            if UNIFIED_APP and path == "/api/webull/risk":
                from webull_risk import read
                try:return self._json(200,read(STATE_DIR))
                except (OSError,ValueError):return self._json(503,{"error":"Webull risk plan unavailable"})
            if UNIFIED_APP and path == "/api/webull/status":
                from webull_openapi import status
                return self._json(200,status(STATE_DIR))
            if UNIFIED_APP and path == "/api/webull/portfolio":
                from webull_openapi import portfolio,WebullError
                account_id=parse_qs(urlparse(self.path).query).get("account_id",[""])[0]
                try:return self._json(200,portfolio(STATE_DIR,account_id))
                except (WebullError,OSError,ValueError) as exc:
                    return self._json(503,{"error":str(exc)[:160]})
            if UNIFIED_APP and path == "/api/robinhood/status":
                return self._json(200,robinhood_status(STATE_DIR))
            if UNIFIED_APP and path == "/api/robinhood/risk":
                from robinhood_policy import read_policy,PolicyError
                try:return self._json(200,read_policy(STATE_DIR))
                except PolicyError as exc:return self._json(503,{"error":str(exc)})
            if UNIFIED_APP and path == "/api/robinhood/portfolio":
                return self._json(200,robinhood_portfolio(STATE_DIR))
            if UNIFIED_APP and path == "/api/brokers":
                return self._json(200,broker_workspace_summary(STATE_DIR))
            if UNIFIED_APP and path == "/api/integrations":
                return self._json(200,integration_summary(STATE_DIR))
            if UNIFIED_APP and path == "/api/schwab/accounts":
                try:
                    return self._json(200,schwab_accounts(STATE_DIR))
                except (SetupError,ValueError,OSError) as exc:
                    return self._json(503,{"error":str(exc)[:120]})
                except Exception:
                    return self._json(503,{"error":"Schwab broker account lookup unavailable"})
            if path == "/api/profile":
                return self._json(200, {"display_name":(profile_username(STATE_DIR)
                    if UNIFIED_APP else "Administrator"),
                    "password_change_enabled":True,"version":installed_version(APP_DIR)})
            if path == "/api/update":
                return self._json(200,(public_update_information(APP_DIR)
                    if UNIFIED_APP else update_information(STATE_DIR,APP_DIR)))
            if path == "/api/research/market":
                return self._json(200,broker_market_snapshot(STATE_DIR/"live"))
            if UNIFIED_APP and path=="/api/research/forecast/connection":
                return self._json(200,selected_forecast_connection(integration_settings(STATE_DIR)))
            if UNIFIED_APP and path in ("/api/research/forecast","/api/research/models"):
                cfg=integration_settings(STATE_DIR)
                if path.endswith("models"):
                    return self._json(200,selected_forecast_models(STATE_DIR,cfg,app_credentials(STATE_DIR)))
                return self._json(200,selected_forecast(STATE_DIR,cfg,app_credentials(STATE_DIR)))
            if path in ("/api/research/forecast","/api/research/models"):
                # Historical split-container compatibility. New installs use
                # the private-LAN research connector above.
                target="/api/forecast" if path.endswith("forecast") else "/api/models"
                try:
                    url=os.getenv("FORECAST_API_URL","").rstrip("/")
                    return self._json(200,forecast_research_doc({"forecast_url":url},target))
                except ForecastConnectionError:
                    return self._json(503,{"error":"Research workstation unavailable"})
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
                params = parse_qs(urlparse(self.path).query)
                days = int(params.get("days", ["1"])[0])
                if days not in (0, 1, 7, 30, 90, 365):
                    return self._json(400, {"error": "Unsupported performance range"})
                return self._json(200, {"points": _performance_points(STATE_DIR / "performance.jsonl", days), "days": days, "source": "paper"})
            if path == "/api/audit":
                return self._json(200, {"events": _last_jsonl(STATE_DIR / "settings_audit.jsonl", 100)})
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            return self._json(400, {"error": str(exc)[:150]})
        return self._json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._same_origin():
            return self._json(403, {"error": "Origin not allowed"})
        if UNIFIED_APP and path == "/api/setup/initialize":
            ip=self.client_address[0]
            with _lock:
                now=time.monotonic()
                tries=[t for t in _setup_attempts.get(ip,[]) if now-t<900]
                if len(tries)>=5:
                    return self._json(429,{"error":"Too many pairing attempts"})
                _setup_attempts[ip]=tries+[now]
            try:
                data=self._body()
                code=data.pop("setup_code","")
                password=data.pop("admin_password","")
                user=data.pop("admin_username","")
                initialize_app(STATE_DIR,code,password,data,PASSWORD,admin_username=user)
                with _lock:_setup_attempts.pop(ip,None)
                return self._json(200,{"ok":True,"message":"Administrator account created"})
            except (SetupError,ValueError,OSError,TypeError,ProfileError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
        if path == "/api/login":
            if UNIFIED_APP and not app_configured(STATE_DIR):
                return self._json(409,{"error":"Complete the first-run setup before signing in"})
            ip = self.client_address[0]
            with _lock:
                now = time.monotonic()
                history = [t for t in _login_attempts.get(ip, []) if now - t < 900]
                if len(history) >= 5:
                    return self._json(429, {"error": "Too many attempts; retry later"})
            try:
                data = self._body()
                password = data.get("password", "")
                if UNIFIED_APP and data.get("username")!=profile_username(STATE_DIR):
                    with _lock:_login_attempts[ip]=history+[time.monotonic()]
                    return self._json(401,{"error":"Invalid username or password"})
                if not isinstance(password, str) or len(password)>1024:
                    return self._json(400, {"error": "Invalid login request"})
                try:
                    authorized=verify_profile_password(STATE_DIR,password,PASSWORD)
                except (ProfileError,OSError):
                    return self._json(503, {"error": "Protected authentication state unavailable"})
                if not authorized:
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
        if UNIFIED_APP and path == "/api/profile/webull-margin":
            from webull_account_preferences import read,save,PreferenceError
            try:
                setting=save(STATE_DIR,self._body())
                if setting["allow_margin_accounts"] is False:
                    from webull_trade_config import disarm
                    disarm(STATE_DIR)
                return self._json(200,dict(setting,
                    live_orders_enabled=False,margin_borrowing_enabled=False))
            except (PreferenceError,ValueError,TypeError,OSError):
                return self._json(400,{"error":"Invalid Webull margin-account preference"})
        if UNIFIED_APP and path == "/api/webull/trader":
            from webull_trade_config import save,WebullPolicyError
            from webull_broker import WebullBroker,WebullError
            from webull_journal import WebullJournal
            from webull_worker import _can_trade_account
            from webull_account_preferences import read as webull_account_preferences
            try:
                request=self._body()
                # When pausing, do not require reachable broker (kill-switch).
                if isinstance(request,dict) and isinstance(request.get("policy"),dict) and request["policy"].get("enabled") is False:
                    return self._json(200,save(STATE_DIR,request["policy"],[]))
                broker=WebullBroker(STATE_DIR)
                if broker.environment!="production":
                    raise WebullPolicyError("Production Webull connection required for live execution")
                accounts=broker.accounts()
                policy=request.get("policy") if isinstance(request,dict) else None
                if not isinstance(policy,dict):raise WebullPolicyError("Missing trade policy")
                selected=[("stock_account","trade_stocks","EQUITY"),
                          ("crypto_account","trade_crypto","CRYPTO")]
                for id_key,flag,asset in selected:
                    if policy.get(flag):
                        row=next((r for r in accounts if r.get("account_id")==policy.get(id_key)),None)
                        allow_margin=webull_account_preferences(STATE_DIR)["allow_margin_accounts"]
                        if row is None or not _can_trade_account(row,asset,allow_margin):
                            raise WebullPolicyError("Selected Webull cash account/asset class not verified")
                        if WebullJournal(STATE_DIR).pending(policy[id_key]):
                            raise WebullPolicyError("Unresolved Webull order intent")
                        if broker.open_orders(policy[id_key]):
                            raise WebullPolicyError("Existing broker open orders prevent arming")
                        b=broker.balance(policy[id_key])
                        if asset=="EQUITY" and "MARGIN" in str(
                               row.get("account_class") or row.get("account_type") or "").upper():
                            from webull_worker import verify_margin_cash_funding
                            if verify_margin_cash_funding(b)<=0:
                                raise WebullPolicyError("Broker cash balance is insufficient for live trading")
                return self._json(200,save(STATE_DIR,policy,accounts,request.get("confirmation")))
            except (WebullPolicyError,WebullError,OSError,ValueError,TypeError,KeyError):
                return self._json(400,{"error":"Webull authorization, account class, risk limits or pending orders not verified"})
        if UNIFIED_APP and path == "/api/webull/risk":
            from webull_risk import save
            try:return self._json(200,save(STATE_DIR,self._body()))
            except (ValueError,TypeError,OSError):
                return self._json(400,{"error":"Invalid Webull risk plan or storage unavailable"})
        if UNIFIED_APP and path == "/api/webull/connect":
            from webull_openapi import store_credentials,WebullError
            try:return self._json(200,store_credentials(STATE_DIR,self._body()))
            except (ValueError,TypeError,WebullError,OSError):
                return self._json(400,{"error":"Invalid Webull credentials or unsafe storage"})
        if UNIFIED_APP and path == "/api/robinhood/connect":
            try:
                return self._json(200,install_robinhood_credentials(STATE_DIR,self._body()))
            except (ValueError,TypeError,OSError) as exc:
                return self._json(400,{"error":"Invalid Robinhood credentials or storage unavailable"})
        if UNIFIED_APP and path == "/api/robinhood/pending/resolve":
            from robinhood_crypto_gateway import RobinhoodUnavailable
            from robinhood_order_journal import UnreconciledOrder
            try:
                return self._json(200,resolve_robinhood_orphan(STATE_DIR,self._body()))
            except (ValueError,TypeError,UnreconciledOrder) as exc:
                return self._json(409,{"error":str(exc)[:180]})
            except (RobinhoodUnavailable,OSError):
                return self._json(503,{"error":"Fresh Robinhood order verification unavailable; lock retained"})
        if UNIFIED_APP and path == "/api/robinhood/risk":
            from robinhood_policy import save_policy,PolicyError
            from robinhood_crypto_gateway import RobinhoodCryptoAdapter,RobinhoodUnavailable
            try:
                broker=RobinhoodCryptoAdapter.from_state(STATE_DIR)
                accounts=broker.list_accounts()
                pairs=broker.trading_pairs()
                return self._json(200,save_policy(STATE_DIR,self._body(),accounts,pairs))
            except (PolicyError,ValueError,TypeError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
            except (RobinhoodUnavailable,OSError):
                return self._json(503,{"error":"Robinhood account verification unavailable"})
        if UNIFIED_APP and path == "/api/robinhood/status":
            return self._json(405,{"error":"Use GET for status"})
        if UNIFIED_APP and path == "/api/live/activation":
            try:
                return self._json(200,toggle_live_access(STATE_DIR,self._body()))
            except (SetupError,ValueError,TypeError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:180]})
            except Exception:
                return self._json(503,{"error":"Unable to verify broker account; live trading remains disabled"})
        if UNIFIED_APP and path == "/api/research/forecast/test":
            try:
                payload=self._body()
                if set(payload)-{"forecast_url"} or not isinstance(payload.get("forecast_url",""),str):
                    return self._json(400,{"error":"Invalid forecast test request"})
                address=payload.get("forecast_url","").strip()
                if not address:
                    address,_=forecast_resolve_url(integration_settings(STATE_DIR))
                if not address:
                    return self._json(400,{"error":"Enter a forecast URL, or save an Ollama computer address first"})
                return self._json(200,forecast_probe(address))
            except ForecastConnectionError as exc:
                return self._json(503,{"error":str(exc)[:170]})
        if UNIFIED_APP and path == "/api/integrations":
            try:
                summary=save_integrations(STATE_DIR,self._body())
                return self._json(200,summary)
            except (SetupError,ValueError,TypeError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
        if UNIFIED_APP and path in ("/api/schwab/authorize","/api/schwab/complete"):
            try:
                data=self._body()
                if path.endswith("authorize"):
                    if data:raise SetupError("No input expected")
                    return self._json(200,begin_schwab_auth(STATE_DIR))
                if set(data)!={"redirected_url"}:raise SetupError("Paste the full Schwab OAuth callback URL")
                return self._json(200,finish_schwab_auth(STATE_DIR,data["redirected_url"]))
            except (SetupError,ValueError,TypeError,KeyError,OSError) as exc:
                return self._json(400,{"error":str(exc)[:160]})
            except Exception:
                return self._json(503,{"error":"Schwab OAuth service unavailable or rejected the callback"})
        if path == "/api/profile/password":
            ip=self.client_address[0]
            with _lock:
                now=time.monotonic()
                tries=[t for t in _change_attempts.get(ip,[]) if now-t<900]
                if len(tries)>=5:
                    return self._json(429,{"error":"Too many password attempts; retry later"})
            try:
                data=self._body()
                if set(data)!={"current_password","new_password"}:
                    return self._json(400,{"error":"Current and new password required"})
                with _lock:
                    _change_attempts[ip]=tries+[time.monotonic()]
                    rotate_profile_password(STATE_DIR,data["current_password"],
                        data["new_password"],PASSWORD)
                    _change_attempts.pop(ip,None)
                # All sessions, across all devices, have been invalidated by revision change.
                return self._json(200,{"ok":True,"message":"Password changed. Sign in again."},{
                    "Set-Cookie":"session=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            except ProfileError as exc:
                return self._json(400,{"error":str(exc)})
            except (ValueError,TypeError,OSError):
                return self._json(503,{"error":"Password update could not be saved"})
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
