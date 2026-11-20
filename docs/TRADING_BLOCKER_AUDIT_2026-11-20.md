# Trading execution blocker audit — November 20, 2026

## Production v1.2.4 observed at 2026-11-20 15:55 UTC
- TrueNAS custom app auto-trader RUNNING on original image; no second deployment.
- Schwab: worker heartbeat last updated roughly 23 hours ago; operator order mode running, journal 19 FILLED and no unresolved orders, no halt. Account snapshot and strategy decisions were similarly stale. The supervisor previously refused all automatic live-process restarts.
- Robinhood: crypto worker monitoring, broker order history VERIFIED, risk policy enabled. Recent decision was NOT_ARMED with reason No qualified technical entry or managed exit; this is a signal/eligibility observation, not evidence that the broker API is offline. Original historic performance was fee-negative, so no fee checks should be removed to force trades.
- Webull: worker RUNNING and stock scanning; trading policy enabled=false, stocks true, crypto false. No live orders should occur until the user explicitly reauthorizes this account in the dashboard. The worker cannot override broker account classes or buying power.
- Paper: 20 simulated trades, currently no holdings. Last reviews predominantly rejected by the AI news gate. That is strategy filtering; test alternate paper-only gates before considering any live change.

## Recovery change
- Worker catches recoverable LiveBlocked events before submission and publishes PRE_ORDER_BLOCKED telemetry with an unarmed heartbeat; the five-minute scan retries only after broker journal proven unhalted and all prior orders terminal.
- Supervisor can relaunch a stopped, explicitly enabled Schwab process only after checking intact journal with no open/replaced orders. Backoff 120 seconds; no more than 3 attempts per hour. Unknown, halted, unresolved or oversize journal -> no relaunch and visible warning.
- Supervisor and worker statuses are saved as private atomic files and surfaced via the existing authenticated Schwab dashboard.

## Acceptance tests
New synthetic tests cover order-journal terminality, crash restart eligibility, transient pre-order retry, unresolved order refusal, private telemetry and unified frontend rendering. Run full Python and JavaScript regression suites, publish immutable GitHub image, snapshot existing TrueNAS state, deploy existing app and verify new Schwab heartbeat, current account snapshot, broker and order status, Webull disarmed policy and Robinhood worker. Never place artificial live orders to make a test pass.

## Limitations
A worker online does not imply a trade is eligible or profitable. User-controlled disabled Webull trading cannot be enabled by a software fix alone. Robinhood fee-adjusted strategy and paper model gate are separate policy/strategy decisions. A zero-trades interval may occur even after workers are online. Do not wipe broker histories or risk settings merely to generate orders.
