# Implementation and validation status

**[Docs](README.md) | [Architecture](architecture.md) | [Change history](../CHANGELOG.md)**

Last documentation review: **2026-11-05 (America/Phoenix)**.

**Scope:** This page distinguishes checked-in source capabilities from confirmed production behavior. `VERSION` is `1.2.0`; the exact deployed `:stable` image commit remains unverified. See [production baseline](truenas-production-baseline.md).

| Component | Current status | Evidence / limitation |
| --- | --- | --- |
| TrueNAS existing deployment | **Working (owner-confirmed)** | Dashboard updated and inspected; does not prove portable clean install |
| Ollama LAN connectivity | **Verified on project LAN** | Model tags visible, no inference test requirement for this documentation work |
| Chronos-Bolt Tiny | **Inference smoke test passed** | CPU quantiles produced; not accuracy validation |
| FinBERT | **Inference smoke test passed** | Sample headline classified; not trading accuracy |
| LightGBM | **Experimental / unvalidated** | Initial holdout MAE **worse** than zero-return baseline; rank falls back to rule-based logic |
| Next-session forecast | **Research API and dashboard implemented** | Five candidates and news links; sources and schedule may be incomplete or delayed |
| Windows AI service autostart | **Configured on original workstation** | Task Scheduler startup; portable setup instructions added, not automated on every other system |
| Beta tag | **Preserved** | `v0.9.0-beta` / branch `beta` |
| v1.0.0 tag | **Preserved** | Archival release, commit `9986003` |
| Portable TrueNAS CLI installer | **Unit and Compose validated** | A complete new TrueNAS install not yet independently exercised |
| Generic Linux Docker CLI installer | **Unit and Compose validated** | `--platform docker` added; fresh-machine acceptance test pending |
| TrueNAS Custom App via YAML | **Template available; existing app owner-confirmed** | `deploy/truenas-apps/unified.yml` uses the published `:stable` image; independent clean-install acceptance remains pending |
| Native TrueNAS catalog listing | **Not available** | Custom-YAML installation is not a catalog-published application |
| Unraid, Synology/QNAP, Proxmox, Windows WSL2 | **Instructions only** | No platform acceptance tests or vendor UI packages |
| Schwab app credential setup | **Wizard built** | Private files generated; manual OAuth helper not tested with every real-account configuration |
| Schwab live order execution | **Implemented; separate opt-in** | Requires selected account and broker safeguards; broker fills are not implied by source code |
| Robinhood Crypto order execution | **Implemented; separate opt-in** | Account-scoped risk policy and live crypto write adapter; actual broker acceptance is not verified by this page |
| Webull order execution | **Implemented; not execution-verified** | `LIVE_EXECUTION_VERIFIED=False`; operator may arm an unvalidated policy; broker acceptance not implied |
| Alpaca / Interactive Brokers | **Discovery only** | No independently validated live order pathway confirmed |
| Generic OpenAI-compatible API | **Initial adapter / experimental** | Real end-to-end provider-specific tests not complete |
| Anthropic/Gemini native API support | **Not verified in portable live worker** | Some old code contains adapters; not integrated into the new install flow |
| CI workflow | **Committed** | Runner result, all container builds and provider checks still need verification |

## Current automated test selection

- `python3 -m unittest discover -s installer` — wizard + offline Compose checks.
- `python3 -m unittest discover -s app -p test_frontend_v2.py` — existing frontend controls and audit safeguards.
- `python3 -m compileall -q app installer ai-workstation` — syntax.
- `docker compose --env-file <DATA>/config/compose.env -f deploy/docker-compose.yml config --quiet` — local Compose validation.

The image-publishing workflow runs application discovery and selected frontend tests. The separate installer workflow previously folded multiple commands into one YAML scalar; the current branch corrects this. CI configuration does not prove successful GitHub runner execution: inspect the checks for the specific commit before claiming a green build.

## Further release and installation validation

1. Use a clean disposable TrueNAS/Linux Docker environment to test wizard, build, runtime and reinstallation refusal.
2. Validate GUI navigation, security headers, model discovery and real AI fallback behavior.
3. Validate and document Schwab OAuth/manual redirect on a dedicated test account/application without submitting orders.
4. Pin and audit dependencies; test architectures and container security/backup.
5. Decide package format, image registry and platform UI install experiences.
6. Audit public-source and registry surfaces for accidental secrets and verify deployment provenance before release promotion.

## v1.0.4 additions

- **Synthetic tests:** OAuth companion validation and Schwab quote normalization/freshness.
- **User consent pending:** ChatGPT browser OAuth and Gemini Google Cloud ADC interactive sign-in.
- **Broker authorization pending:** near-real-time Schwab polling and authenticated UI quote monitoring.
- **Not yet verified:** model calibration driven by real streaming quotes or OAuth model inference with a live third-party account.

- **Forecast calibration monitoring:** daily out-of-sample scorecard records candidate quantiles before the next session, then compares them with later observed daily closes; 20+ samples required for descriptive coverage metric. Not a proven signal.
