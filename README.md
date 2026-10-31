# Auto Trader

**Open-source MIT-licensed repository · self-hosted market research and experimental cash-only trading controls**

Auto Trader runs a web dashboard on a home server and optionally uses an external Ollama/AI workstation for market research. It can display a five-candidate **Next Trading Session Forecast**, source-linked financial news, research scenarios, model status, and unmet confirmations. **Forecasts are not verified trading signals or guarantees.**

> **Repository status:** public-release source prepared. The historical releases are preserved as immutable tags: [v1.0.0](https://github.com/Zoncko98/Auto-Trade/tree/v1.0.0) and [v0.9.0-beta](https://github.com/Zoncko98/Auto-Trade/tree/v0.9.0-beta). The portable installer is **v1.1.0-dev**, not a public production release. Don't point a fresh installation at the archived v1.0.0 Compose files: they include installation-specific addresses.

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

The installer brings up **only the dashboard**, not the live-trader container. A separate broker account selection, read-only verification and explicit activation are required before live trading.

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

## Private until reviewed

No source or guide makes the repository public. A public release requires a license decision, credential review, fresh-install verification, container-image distribution decision and additional compatibility testing. **Do not expose the dashboard, Ollama API, or forecasting API directly to the public internet.**

Profile password changes and release notifications are also included in v1.1.0-dev.


## TrueNAS Apps native update integration

[Private GHCR images and TrueNAS UI migration](deploy/truenas-apps/README.md) (development/testing only; private registry credentials required).


The v1.0.3 registry images are at [the release](https://github.com/Zoncko98/Auto-Trade/tree/v1.0.3).


## v1.0.4 — AI OAuth and broker market research

- [OAuth AI companions, Ollama models, and broker quotes](docs/guides/oauth-providers.md).
- [MIT License](LICENSE) and [security policy](SECURITY.md).

Live OAuth consent and broker market entitlements require the end user. No AI account authorization can independently enable real-money trading.
