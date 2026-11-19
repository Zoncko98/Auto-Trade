# Mobile-first Auto Trader and Robinhood indicative valuation — v1.2.1

## What triggered this change
An Android Chrome screenshot showed oversized two-column cards, three full-width portfolio performance blocks and one Robinhood holding with Partial $0.00 rather than a verified price. A read-only broker probe on the running TrueNAS container confirmed one active Robinhood account with a positive USDC holding; the v2 USDC-USD quote request returned RobinhoodUnavailable, while cash and holdings endpoints succeeded.

## Design references
- [Freqtrade FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) separates bot controls, performance, open trades and detailed charts.
- [Hummingbot Dashboard](https://hummingbot.org/dashboard/) exposes a portfolio view across multiple exchanges and strategies.
- Auto Trader uses a consistent account selector, a compact order-permission header, account metrics and a direct held-asset preview. Detailed execution checks remain behind optional disclosure. Mobile navigation retains Accounts, Overview, Risk and Activity, without creating a fifth trading dashboard.

## Portfolio pricing behavior
1. Continue to request signed Robinhood v2 bid/ask; use its valid midpoint when available.
2. For a verified Robinhood-reported USDC holding only, when the broker quote is absent, request independent usd-coin / USD price from CoinGecko over HTTPS.
3. Accept only an explicitly identified, recent (0–300s) finite positive USD quote. No $1 peg assumption is used.
4. Display the source and mark as indicative external, not a broker executable quote. If this quote is stale or unavailable, show Price unavailable rather than Partial $0.00 or a fabricated account value.
5. Never send CoinGecko marks into signal generation, AI approval, order sizing, broker order submissions, trading risk checks, or reconciliation.
6. Do not infer P/L from holdings alone. Robinhood v2 holdings have no official acquisition price; leave P/L unavailable without reconciled broker fills.

## Deployment
Reuse the TrueNAS auto-trader custom app on port 8765. The GitHub Actions image for this branch is ghcr.io/zoncko98/auto-trade:mobile-ux-<commit>. Preserve the existing app's Compose configuration, state mount and rollback image/snapshot. Validate live assets, authenticated view if available, and read-only broker holdings after deployment. No live orders are part of the verification.
