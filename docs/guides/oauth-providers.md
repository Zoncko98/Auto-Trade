# AI connections: OAuth sign-in, Ollama, and broker market data

This document applies to the Auto Trader **v1.0.4** code line. Read [installation](../../INSTALL.md) first.

## Choose an AI provider during setup

| Provider | Authorization | What is supported | Important limitations |
| --- | --- | --- | --- |
| **Ollama on your LAN** | No provider account login | Enter endpoint + model, optionally pull from curated model list to remote Ollama computer | Host needs Ollama running and enough RAM/VRAM; no cloud subscription |
| **ChatGPT** | **Sign in with ChatGPT** (OAuth/OIDC + PKCE, user consent) | User-controlled Node companion retains OAuth tokens locally; restricted public-news classification endpoint connects to NAS | Must authorize ChatGPT plan usage separately. Inference is not automatically included just by account sign-in; first real-account end-to-end test pending |
| **Google Gemini API** | Google Cloud **OAuth via application default credentials** | Local Python companion uses the user's Google account and project OAuth token, with REST API classification | Requires Google Cloud project/API enablement and ADC login; not the Gemini website subscription. Live account E2E verification pending |
| Claude | No supported consumer-subscription OAuth bridge in this project | Developer API adapter may be configured separately | Do not reuse Claude web subscription tokens in an unapproved third-party tool |
| OpenAI-compatible provider | Vendor API key (optional legacy fallback) | Provider-specific HTTPS endpoint and model ID | Not OAuth; retained for APIs that do not support delegated account access |

**Provider passwords are never collected.** OAuth credentials stay on the separate user-owned AI computer. Auto Trader stores only the independent long random LAN bridge token to authorize its limited public-news requests. Cloud AI does not receive Schwab account data.

### ChatGPT OAuth — install on the AI computer, not the NAS

From the **ai-workstation** directory on the machine you control:

1. Install Node 20+ and run \`npm install\`.
2. Run \`node chatgpt_oauth.mjs connect\` on that same computer. Open the URL in its local browser, authenticate on the official OpenAI website and review the requested permissions. **Plan usage is a separate permission**, and access is subject to the account's eligibility and usage limits.
3. Run \`node chatgpt_oauth.mjs status\`. If sharing was authorized, it will say so without printing any tokens.
4. Create a long unique bridge secret in your password manager. Set \`AUTOTRADER_OAUTH_BRIDGE_TOKEN\` to it, \`AUTOTRADER_OAUTH_BIND\` to the AI computer's private LAN IP and \`AUTOTRADER_OAUTH_PORT\` to 8767. Run \`node chatgpt_oauth.mjs serve\`.
5. Restrict TCP 8767 to the NAS IP in the AI workstation firewall. In the Auto Trader installer choose **4 — ChatGPT OAuth**, enter the companion URL, your chosen authorized model, and the *same bridge secret*. The secret is not your ChatGPT OAuth token.

For example on Windows PowerShell:

\`\`\`powershell
cd D:\AutoTraderAI\oauth
npm install
node chatgpt_oauth.mjs connect
node chatgpt_oauth.mjs status
# Set these values privately in your own shell / service configuration.
$env:AUTOTRADER_OAUTH_BIND="192.168.1.100"
$env:AUTOTRADER_OAUTH_PORT="8767"
$env:AUTOTRADER_OAUTH_BRIDGE_TOKEN="<create-your-own-long-secret>"
node chatgpt_oauth.mjs serve
\`\`\`

This companion verifies the signed ID token (issuer, audience, nonce and JWKS), uses dynamic client registration, validates OAuth state/PKCE, checks the granted inference scope, and refreshes tokens when needed. The account credentials are kept in the local user profile, **not inside the NAS or GitHub**. It is an optional research integration, not a brokerage execution dependency.

Official reference: https://developers.openai.com/siwc/token-sharing-open-source/sign-in

### Gemini OAuth — Google Cloud ADC

On the AI computer, install Google Cloud CLI, Python and the \`google-auth\` and \`requests\` Python packages. Enable **Generative Language API** for your Google Cloud project. Follow Google's documented interactive consent flow:

\`\`\`sh
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/generative-language.retriever
\`\`\`

Set the same isolated bridge-token environment variable, \`AUTOTRADER_GCP_PROJECT\` to your own project ID, \`AUTOTRADER_OAUTH_BIND\` to the AI host's LAN IP, \`AUTOTRADER_OAUTH_PORT=8769\`, and start:

\`\`\`sh
python ai-workstation/gemini_oauth.py
\`\`\`

In Auto Trader setup choose **5 — Gemini OAuth**, enter \`http://AI_HOST:8769\`, an enabled Gemini model name and the bridge token. Restrict the listener to the NAS in your firewall.

Official reference: https://ai.google.dev/gemini-api/docs/oauth

### Ollama remote installation choices

\`\`\`sh
python3 installer/ollama_models.py --url http://192.168.1.100:11434 --list
python3 installer/ollama_models.py --url http://192.168.1.100:11434 --model qwen3.5:4b
\`\`\`

The interactive installer can do the pull for you. Ollama downloads **to its own AI computer**. Auto Trader doesn't install Chronos-Bolt or FinBERT as Ollama chat models; those remain separate Python models on the AI computer.

## Schwab market-data and forecast monitoring

Existing live-order logic already retrieves Schwab broker quotes and historical bars. v1.0.4 adds a **separate, read-only market-data collector** that can run without enabling live trading:

\`\`\`sh
docker compose --env-file /path/to/data/config/compose.env \
  -f deploy/docker-compose.yml --profile market up -d --build market-data
\`\`\`

It uses the same user-authorized Schwab developer token and app credentials, polls broker quotes every 20 seconds by default, and writes only sanitized symbol/price/bid/ask/quote-time data to \`state/live/broker_market_snapshot.json\`. The collector has **no buy/sell functionality**. It does not share account identifiers or credentials.

The authenticated Auto Trader \`/api/research/market\` endpoint displays fresh snapshots (60-second freshness threshold) in the five-candidate forecast screen and flags stale/missing quotes. This adds **broker-observed market monitoring**; it is not an exchange-certified, millisecond real-time feed. Current forecast ranking/calibration still uses historical price bars and chronological validation; it does not retrain on streaming quotes automatically. Some brokerage quotes may be delayed depending on data entitlements.

### Validation status

- **Verified with synthetic tests:** provider URL/schema restrictions, safe news payloads, broker quote normalization, timestamp expiry, model-output validation, Compose files, dashboard auth and prior trading safeguards.
- **Needs user authorization to verify end-to-end:** live ChatGPT OAuth consent + model inference, Gemini Google Cloud OAuth consent + model inference, and actual Schwab quote streaming entitlement on a separate install.
- **Not implemented:** Claude consumer subscription OAuth, automatic trading decisions from OAuth models, calibrated probabilities from broker streaming observations.

Public source should not misrepresent unperformed OAuth consent or real market-data tests. The optional adapters can be tested by users with their own authorizations, without supplying API keys where supported.
