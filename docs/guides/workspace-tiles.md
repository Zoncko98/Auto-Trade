# Workspace trading-profile tiles

Development branch: feature/workspace-account-tiles. **Not installed into the production v1.0.11 TrueNAS app.**

The sidebar Trading Workspace selector uses six account-style tiles. Only two are selectable while their underlying views exist:

| Tile | Status | On selection |
| --- | --- | --- |
| Charles Schwab | Live dashboard supported, may need broker sign-in | Opens existing Schwab live overview with broker positions/order journal, AI evidence and dedicated live risk settings |
| Paper Trading | Simulator available | Opens the existing paper overview, paper trade history and its separate risk settings |
| Webull | Coming Soon, disabled | No navigation or trading |
| Robinhood | Coming Soon, disabled | No navigation or trading; published official Robinhood API covers crypto rather than general stock orders |
| Alpaca | Coming Soon, disabled | No navigation or trading |
| Interactive Brokers | Coming Soon, disabled | No navigation or trading |

The new sidebar does not alter any live execution permission. If Schwab OAuth has been saved, its tile displays AUTH SAVED, which does not assert the token is fresh; without saved authorization it displays CONNECT ACCOUNT. The tile remains navigable so an authorized user can reach integrations and finish setup.

Other brokers remain disabled until an official account adapter actually supports authentication, balances, positions, account-specific risk settings and safe execution. In the longer term, each connected account can become its own tile only after account switching is implemented safely and tested.

Keyboard users can activate available tiles with Enter or Space. Disabled tile buttons cannot be selected. Active selection is marked with aria-pressed. Sidebar and dashboard adapt to narrow screens.

## Quality checks

- Standalone HTML structure and accessibility regression tests: app/test_workspace_tiles.py
- JavaScript syntax verification: node --check web/app.js
- Existing live/paper UI tests: app/test_frontend_v2.py
- Existing broker capability tests: app/test_broker_workspace.py
- Visual review in headless Chrome at desktop and compact widths

No production update or new release is created by these development changes.
