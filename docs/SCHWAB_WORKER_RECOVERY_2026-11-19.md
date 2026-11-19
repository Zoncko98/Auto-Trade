# Schwab worker recovery — 2026-11-19

## Evidence
Production v1.2.2 on TrueNAS reported live worker stopped after BLOCKED: Market candles missing or stale, followed by repeated Live worker stopped; operator review required logs. Broker token, cash/positions, and account mapping were present. Snapshot and heartbeat aged out. A read-only live Schwab request then obtained valid completed 5-minute candles for NOK, F and BTG. The order journal had 16 FILLED entries and was not halted.

## Remediation
- Treat held-position candle gaps as a temporary market-data block: never act on an incomplete exit, and block ALL orders for the scan, record HELD_CANDLES_UNAVAILABLE and continue monitoring on schedule.
- When operator order permission is paused, refresh only Schwab account, positions, and portfolio market values once per minute. No exchange order submission, no journal reconciliation side effects from the paused monitor.
- Preserve the supervisor no-auto-restart rule for other failed live-order processes and suppress repeated stop notifications.
- Differentiate paused order scanning from a genuinely offline worker in the readiness UI.

## Safety and verification
Keep the preexisting account hash, risk configuration, broker cash-only limits and journal. No margin borrowing, stop-loss bypass, manual test orders or forced BUY/SELL. Live order permission must remain paused on deployment until the user explicitly starts it. Automated tests, actual TrueNAS container, read-only broker snapshot, and authenticated UI must be separately checked. A healthy process is not proof of accepted or filled trades.

## Rollback
Restore previous image ghcr.io/zoncko98/auto-trade:broker-recovery-87391fa0311f using the existing TrueNAS custom app. Preserve rollback snapshot and backup configuration before update.
