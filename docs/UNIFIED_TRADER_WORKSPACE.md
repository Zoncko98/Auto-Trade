# Unified Trader Workspace — Feature Branch

Branch: `feature/unified-trader-workspace-20261118`
Starting point: current deployed image's source commit `0914f2b76307887e36a410421c7165cc958163be` (v1.2.0).
Scope: presentation, startup ergonomics, and authorization-vs-order timing only. Includes the current Robinhood portfolio-history fallback fix from the new deployment baseline.

## Product flow

Every existing account (Schwab, Robinhood Crypto, Webull, Paper) uses the same visible composition:

1. **Account selector & navigation** — overview, risk/start, orders/activity. Additional account tools and shared AI/connection tools are collapsed by default.
2. **Account header & controls** — account type, current permission state, prominent Start, Pause, Risk settings, plus collapsed original actions.
3. **Four account metrics** — value/equity, available cash/buying power, holdings, bot order records, sourced from that account's existing API DOM IDs.
4. **Portfolio performance** — holdings valuation, unrealized P/L, and return when the existing adapter supports them. Holdings are expandable; simulated equity history is expandable in Paper.
5. **Execution status & details** — heartbeat, scanner, reconciliation, funding/permission diagnostics expandable.
6. **Activity & diagnostics** — additional journal tables and shadow-strategy results expandable.
7. **Risk configuration** — a short save-then-start guide and primary limits. Robinhood's advanced entry/exit/cooldown fields are expandable; nothing is silently discarded.

Existing account controls, field IDs, user/session authentication, CSRF token handling, API callbacks, and reporting remain intact. The implementation restructures DOM nodes in-place and uses HTML details/summary for keyboard-friendly disclosure rather than creating an unrelated dashboard.

## Startup behavior

**Configure risk** does not itself start real-money trading. Start on a live broker still requires explicit real-money authorization. The first eligible order can execute after Start; saving risk does not promise a signal, fill, or net profit.

- Schwab: the UI requests fresh live state, requires an active/armed and non-halted worker, confirms real-money intent, then calls the existing authenticated `/api/live/mode`. Pausing is allowed even if the worker heartbeat is unavailable.
- Robinhood: the UI loads a previously configured risk policy and active selected account, confirms real-money intent, and calls the existing signed-broker-validated `/api/robinhood/risk` to enable. New `disarm_policy` permits revocation without relying on the Robinhood API during outages.
- Webull: user saves a risk policy and selects permitted market/account. The existing `webullChangePermission` confirmation workflow arms execution. The authorization endpoint still verifies production environment, broker account identity, asset-class eligibility, and risk policy, but does **not** require momentary available cash or absence of open orders merely to arm scanning.
- Paper: Start delegates to the existing simulated-mode API and never accesses live brokerage orders.

## Safeguards explicitly preserved

At the **order submission boundary** all existing broker checks stay mandatory. In particular, Webull `_live_gate` still enforces authentication, production API, active market account/asset flags, stock market hours, pending-order journal, broker-reported open orders, fresh balance and settled margin cash, position limits, daily loss, actual buying power, and maximum notional/exposure. Robinhood `preflight` continues checking available buying power and broker minimum on every proposed buy. Robinhood live execution still uses signed orders, duplicate-order journals, broker reconciliations and strategy qualification. Schwab still requires its worker, operator mode, per-order risk and broker authorization. All live accounts are independent, and real broker fills are not inferred from mere order acknowledgement.

**Intentional distinction:** the user can authorize trading/scanning after saved risk and an eligible connected account even when temporary cash or pending-order conditions would prevent an order at that instant. The worker will block the actual order until these conditions become safe. There is no unconditional forced purchase.

## Verification

- Python stdlib unit tests on the feature working copy: 459 passed, 1 skipped (as of Nov 18, 2026).
- Existing and new JavaScript test files executed with Node.js 22 on the desktop. New contract tests cover layout, static-asset allowlist, start confirmations and remaining Webull order gates.
- Browser-rendered previews for all four workspaces use illustrative **sample data**, not real broker balances or production authentication. Screenshots are design evidence only.
- Feature branch was prepared against the exact deployed commit; production image/state was **not** changed by the design audit. No live orders were used as tests.

## Deployment / rollback

This is a feature branch. Rollout requires publishing the branch/image through the existing private image pipeline, applying the update to the existing TrueNAS custom app, then authenticated browser verification of each of the four dashboard flows and read-only broker status. Before deployment, back up application state and preserve the previously deployed image tag `robinhood-quality-0914f2b76307` for rollback. Never replace /mnt/Home/auto-trader/state with source checkout data or expose private credentials.

Do not label feature production-verified until the running container serves /unified.js and /unified.css correctly, users can sign in, all four accounts render actual authenticated broker state, Start/Pause status matches backend permission, and paper workflow completes without live broker orders.
