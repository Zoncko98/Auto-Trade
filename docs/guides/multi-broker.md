# Auto Trader: Multi-broker workspace

The goal is ONE self-hosted Auto Trader app with a single paper engine, shared forecasts and explainable AI reasoning, and independently authorized brokerage accounts. No separate TrueNAS app is installed for each broker.

## Implemented in v1.0.10

- The authenticated Broker connections page lists documented capabilities, actual connection status and the authorization approach for Schwab, Webull, Alpaca, Robinhood Crypto and Interactive Brokers.
- A common BrokerAdapter interface defines account listing, balances, positions, quotes, orders, submission and cancellation. Each feature must be implemented and validated per provider.
- The existing Schwab OAuth and live worker remain unchanged. All non-Schwab adapters fail closed, including live order submission and cancellation.
- Credentials stay outside source control and away from the frontend. The new discovery endpoint returns only public provider metadata and whether the existing Schwab token file exists, not a broker password or token. Saved tokens aren't proof of an active brokerage session.
- Paper trades, risk controls, AI forecast and TrueNAS update flow are unchanged.

## Official broker integrations verified October 2026

| Broker | Official connection | Auto Trader status |
| --- | --- | --- |
| Schwab | https://developer.schwab.com/ OAuth Trader API | Existing brokerage; authorize through Profile → Integrations |
| Webull | https://developer.webull.com/apis/docs/connect-api/about-connect-api/ (third-party OAuth), individual OpenAPI app keys | Provider discovery and contract; not yet linked |
| Alpaca | https://docs.alpaca.markets/us/docs/about-connect-api (OAuth and paper/live APIs) | Provider discovery and contract; not yet linked |
| Robinhood Crypto | https://docs.robinhood.com/ | Official Crypto Trading API only; stock brokerage API not verified |
| Interactive Brokers | https://www.interactivebrokers.com/docs/ (IB Gateway/TWS, eligible third-party Web API) | Provider discovery and contract; not yet linked |

### Webull specifics

Webull offers individual Trading OpenAPI with approved app keys/signatures and the separate third-party Connect OAuth integration. The latter requires platform application approval, issued client credentials and sandbox tests. Its OAuth tokens have refresh and expiry rules, so future integration must rotate and securely store them.

Official personal API: https://www.webull.com/help/faq/10512-Does-Webull-offer-API
Third-party OAuth: https://developer.webull.com/apis/docs/connect-api/authentication/

### Robinhood limits

Robinhood's published developer trading documentation is for crypto. We should not automate stock trading via undocumented consumer endpoints, account web scraping or password collection. An official general-equities API would be evaluated if later published or approved.

## Integration milestones

Phase 1 (v1.0.10): provider registry, official-capability matrix, safe adapter interface, authenticated workspace, regression tests, no additional order execution.

Phase 2 — Webull/Alpaca: Apply for required provider approval; implement sandbox OAuth/signature verification; list accounts and positions; live and historical market data; isolated paper simulation; order preview and reconciliation; then opt-in live orders after a separate permission and safety review.

Phase 3 — IBKR and Robinhood Crypto: Add approved IBKR Gateway/TWS or Web API connections with account/session handling. Robinhood's official integration is crypto only with distinct volatility, precision and risk controls.

## Account isolation requirements

1. Every broker and account gets its own credential store, order ledger, idempotency keys, loss limits, risk settings, pending-order reconciliation and trade history.
2. Every AI recommendation must include broker ID, permitted account, verified price source and timestamp before an adapter can prepare an order.
3. No automatic routing across brokers; one broker's failure never causes an order on another.
4. Broker connection and live-order permission are separate. Keep current cash-only Schwab worker isolated from experimental providers.
5. Respect provider rate limits, authorized scopes, session expiry, entitlements, trading hours and terms of service.
6. Aggregate balances read-only, with account/currency attribution and stale-data flags; never combine settled cash across brokerages as though transferable.

Developer interface: app/broker_workspace.py is the baseline. Do not import other brokers' trade clients into the existing Schwab live worker until their complete adapter is tested.
