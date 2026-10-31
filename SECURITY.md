# Security policy

Auto Trader is self-hosted experimental software. Trading with real money is risky.
Only users explicitly authorized by their broker should connect a brokerage account.

## Never share

- Brokerage developer secrets, OAuth access/refresh tokens, private account identifiers or session cookies.
- ChatGPT/Gemini OAuth credentials, LAN bridge tokens, dashboard passwords, TLS keys or GitHub tokens.
- Logs or support files before checking for personal data.

## Reporting a security issue

Do **not** open a public GitHub issue containing a vulnerability or credential.
Use GitHub's **Report a vulnerability / Private vulnerability reporting** function if enabled for this repository. If the setting is unavailable, ask a repository maintainer through the repository's public issue tracker for a private contact method **without providing the vulnerability details publicly**.

## Design boundaries

- OAuth credentials for AI providers are kept on the user's own AI computer.
- TrueNAS receives only an independent high-entropy local bridge token for optional inference.
- Broker market collector calls read-only quote endpoints and stores no account identifiers.
- Forecasts never grant permission to place live orders.
- Live trading must be explicitly authorized, separately from an AI login or a market-data subscription.
- Container images and the public Git repository do not include user configuration or saved tokens.

## Scope of testing

Historical Git object scanning and targeted credential pattern scans found no matching exposed secrets in the audited history at the time of v1.0.4 preparation. This is **not** a completed security penetration test and does not imply that untested third-party integrations are free of vulnerabilities.

Pin versions, review network listeners and Docker permissions, and check third-party license/market-data terms before publishing your own hosted service.
