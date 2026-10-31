## v1.0.7 — Installation fixes and simplified live trading

- Fix GUI setup progress: administrator creation is complete independently from optional AI, broker OAuth and module connection states.
- Stop requiring live-trading confirmation words when saving unrelated integration settings.
- Replace the live-trading checkbox and manually typed phrase with one ON/OFF button. ON shows an explicit real-money order confirmation popup and validates the selected Schwab account. OFF pauses order permission.
- Clarify two optional modules: simulated paper trading versus read-only Schwab quote monitoring. The quote monitor can be selected before connecting Schwab and waits for authorization.
- Explain 127.0.0.1:8182 points to the browser computer. A browser connection error after Schwab login is expected without a local listener. Copy the full redirect URL into the integration page.
- Add an optional direct HTTPS NAS callback for developer apps registered to that exact address. Developer callback changes can require Schwab reapproval.
- Prevent OAuth query-code leakage through web access logs.
- Check public GitHub release tags from the GUI, show the repository source link, and document native TrueNAS image update support and custom YAML Source N/A.
- Add regression tests for OAuth callback, live order confirmation, update checks and optional module setup. Existing brokerage credentials and trading data are not included.

## v1.0.6 — Unified TrueNAS app and first-run web setup

- One public container image and stable tag for all Auto Trader components; no separate paper/live/market updates.
- First-run HTTPS wizard for administrator username and password, Ollama, OAuth AI companions, Schwab developer settings, and module selection.
- GUI-driven Schwab OAuth redirect flow and linked broker account selection.
- Paper, market and live functionality remains internal to a single Docker container; no automatic live trading on install.
- Persistent protected credentials and broker state; one-time pairing code shown in TrueNAS app logs.

# Auto Trader change history

[Documentation](docs/README.md) · [System architecture](docs/architecture.md) · [Test status](docs/status.md)

## 2026-10-31 — v1.0.3: Private Docker registry update distribution

- Added GitHub Actions to build/test/version private linux/amd64 dashboard, paper and live-worker container images.
- Stable releases publish immutable version tags for all images and mutable stable tags for dashboard/paper only; live remains version-pinned for order safety.
- Added TrueNAS Apps YAML templates and instructions for private GHCR login, GUI updates and dashboard migration.
- Added .dockerignore protections for image build contexts; no secrets or OAuth tokens are shipped in images.
- No automatic activation of brokerage trading. Existing TrueNAS deployment is not switched without a backup and registry authentication.
- Note: native TrueNAS image-update indicator still requires a successful private-image pull and GUI validation.

## 2026-10-31 — v1.0.2: Manual update status display

- Adds an explicit Software Updates panel within the user profile.
- Displays the installed version, latest stable GitHub version, and host check timestamp.
- Adds a manual Refresh Update Status button that only reads local host-checked state.
- No automatic code installation, broker credential changes, or live-worker modifications.
- Published as a real follow-up stable tag to test the v1.0.1 dashboard update notification.

## 2026-10-31 — v1.0.1: Administrator Profile and private release updates

- Added an Administrator Profile with a dashboard password-change option.
- Changing passwords requires the current password, stores a salted PBKDF2 hash in persistent state and invalidates all existing sessions.
- Added cookie revisioning, change-request rate limits and HTTPS integration tests.
- Added authenticated read-only profile/version endpoints and an Update available notice.
- Added a host-side private GitHub stable-tag checker; GitHub SSH credentials never enter the dashboard container.
- The v1.0.0 dashboard cannot show notifications until this feature is installed once.
- The live brokerage worker and its risk controls were not altered.

## 2026-10-30 / 2026-10-31 — Portable installer documentation (v1.1.0-dev)

- Preserved the current v1.0.0 snapshot and the earlier v0.9.0-beta snapshot as immutable Git tags.
- Published `main` for v1.0.0 and `beta` for the prior build.
- Created `feature/truenas-portable-installer` for installation/portability changes without altering either release tag.
- Added an interactive installer that generates private `config/*.env` values, a local HTTPS certificate, isolated persistent storage, and Docker Compose deployment.
- Added customizable Ollama LAN URL/model, an OpenAI-compatible HTTPS API route and API key, and a separate forecast-service endpoint.
- Added Schwab developer app key/secret and manual OAuth flow; installation **does not** start live orders.
- Added a general Linux/Docker mode so the wizard does not require a TrueNAS `/mnt/POOL/` path outside TrueNAS.
- Added source files for the optional Windows AI workstation, initial tests, Compose validation and GitHub Actions checks.
- Added platform documentation/navigation, operations, security, troubleshooting and architecture references.
- **Status:** v1.1.0-dev documentation and deployment tooling under development; not a tested general-public release.

## 2026-10-30 — v1.0.0: next-session AI research

- Updated dashboard model discovery to the separate Ollama server on the LAN instead of running large AI models on the NAS.
- Confirmed Ollama models available for use by the dashboard, including Qwen and DeepSeek-R1 where installed.
- Installed **LightGBM**, **Amazon Chronos-Bolt Tiny** and **ProsusAI FinBERT** on a separate Windows computer, not as Ollama chat models.
- Added the read-only `/health`, `/api/models`, and `/api/forecast` endpoints on the Windows research service.
- Built an experimental five-candidate forecast refreshed after market close and on Monday pre-open (timezone: America/New_York). Research includes market-data sources, dated news links, forecast price scenarios, illustrative entry/invalidation/2R levels and unmet confirmations.
- Ranked candidates conservatively: a tested LightGBM holdout did **not** beat the zero-return baseline, so its output is labeled *unvalidated* and excluded from rankings. Fallback uses transparent technical rules.
- Added the dashboard **Next session forecast** view; verified the NAS could reach the LAN research service.
- Registered a Windows Task Scheduler startup task for the standalone research service and limited its inbound firewall access to the NAS.
- Preserved broker execution and risk controls: forecast output is **not** an order command.
- **Release tag:** `v1.0.0`, commit `9986003`.

## Pre-forecast version — v0.9.0-beta

- Earlier dashboard with live overview, decision evidence, operator risk settings, local model selection, paper overview/trades/audits and export work.
- Cash-only, long-equity, hard-capped trading-worker order validation, broker reconciliation and fail-closed behavior; dashboard login/session protections.
- The beta source is preserved in branch `beta` and tag `v0.9.0-beta`, commit `de15983`.

## Reproducibility notes

- The old v1.0.0 archive contains installation-specific LAN addresses and was **not** itself designed as a portable install package.
- Public market-data/news sources can be delayed, incomplete or unavailable.
- The optional Windows forecasting code is independent of the TrueNAS/Docker dashboard.
- The installer is not a published TrueNAS Apps catalog listing or an Unraid/Docker Hub image.
- Earlier test suites include legacy tests expecting endpoints removed in newer dashboard versions; consult [test status](docs/status.md).

## Upcoming work (not done)

- Clean-host install and upgrade/rollback integration tests.
- Native TrueNAS Apps YAML or catalog packaging with published images.
- Vendor UI manifests/containers for Unraid, Synology and QNAP.
- Verified end-to-end cloud-AI adapters and stricter provider-specific validation.
- Real-time broker market data integration for forecasts, model calibration and live inference monitoring.
- Additional security audits, licensing and public-release readiness.


## v1.0.4 — OAuth AI bridges, broker data monitoring and public-source preparation

Merged portable installer and registry update setup with v1.0.3 release, and adding provider-specific OAuth + broker-market-data integration.

- Added browser-based ChatGPT OAuth/OIDC companion using PKCE, token validation and independent plan authorization; user-consent test pending.
- Added Google Cloud Gemini OAuth ADC companion, with stricter model and response validation.
- Preserved Ollama remote endpoint and selectable model installation on the AI computer.
- Added read-only Schwab quote collector with protected timestamped cache and live quote display in forecasts.
- Added MIT licensing, public security guidance and full-history credential pattern scan of 218 objects (no matches).
- No automatically authorized trades. Broker entitlements and OAuth real-account tests remain user-dependent.


## v1.0.5 — Public container images and dashboard build correction

- Fix dashboard image build to use repository-root context and deploy/Dockerfile.dashboard, including the web interface.
- Preserve versioned images for all services, mutable stable tags for dashboard/paper/market, and pinned live-broker worker.
- No order execution or operator permission changes.
