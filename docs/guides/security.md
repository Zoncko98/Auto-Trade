# Security & privacy checklist

**[Docs](../README.md) | [Schwab](schwab.md) | [Operations](operations.md) | [Status](../status.md)**

## Repository access

- The GitHub repository remains **PRIVATE**. Do not change visibility or publish packages before review.
- Do not commit `config/`, `state/`, `logs/`, `backups/`, `.env`, TLS keys, credential files, tokens, or model cache files.
- The code's `.gitignore` and `.dockerignore` are safeguards, not a replacement for a secret scan.
- Review **entire Git history** before a future public release; deleting a secret from the latest file does not remove it from old commits.
- For automated CI, use least-privilege, read-only checkout permissions where possible.

## Host/network restrictions

- Dashboard: HTTPS on private LAN; strong unique password, random session secret. The wizard's cert is self-signed; production trust requires TLS management.
- Ollama (11434) and forecast service (8766): accept connections **only from expected NAS/clients**. Limit by host firewall; avoid public port forwarding.
- AI and news services are **not trusted broker authority**. Model outputs may be wrong, delayed, injected or maliciously formatted.
- Windows AI workstation is separate from the NAS, runs model weights and public-market research, **without** Schwab tokens.

## Credentials and brokerage safety

- Schwab developer **APP KEY/APP SECRET** are not website login details. Never request, store or display a Schwab username/password.
- OAuth tokens are sensitive; restrict `state/schwab_token.json` and never post redirected OAuth URLs containing codes.
- Live worker is not started by install; `LIVE_TRADING=false` and account hash unset. Extra approval, broker reconciliation and operator controls remain required.
- Cash-only/long-only order safeguards do not eliminate financial risk. Do not promise a daily return.

## Before sharing this repository publicly

- Decide license and redistribution terms for application code; check third-party model/data licenses.
- Remove user-specific network addresses from **current code and all reachable history/archives** as appropriate, and audit any accidentally committed secrets.
- Validate clean installations on supported architectures and Docker/TrueNAS UI routes.
- Run dependency, container and supply-chain audits; ideally pin verified versions/digests and publish SBOMs.
- Validate provider-specific API adapters, rate limits, spend caps, incident recovery and token rotation.
- Publish security disclosure process and obtain code review before enabling public distribution.

**The present private development branch is not a completed public security audit.**
