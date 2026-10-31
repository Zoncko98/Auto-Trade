## v1.1.0 — Unified trading workspaces and streamlined setup

This version integrates the complete v1.0.18 stable trading engine, AI position reviews and model readiness with the accessibility and user-experience work below. Existing broker tokens, real-money trading authorization, positions and risk limits are preserved in persistent storage. The UI is a presentation and authenticated configuration update, not an automatic change to order execution.

### Login, installation and broker navigation cleanup

- Reduced the minimum length for NEW dashboard administrator passwords from 20 to 10 characters. New passwords require an uppercase A–Z letter, number and symbol (up to 256 characters). Both the server and browser enforce the rule. Existing passwords remain valid; PBKDF2 protection, login rate limiting and session invalidation are preserved.
- Simplified first-run installation to account claim and AI model/provider selection. Forecasting uses the built-in NAS default. Schwab OAuth, background modules and trading permissions are no longer part of first-run.
- Profile now links to AI & Forecast Settings only. The existing Schwab developer credentials, callback flow, read-only quote monitoring, account selection and real-money activation are on the new authenticated broker-specific page accessible from Broker Connections.
- Page-specific settings updates preserve unrelated AI settings, broker secrets and live-trading configuration. Neither settings page can accidentally clear the other one's fields.
- Added explicit Paper → Risk Settings control to enable/disable the separate background paper simulator without placing this option in installation or Schwab authorization.
- Added end-to-end and browser payload isolation regression tests, with the new tests included in the GitHub Actions workflow.
- Integrated on the v1.0.18 codebase. No live-trading authorization defaults, account choices or execution permissions are changed by this release.

### Workspace account tiles (feature/workspace-account-tiles)

- Replaced the sidebar Live/Paper dropdown with visually distinct selectable account tiles. Schwab Live opens the existing live overview and Paper opens the existing simulator, each preserving its dedicated navigation, risk controls and account history.
- Added greyed-out, non-clickable Coming Soon tiles for Webull, Robinhood, Alpaca and Interactive Brokers. These are interface placeholders, not real brokerage connections or order routes.
- Shows a conservative Schwab connection hint from authenticated /api/brokers capability metadata (AUTH SAVED vs CONNECT ACCOUNT); a stored OAuth file is not evidence that an active broker session or order permission is valid.
- Added selected-account highlighting, keyboard-focus and ARIA pressed states, mobile compact tiles, small-screen layout refinements and reduced-motion treatment.
- Added freshness-checked equity badges: paper simulator equity and Schwab broker equity only for an online worker with a recent valid account snapshot; unavailable values never show fake $0.00. Balance text clears on logout.
- Replaced letter placeholders with pictograms and retained the paper wallet icon. Added the unmodified Alpaca external-use brand kit asset. Other providers use neutral symbols pending clear logo permissions; provenance and reuse restrictions are recorded in docs/guides/workspace-tiles.md.
- No credentials, risk settings, order code, broker selection, trading authorization or production deployment were changed.
- Combined into v1.1.0 and validated against the v1.0.18 trading safeguards.

## v1.0.18  Recurring advisory AI reviews for live positions

- Added periodic (15-minute minimum per symbol) structured AI news assessments for already-held live positions.
- Uses the existing strictly validated live AI-review response schema; missing, malformed, or unavailable responses remain fail-closed for new BUY entries.
- Position review outputs are explicitly advisory, never automatic SELL commands; existing independent downward-crossover and authorized protective exits take priority.
- Records bounded, non-secret position AI review telemetry to the existing private live-state volume, without sending holdings or account data to the AI.
- Adds four isolated unit tests with mocked AI providers. No paper trades or live test orders.
- Does not yet verify structured capabilities for all configured cloud providers or implement AI-generated SELL/REDUCE execution. These require separate validation.
- Does not modify live settings or redeploy TrueNAS.

## v1.0.17  Verified local AI model metadata and readiness UI

- The authenticated readiness API now queries the configured private-LAN Ollama /api/show endpoint with a five-second timeout and bounded response size.
- Validates actual model parameter_size metadata rather than trusting the model-name suffix; unknown, undersized or unavailable models are explicitly reported as unverified.
- Dashboard sidebar shows SIZE VERIFIED, BELOW 4B or AI OFFLINE with clear limitations.
- No inference payload, account data or broker credentials are sent during metadata validation.
- Metadata verification is not a structured-response capability test and does not yet change live entry authorization; the existing fail-closed AI news veto remains in force.
- Added mocked unit tests for verified metadata and provider failure. No paper or live orders were placed.
- Existing live position SELL protections and risk settings are untouched.

## v1.0.16  Visible AI configuration readiness

- Added an authenticated sidebar AI readiness indicator and failure/uncertainty explanations, refreshed every 30 seconds.
- Explicitly differentiates a model-name claim from verified model metadata or a working AI connection.
- Preserved the existing fail-closed AI research veto on new live buys; existing rule-based protective sells remain independent.
- Does not assert runtime readiness, implement model metadata verification, or enable a new live trading gate until these mechanisms can be validated.
- No paper trading or real order execution was performed during validation.

## v1.0.15  Read-only AI compatibility diagnostics (stage one)

- Added authenticated GET /api/ai/readiness with non-secret model/provider compatibility status.
- Local Ollama model-name parser flags claims below the proposed 4B minimum; name alone does NOT verify actual parameter count, readiness or capability.
- Cloud selections are reported as needing runtime verification, not falsely marked healthy.
- No credentials are exposed. No AI calls are made by the endpoint.
- Added five targeted tests for 4B, subminimum, unknown size, cloud and missing provider.
- No new trading gate or runtime enforcement: existing live orders, risk controls, authentication and settings remain unchanged.
- Future stage: authoritative metadata and structured response probes, then separately validated live enforcement.

## v1.0.14  Advisory technical indicator research

- Added deterministic 14-session RSI, 12/26 MACD and nine-session signal, a close-only 14-session volatility range proxy, and relative volume compared with the previous 20 sessions.
- Added a clearly labeled symbol-only trending/ranging/volatile regime proxy; it is not a broad-market regime assessment.
- Attached advisory indicator data to NAS-native read-only forecast research for candidates with sufficient validated history.
- ATR is explicitly labeled a close-only proxy because the historical feeds currently use close/volume bars; it must not be confused with true OHLC-based ATR.
- Added four regression tests covering indicator bounds, insufficient data, invalid close and flat prices.
- Kept all live entry selection, AI veto policy, risk controls, order sizing and broker authorization unchanged. Indicators do not automatically trigger orders.
- No production deployment or live-order tests performed.

## v1.0.13  Explainability update release validation

- Updated the profile version regression test to compare against the application VERSION file instead of hard-coding v1.0.11; this keeps the test valid for subsequent releases.
- Preserved the v1.0.12 code and immutable tag. v1.0.12's image publication failed due to the version-specific test assertion.
- Published the explainability changes under a new immutable release version after correcting validation. No changes to execution behavior.

## v1.0.12  Explainable trade decision records

- Added app/trade_explanations.py for structured, observable trade evidence; no private model thoughts are claimed.
- Paper trading reviews now record the crossover strategy, AI response, risk flags, and decision timestamp.
- Live entry audit evidence includes technical reasons, AI verdict, and up to eight ranked alternatives.
- Screened-but-not-selected alternatives are not misrepresented as confirmed failed entry signals.
- Invalidation levels are only recorded when explicit validated data is available, never invented; no automatic stop order is added.
- No fabricated confidence probability. Existing execution, risk, authorization and cash-only protections are unchanged.
- Four standalone tests added. No TrueNAS production deployment or live execution testing was performed.

## v1.0.11 — Sidebar installed-version display

- Replaced the bottom-left sidebar sentence about the Schwab worker and dashboard order submission with a live Auto Trader vX.Y.Z version label.
- Version comes from the authenticated, local /api/profile endpoint after login, so it always reflects the installed app, not the latest GitHub release or TrueNAS custom catalog metadata.
- If version lookup is unavailable, the footer shows a clear fallback rather than an outdated hard-coded version.
- No changes to broker connections, order permissions, risk limits, credentials, or deployment topology.

## v1.0.10 — Multi-broker workspace foundation

- Added a new authenticated **Broker connections** view to the single TrueNAS Auto Trader app, accessible from both live and paper workspaces.
- Verified and documented official API routes for Schwab, Webull Connect/OpenAPI, Alpaca Connect, Interactive Brokers and Robinhood Crypto. Clearly distinguish published provider capabilities from real integrations and account authorization.
- Introduced a typed Python BrokerAdapter contract covering accounts, balances, positions, market quotes, order history, submission and cancellation. All non-Schwab adapters explicitly fail closed; no new live trade execution has been enabled.
- Exposed authenticated GET /api/brokers returning non-secret capability and integration metadata. The Schwab badge reflects only presence of a saved authorization file, not proof of a valid current broker session.
- Added the provider documentation links, exact API access prerequisites, asset-class restrictions and phased integration plan under docs/guides/multi-broker.md.
- The existing Schwab OAuth workflow, live worker, cash-only restrictions, risk controls, paper engine, AI model settings, trade histories and TrueNAS deployment are unchanged. No new brokerage password/API key is collected.
- Added tests for unsupported-adapter fail-closed behavior, credential non-disclosure, broker feature claims and integration statuses.

## v1.0.9 — NAS-native market forecasts and selected-provider commentary

- Implemented a no-extra-model NAS-native daily market analysis engine inside the single TrueNAS app, with genuine historical data feeds, eligibility screens, technical momentum/trend/volatility/liquidity calculations and illustrative historical-volatility bands.
- Added a second public price-history feed fallback, dated persistent cache, background fetching and explicit incomplete/stale state. No speculative prices are generated when market data is absent.
- Added Automatic, Built-in NAS and Advanced Workstation forecast modes. Existing specialist Chronos/LightGBM/FinBERT forecasting remains optional.
- Added opt-in qualitative public-news interpretation using the user's already selected Ollama or ChatGPT/Gemini OAuth companion. The model cannot modify prices, scores or trading eligibility. Existing cloud OAuth requires a LAN companion; direct native cloud OAuth login is not implied.
- Updated forecast UI to distinguish historical-volatility bands from advanced scenario quantiles, display relevant source/model, provider commentary when available, and helpful setup errors.
- Continued the first-run wizard into Schwab OAuth onboarding, with optional skip. Included explicit forecast explanation, connection test, workstation setup and security guide.
- Added no-AI, provider-schema, deterministic data and regression tests. No changes to brokerage trading permissions or live order logic.

## v1.0.8 — Schwab redirect copy-and-paste repair

- Fixed incorrect callback mismatch errors when the developer-app callback is https://127.0.0.1:8182 but the browser adds the standard root slash and returns https://127.0.0.1:8182/?code=...&state=.... These root paths are equivalent for validating the returned redirect; the exact callback sent to Schwab remains unchanged.
- Preserved strict HTTPS, host, port, non-root path and OAuth state comparisons, so redirects from another host or unrelated sign-in sessions are still rejected.
- Improved error messages to distinguish callback base-address mismatches, expired/different authorization sessions, missing authorization codes and token-exchange failures. Code/state values are never shown in errors.
- Trim harmless surrounding whitespace from browser-copied callback addresses.
- Added regression tests for root-slash acceptance and rejected wrong port, host, scheme, path, and fragment.
- Does not change Schwab developer-app settings, credentials, stored tokens, positions or live order permissions.

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
