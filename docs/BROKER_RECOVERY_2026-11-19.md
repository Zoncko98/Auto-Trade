# Broker recovery audit — v1.2.2, 2026-11-19

## Observed deployment failure
Webull authorization returned HTTP 502 while official Webull SDK initialization raised HTTP 429 (shared application quota). Robinhood worker was marked offline because its order listing exceeded a 50-page ceiling; 51 pages successfully returned more than 1,000 orders.

## Fixes
- Webull: authenticated worker account snapshot may be reused for authorization (180s freshness and credential-change checks) only. A live order still independently verifies account, buying power, holdings, risk, and existing orders. UI GET requests use a short-lived SDK read cache and return controlled 503 when provider rate limits remain.
- Robinhood: orders listing retains full cursor validation with 250-page bound, and never returns a partial list as an authoritative empty or complete result. A broker history outage leaves a fresh degraded worker heartbeat and every order path blocked until reconciliation succeeds.
- No margin borrowing or account reclassification, no auto-arm, no real order test, no suppressed duplicate-order checks.

## Rollback
Revert the existing TrueNAS custom app to the prior immutable image mobile-ux-3fa8e2ba81a4 using the preserved Compose configuration and dataset snapshot. Do not create another app.
