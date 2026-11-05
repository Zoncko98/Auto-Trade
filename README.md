# Auto Trader

> **Source status (November 5, 2026):** `VERSION` is **1.1.10** on this development branch. This is a source version, **not** proof of the version installed on TrueNAS. The deployed container revision must be checked independently (see [production baseline](docs/truenas-production-baseline.md)). Auto Trader is experimental; neither trading profitability nor broker-side execution across providers is certified.

## Current broker capabilities in source (not production verification)

- **Schwab:** independently authorized live equities worker and broker-order reconciliation.
- **Robinhood Crypto:** authenticated account integration with account-scoped, explicitly enabled live crypto order submission; disabled by default.
- **Webull:** account-scoped stock/crypto order submission code and operator authorization controls. `LIVE_EXECUTION_VERIFIED` is `False`; a policy may still be armed as *operator-authorized but unvalidated*. This is not evidence that an order was accepted or filled.
- **Alpaca and Interactive Brokers:** discovery/integration guidance; do not treat the broker cards as live order integrations.

Broker capabilities vary by account and permissions. A connected account does not alone authorize live orders. Details: [multi-broker guide](docs/guides/multi-broker.md).

## Historical release notes


## v1.0.11 — Installed version in sidebar

The bottom-left corner of Auto Trader now displays its installed application version directly from the local profile endpoint. This replaces the legacy Schwab-only sentence and is independent of the remote release notifier.

## v1.0.10 — Multi-broker connections

Auto Trader now includes a **Broker connections** workspace in its single TrueNAS app. It lists Charles Schwab, Webull, Alpaca, Robinhood Crypto and Interactive Brokers, with official API requirements and clearly labeled implementation status.

At the v1.0.10 milestone only Schwab had live-order wiring; subsequent development added guarded Robinhood Crypto and Webull order paths. See the [current capabilities above](#current-broker-capabilities-in-source-not-production-verification), the [multi-broker guide](docs/guides/multi-broker.md), and [changelog](CHANGELOG.md).

## v1.0.9 — Built-in forecast and optional selected AI provider

Forecasting now works inside the single Auto Trader TrueNAS image, with no separate AI workstation or specialist model installation needed. Automatic mode uses an existing advanced service when available and otherwise computes historical-price technical research natively. The configured local or OAuth companion can optionally add public-news commentary without access to brokerage data.

See docs/guides/forecast-research.md and CHANGELOG.md for calculations, source limitations and configuration.

## v1.0.8 Schwab callback hotfix

Browser-generated root / in Schwab OAuth redirects no longer causes a false callback mismatch. See CHANGELOG.md and the TrueNAS install guide for details.

## v1.0.7 setup and update fixes

Clear setup-progress states, explained paper/market modules, single-button live-trading confirmation, and guided Schwab callbacks. TrueNAS Source: N/A is expected for custom YAML apps; native updates use the public stable image digest, and the Auto Trader Profile links directly to GitHub.

## Recommended installation: ONE TrueNAS app, ONE update

Use the [Unified TrueNAS installation guide](deploy/truenas-apps/README.md).

Install one public image: ghcr.io/zoncko98/auto-trade:stable.
In TrueNAS Apps > Discover > Custom App via YAML, paste deploy/truenas-apps/unified.yml, adjusting the dataset path.
Open HTTPS Auto Trader in your browser and complete the first-run web wizard:
- Pair using the one-time code from the TrueNAS app logs
- Choose administrator username and password
- Configure remote Ollama endpoint and model, or OAuth AI companion
- Configure Schwab developer app credentials and log in on Schwab's official website through the app GUI
- Choose paper/market modules; live worker remains off until explicitly authorized

The dashboard, paper trading, market-data monitoring and live worker are internal components of this one image, not independent TrueNAS Apps. Future versions update ONE app. Brokerage settings, trading journals and tokens stay in persistent storage.


**Open-source MIT-licensed repository · self-hosted market research and experimental cash-only trading controls**

Auto Trader runs a web dashboard on a home server and optionally uses an external Ollama/AI workstation for market research. It can display a five-candidate **Next Trading Session Forecast**, source-linked financial news, research scenarios, model status, and unmet confirmations. **Forecasts are not verified trading signals or guarantees.**

> **Repository status:** source is published on GitHub. Archived tags such as [v1.0.0](https://github.com/Zoncko98/Auto-Trade/tree/v1.0.0) and [v0.9.0-beta](https://github.com/Zoncko98/Auto-Trade/tree/v0.9.0-beta) are historical; they are not recommended fresh-install targets. Legacy Compose files contain host-specific paths. A clean-room installation and the exact deployed revision still need independent verification.

## Documentation navigation

**[Overview](docs/README.md) · [TrueNAS SCALE](docs/install/truenas-scale.md) · [Docker / Linux](docs/install/docker-linux.md) · [Unraid](docs/install/unraid.md) · [Synology & QNAP](docs/install/synology-qnap.md) · [Proxmox](docs/install/proxmox.md)**

**[Windows / WSL2](docs/install/windows-wsl.md) · [AI / Ollama](docs/guides/ai-setup.md) · [Schwab OAuth](docs/guides/schwab.md) · [Operations](docs/guides/operations.md) · [Troubleshooting](docs/guides/troubleshooting.md) · [Release history](CHANGELOG.md)**

## Installation choices

| Host | Installation route | Verified status |
| --- | --- | --- |
| TrueNAS SCALE 25.10+ | SSH/TrueNAS shell and Docker Compose | **Working home installation**; portable clean-install wizard not yet end-to-end tested |
| Ubuntu/Debian and other Linux Docker hosts | Docker Engine + Compose + `--platform docker` | Compose configuration and installer unit-tested; fresh host still untested |
| Unraid | Dedicated Linux VM with Docker Compose | Guidance only; not an Unraid Community Apps package |
| Synology / QNAP | Shell with supported Docker Compose, or Linux VM | Guidance only; not a vendor app store integration |
| Proxmox VE | Dedicated Linux virtual machine with Docker Compose | Guidance only; not a ready-to-import VM template |
| Windows Docker Desktop / WSL2 | Ubuntu WSL2 distro and Linux containers | Guidance only; not a native Windows service |

**Start here:** [Choose your host](docs/README.md). Every guide links back to the same navigation hub.

## What is included

- HTTPS dashboard for live control/telemetry, paper simulation, audit history, model selection and five research candidates.
- A **separate optional** Windows research engine: Chronos-Bolt Tiny (time series), LightGBM (feature-based model), FinBERT (news sentiment), and Qwen/other models via Ollama.
- Configurable private-LAN Ollama URL and model; experimental OpenAI-compatible HTTPS API support; optional forecast service URL.
- Separately authorized Schwab OAuth for brokerage API integration. **Never enter Schwab username/password into Auto Trader**.
- Private data outside the Git checkout, installer-created TLS certificate, read-only forecast endpoint, and explicit opt-in gates before any live orders.

On fresh unified installs, the dashboard starts first; configured paper and broker workers can subsequently run as subprocesses inside the **same** container. Live trading requires broker-specific account selection, eligible credentials and explicit authorization; separate live-worker Docker containers are a legacy optional deployment design.

## Repository map

| Location | Purpose |
| --- | --- |
| `app/` and `web/` | Application backend, trading safeguards, dashboard, browser assets |
| `deploy/` | Portable Docker Compose and Dockerfiles |
| `installer/` | Interactive setup wizard, Schwab manual OAuth helper, tests |
| `ai-workstation/` | Separate forecasting service and model bootstrap instructions |
| `docs/install/` | Per-platform installation guides |
| `docs/guides/` | AI, Schwab, backup/update, security and troubleshooting |
| [CHANGELOG.md](CHANGELOG.md) | What we changed and when |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, security boundaries |
| [docs/status.md](docs/status.md) | Tested vs planned features, known limitations |

## Public source and security boundaries

The GitHub repository and published image references must be treated as public-release surfaces. Never commit credentials or installation-specific secrets. Clean-install verification, dependency review and container hardening remain outstanding. **Do not expose the dashboard, Ollama API, or forecasting API directly to the public internet.**

Version-specific notes elsewhere in this file describe historical milestones and are not independent production verification.


## TrueNAS Apps native update integration

[Unified TrueNAS custom-YAML install guide](deploy/truenas-apps/README.md). The `:stable` tag is mutable; record the deployed digest and revision before making operational changes.


The v1.0.3 registry images are at [the release](https://github.com/Zoncko98/Auto-Trade/tree/v1.0.3).


## v1.0.4 — AI OAuth and broker market research

- [OAuth AI companions, Ollama models, and broker quotes](docs/guides/oauth-providers.md).
- [MIT License](LICENSE) and [security policy](SECURITY.md).

Live OAuth consent and broker market entitlements require the end user. No AI account authorization can independently enable real-money trading.
