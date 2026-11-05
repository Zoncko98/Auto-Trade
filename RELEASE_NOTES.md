# Releases

> **Source milestone (November 5, 2026):** `main` declares **v1.2.0**. This is the checked-in source version, **not** a verified running TrueNAS version or an immutable tagged release. The existing deployment may continue to display v1.1.10 until intentionally rebuilt and updated. GitHub branch pushes publish candidate images; an explicit `v*` tag publishes `:stable`. A stable tag and production upgrade were intentionally **not** performed by this documentation change.

## v1.2.0 — Multi-broker workspaces, risk controls and performance diagnostics

- Unifies the layout of the four **existing** Schwab, Robinhood Crypto, Webull and Paper Trading workspaces without adding a new dashboard.
- Adds guarded Robinhood Crypto and Webull broker/account experiences with independent authorization, market-data checks, position visibility, journal reconciliation and operational evidence. Broker acceptance and fills are not certified by the source release.
- Adds Robinhood trade performance Excel exports and fee-aware entry/exit *shadow* diagnostics that do not modify live trade rules.
- Includes optional-news handling, independently mirrored Webull five-minute stock evaluation, AI/connection status consolidation and automated regression coverage.
- See [CHANGELOG.md](CHANGELOG.md) for the detailed changes and [README.md](README.md) for privacy-redacted screenshots of the existing deployed UI.

**Release boundary:** no automatic stable promotion, TrueNAS upgrade, simulated brokerage fill or live broker order is implied by the v1.2.0 source version. Cash and paper accounts remain separately authorized.

## Historical release context

Versions before v1.1.7 were deprecated due to incomplete paper-trading operation; their tags remain for inspection. v1.1.7 introduced repaired experimental paper feeds. v1.1.9 and v1.1.10 subsequently addressed the shared account worker and paper AI routing. None of these historical versions certify profitability or live brokerage fills.

## v1.0.0 — Forecast-enabled Auto Trader

Captured from the working TrueNAS + AI workstation deployment, including five-candidate read-only next-session research, Chronos-Bolt, FinBERT, LightGBM with holdout validation, and Ollama model selection.

**Important:** This is an archival snapshot. Its deployment files contain machine-specific LAN addresses and filesystem paths. Use the portable installer development branch for new systems, not the archival compose files.

The LightGBM model did not beat the no-change baseline in its initial test. Forecasts remain research only and never authorize orders.

## v0.9.0-beta — Frontend v2 (previous build)

Historical build before next-session forecast integration.
