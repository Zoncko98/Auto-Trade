# Schwab account-specific risk configuration (v1.2.4)

## User controls
- Strategy capital USD: explicit maximum account funding available to this automated strategy; effective cap is at most Schwab-verified equity.
- Cash allocation percent: how much verified spendable non-borrowed cash may support the next order.
- Per-order maximum dollars: order notional cap, cannot exceed strategy capital.
- Maximum position percent: per-order cap relative to the effective strategy capital.
- Daily loss USD: independent cap for new entries after observed equity drawdown. Not a guaranteed stop-loss and cannot exceed strategy capital.
- Open holdings (1–30), buys per day (1–30), total orders per day (1–100): all enforced from the saved policy. Total orders must be at least daily buys.
- Daily growth objective (0–25%) is reporting-only and NEVER forces trades.

These controls are available in the existing Schwab Risk & Start page and protected by the same authenticated, CSRF-controlled REST endpoint with optimistic revision checks. Previous documents with eight controls migrate in memory to a $100 strategy capital limit; no hidden risk increase occurs from upgrading alone.

## Order boundary
A BUY must separately pass live operator arm, Schwab API, account hash, broker-confirmed cash, broker equity, no margin debt, positions/journal reconciliation, complete market-data candles, permitted order session, whole shares, bid/ask freshness and spread, risk drawdown, daily order counts, candidate quality, AI approval and available cash/strategy exposure. Orders are journaled and fsynced prior to submission; failed or unknown outcomes require independent broker reconciliation rather than automatic replay.

## Initial adjustment
User-requested starting limits after deployment: strategy capital $100 unchanged, cash allocation 100% unchanged, maximum order $50, maximum position 50%, daily loss threshold $10, six holdings, six daily buys, fifteen daily orders, daily reporting target unchanged at 1%. The user can change every field in the Risk & Start screen. These increases are risky and do not guarantee trades; saved broker settings and order safety remain active.

## Rollback
Back up TrueNAS state and app config first. Previous immutable image schwab-monitor-87f44076f57e, and its predeployment ZFS snapshot, remain available. Restore exact prior risk document and previous image if rolled back.
