# Robinhood Crypto integration

Auto Trader includes a signed Robinhood Crypto Trading API v2 adapter for account data, holdings, quotes, and order history, plus a separate execution adapter for limit-order submission and cancellation.

## Connect inside the Auto Trader dashboard

1. Sign in to the existing HTTPS Auto Trader dashboard.
2. Open **Broker connections** and find **Robinhood Crypto**.
3. Enter the Robinhood API key identifier (`rh-api-...`) and the matching raw 32-byte Ed25519 private signing key encoded as Base64.
4. Select **Save Robinhood connection**. The backend saves both values in a restricted `/state/config/robinhood_crypto.json` file (mode 0600), not GitHub or frontend JavaScript.
5. The dashboard attempts an authenticated account request and displays status, buying power and API-tradable eligibility. A successful saved configuration is not proof of API connectivity: the account lookup must also work.

Do not share signing keys in logs, screenshots, GitHub issues, or source code. Rotate keys if exposed. The credentials file is restricted by filesystem permissions but is **not encrypted at rest**; use TrueNAS dataset encryption and controlled backup access for stronger protection.

## Safety and execution status

The live-order implementation is available in `app/robinhood_crypto_execution.py`, but it is **not** wired to the shared autonomous trading worker. Neither saving credentials nor a successful account lookup enables real brokerage order execution. Live execution needs independently configured account permissions, risk limits, order-idempotency and reconciliation, and user approval. Existing Schwab live trading and paper trading remain separate.

Only the official Robinhood **Crypto** API is supported; this integration is not for equities or options.

## Testing

Run `python -m unittest discover -s app -q` and `node --check web/brokers.js`. All tests mock brokerage writes. Never submit real orders to test integration.
