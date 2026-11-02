# Robinhood Crypto integration groundwork

This feature initially adds a read-only Robinhood Crypto API adapter in `app/robinhood_crypto_gateway.py` for the existing multi-broker architecture. It does not alter the current Schwab or paper engines. Order submission and cancellation always fail closed.

## Authentication

Register an Ed25519 public key using the official Robinhood Crypto API settings. Store the resulting Robinhood API key identifier and the matching Base64 raw 32-byte private signing key outside Git, and inject as `ROBINHOOD_CRYPTO_API_KEY` and `ROBINHOOD_CRYPTO_PRIVATE_KEY_B64` at runtime. Never place either credential in frontend code, GitHub, logs, or issue trackers.

## Validation

Install `app/requirements.txt` and run `python -m unittest discover -s app -p test_robinhood_crypto_gateway.py`. These tests mock network calls and never send live orders.

This is groundwork only: API credentials have not been verified against a live Robinhood account. Dashboard wiring, pagination, rate limits, account-specific responses, connection status and optional live trading require further implementation and tests. Robinhood's published trading API applies to crypto; it is not an authorization to automate equities or options.

The feature branch also includes an isolated live-order adapter in app/robinhood_crypto_execution.py; it is not automatically activated by this status UI. /api/robinhood/status checks actual account connectivity from server-only secrets, without exposing credentials to the browser.
