# Workspace trading-profile tiles

Included with v1.1.0, based on v1.0.18.

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

The combined v1.1.0 release integrates these UI changes with the v1.0.18 trading engine.


## Account equity on the tiles

- Schwab: displays Equity $X only when a fresh authenticated /api/live snapshot reports a finite broker account equity value, its timestamp is five minutes old or less, and the broker worker is online. A saved token or an offline/stale snapshot never masquerades as a current account balance. This is **total account equity**, not available buying power or free cash.
- Paper: displays Sim. equity $X from the authenticated /api/status simulator account. This value is virtual money. Numeric zero is displayed as zero; missing/invalid data displays Balance unavailable.
- Balance text is reset on logout/session expiry. No account balances are transmitted to logo sources or stored in browser local storage.
- Coming Soon brokers have no balance until their actual authorized account API exists.

## Official brand artwork and permissions

The workspace never hotlinks images from broker sites, uses random third-party logo PNGs, or assumes that a Creative Commons icon library automatically grants trademark rights.

Alpaca offers an [official external-use brand kit](https://alpaca.markets/newsroom), with usage guidance. The tile uses the unmodified official 02_light-alpaca-logo.png from the [external kit](https://files.alpaca.markets/webassets/alpaca-brand-external.zip). It identifies an inactive integration only, does not imply endorsement, and should be reviewed under current kit guidelines before public release.

Schwab's [terms](https://www.schwab.com/legal/terms) prohibit general trademark/logo reproduction without permission, so its logo was not copied. Webull, Robinhood and IBKR also lack a verified grant of redistribution rights in this review. Their cards use neutral, local navigational symbols (not official logos), pending an approved official asset or permission. This avoids claiming an unapproved logo is official.

Paper Trading keeps the requested wallet symbol. Once a provider authorizes a logo, an approved asset can be inserted into the same card layout with source and license notes.
