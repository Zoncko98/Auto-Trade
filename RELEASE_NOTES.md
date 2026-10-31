# Releases

> **Release status (October 31, 2026):** Every version before **v1.1.7** (v0.9.0-beta, v1.0.x, and v1.1.1-v1.1.6) is **DEPRECATED / UNSUPPORTED** due to incomplete or malfunctioning paper-trading functionality. Git tags are retained for historical reproducibility. **v1.1.7** is the current supported experimental build, but neither profitability nor live-broker execution is certified.

## v1.1.7 - Current supported experimental build

Restored the existing paper worker heartbeat and public crypto/equity feed ingestion, with separate AI approval and risk limits. No guarantee of hypothetical or live returns.


## v1.0.0 — Forecast-enabled Auto Trader

Captured from the working TrueNAS + AI workstation deployment, including five-candidate read-only next-session research, Chronos-Bolt, FinBERT, LightGBM with holdout validation, and Ollama model selection.

**Important:** This is an archival snapshot. Its deployment files contain machine-specific LAN addresses and filesystem paths. Use the portable installer development branch for new systems, not the archival compose files.

The LightGBM model did not beat the no-change baseline in its initial test. Forecasts remain research only and never authorize orders.

## v0.9.0-beta — Frontend v2 (previous build)

Historical build before next-session forecast integration.
