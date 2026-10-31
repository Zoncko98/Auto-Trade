# Unified Auto Trader installation on TrueNAS SCALE

The recommended setup is ONE installed TrueNAS app called auto-trader. It runs one Docker image:

  ghcr.io/zoncko98/auto-trade:stable

## Install using TrueNAS GUI only

1. Create a persistent directory/dataset, for example /mnt/Home/auto-trader.
2. In TrueNAS Apps > Discover > More Options > Custom App via YAML, set the name to auto-trader.
3. Copy the [single-container compose template](unified.yml) into Custom Config and replace POOL_NAME with the actual pool. Keep /state and /logs persistent.
4. Save. The image generates its own local HTTPS certificate and session secrets at startup.
5. In Apps > auto-trader > Workloads > Logs, copy the one-time pairing code. No NAS shell is required.
6. Open https://YOUR_NAS:8765. The browser may warn about the local self-signed certificate. Enter the pairing code and your chosen administrator username/password.
7. Select an Ollama endpoint, an authorized ChatGPT/Gemini OAuth companion, or AI disabled. You can optionally enter the Schwab developer app key and secret.
8. After signing in, open Profile > Configure AI, Ollama and Schwab connections. Click Connect Schwab, sign in on the official Schwab website, and paste the full final redirected URL into Auto Trader. Never enter your Schwab account password into Auto Trader.
9. Enable paper trading and optional market quotes through the same GUI. Live trading requires an additional Schwab account selection, explicit opt-in and the existing Allow Orders button.

## One-click updates

TrueNAS monitors the moving :stable image digest and can show an app update. There are no independent dashboard/paper/market app updates. The Source: N/A label may still appear because TrueNAS considers the installation a custom YAML app.

Keep /state during updates: passwords, tokens, journals, broker authorization, and risk settings remain outside the image.

## Migration

Do not start two live worker processes against one brokerage account. Use a temporary host port 8768 for validation if an old dashboard already uses 8765; after the new unified app has been configured and verified, retire legacy apps and move the new app to 8765 via TrueNAS GUI. Back up old state and token first. The old individual images are deprecated and no longer the standard release channel.

Cloud OAuth requires separate user consent on the AI workstation; choosing a provider in the GUI does not automatically authorize a third-party account. Live trading is OFF on every fresh installation.

## v1.0.7 Schwab callback and native updates

Default https://127.0.0.1:8182 points to the browser computer, not the NAS. Auto Trader does not start a listener on the PC. Therefore a browser connection error after Schwab consent is expected. Copy the entire redirected URL from the browser's address bar and paste it into Profile > Integrations > Finish Schwab connection. The URL contains a one-time OAuth code; never share it publicly.

Advanced alternative: If accepted and approved in the Schwab Developer Portal, register https://NAS_PRIVATE_IP:PORT/schwab/callback, and enter that exact address in the GUI. With HTTPS reachable, the NAS receives and finishes the callback automatically; changing the developer-app redirect can require reapproval. The loopback copy-and-paste flow remains supported.

Profile > Integrations shows administrator setup, AI setup, Schwab authorization and module status separately. Paper uses fake funds; market monitoring reads only broker quotes; live trading permits real orders only after a single confirmation popup and account validation.

Native TrueNAS: Custom YAML apps show Source: N/A because their catalog metadata has no upstream source. TrueNAS nonetheless detects new public image digests when image updates are enabled. The installed app uses ghcr.io/zoncko98/auto-trade:stable. The Auto Trader Profile links to GitHub and checks current stable release tags; the update itself happens through TrueNAS Apps. A TrueNAS catalog submission would be needed for populated native catalog source metadata.


## v1.0.8 — Schwab callback copy/paste bug fix

For a registered callback of https://127.0.0.1:8182 (without a slash), browsers can display https://127.0.0.1:8182/?code=...&state=... (with a slash). Earlier releases incorrectly called this a mismatch. v1.0.8 accepts these two ROOT-path forms as equivalent when processing the redirect, without changing the exact registered URL sent to Schwab. Scheme, host, port, state and non-root paths must still match. Start a fresh authorization after updating, since old OAuth codes may expire.

If the app reports a real mismatch, it now shows the expected versus received callback BASE addresses without one-time authorization codes. Confirm the expected address exactly matches the callback registered at https://developer.schwab.com/ . Auto Trader cannot inspect the Schwab developer portal registration on your behalf. If Schwab reports invalid_client before redirecting, its developer app may be configured differently or not yet Ready For Use.


## v1.0.9 NAS-only forecasting

Built-in forecasting needs only the one Auto Trader app and outbound historical price feeds; no separate model installation or TrueNAS app. The installer provides Automatic, Built-in NAS and optional Advanced Workstation modes, plus a selected AI public-news review checkbox. Current cloud OAuth connectors still require their authorized companion. See ../../docs/guides/forecast-research.md.
