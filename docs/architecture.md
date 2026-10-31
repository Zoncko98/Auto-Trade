# Auto Trader — architecture and data flow

**[Docs](README.md) | [Change history](../CHANGELOG.md) | [Security](guides/security.md) | [Operational status](status.md)**

## Components

```text
Browser (HTTPS)
   |
   v
Home server / TrueNAS / Docker host
   +-- auto-trader-dashboard  -> authentication, runtime control, read-only reports
   +-- auto-trader-paper      -> optional simulated trading (profile "paper")
   +-- auto-trader-live       -> optional, separately gated Schwab worker (profile "live")
   |       |
   |       +-- Schwab API: OAuth tokens, broker risk reconciliation, order checks
   |
   +------> AI Workstation (optional; private LAN)
                 +-- Ollama (e.g. Qwen, DeepSeek; port 11434)
                 +-- Read-only research API (e.g. port 8766)
                         +-- Chronos-Bolt Tiny: time-series scenarios
                         +-- FinBERT: financial headline classification
                         +-- LightGBM: experimental price-feature model
                         +-- market price + source-linked public-news feeds
```

The home server hosts the web UI and optionally the trading worker. **Model inference lives on the optional AI workstation**; the TrueNAS NAS need not run those models. Open WebUI is a separate optional interface to Ollama, not a dependency of Auto Trader.

## Data flows and trust boundaries

- **Dashboard:** HTTPS on the selected NAS IP/port; login password and session secret generated during installation. TLS certificate is self-signed by the installer.
- **Ollama:** selected via a private LAN URL, such as `http://192.168.1.100:11434`; no automatic network discovery or OAuth required by Ollama. Restrict source IPs at the firewall.
- **External AI:** initial adapter supports an OpenAI-compatible HTTPS chat-completions API; provider-specific authentication/protocols need separate implementations/validation. Secrets stay in private environment files, outside Git.
- **Forecast API:** `GET /health`, `GET /api/models`, `GET /api/forecast` are read-only; local refresh is limited to loopback. Forecast ranking cannot trigger broker POSTs.
- **Broker:** Schwab OAuth app key/secret, callback and saved token are never source-controlled. Only the separately launched live-worker may perform permitted brokerage operations, subject to account binding, risk limits and explicit authorization.

## Safety characteristics

- Long-only cash-equity/ETF logic; no margin, options, short sales or borrowing in the current live worker.
- Unverified quotes, broker order states or external AI evidence can block decisions.
- Forecasts offer **illustrative**, not executable prices. LightGBM failed an initial zero-change holdout test; fallback ranking is rule-based until validation improves.
- Live worker does **not** start during normal wizard installation.
- System behavior should not be mistaken for a guarantee of profitability.

## Persistent storage

Wizard creates a directory outside the repository, including:

```text
<PERSISTENT_DATA>/
  config/compose.env
  config/dashboard.env
  config/live.env
  config/schwab.env
  config/paper.env
  state/
     live/                 # order ledger and runtime state
     schwab_token.json     # private broker OAuth token
  logs/
  tls/cert.pem
  tls/key.pem
```

Private files require restrictive host permissions. Never push them to Git, include them in build context, or attach them to bug reports.

For dependency details see `deploy/docker-compose.yml` and `ai-workstation/README.md`.
