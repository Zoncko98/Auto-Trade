# Installing Auto Trader on TrueNAS SCALE

## Scope

This installation is intended for TrueNAS SCALE 25.10+ with Docker Compose.
The portable installer is being developed on the feature/truenas-portable-installer
branch. Stable v1.0.0 and v0.9.0-beta are preserved as immutable Git tags.

The portable installation is CLI-based. It builds the source from this repository
and starts an HTTPS dashboard container. It does NOT yet publish prebuilt images
or register a catalog entry in TrueNAS Apps. TrueNAS also supports custom apps
via Apps > Discover > Install via YAML, but that will require a published image
and corresponding validated custom-app manifest for a true one-click install.

## 1. New installation

Use a **different storage directory** from an existing production installation.
Do not run this wizard against /mnt/Home/trading-bot if that is already in use.

Prerequisites: TrueNAS administrator access, Git, Docker Compose, Python 3 and OpenSSL.
A mounted app storage pool is required.

From a TrueNAS shell:

    cd /mnt/POOL/apps
    git clone -b feature/truenas-portable-installer https://github.com/Zoncko98/Auto-Trade.git
    cd Auto-Trade
    sudo sh install.sh

Replace POOL with the name of your apps storage pool. The repository is currently
private; cloning requires repository access until the owner chooses to publish it.

During setup you choose:
- A dedicated data directory under /mnt/POOL/ (never inside the Git checkout).
- The NAS LAN IP to bind and an HTTPS port (8765 by default).
- A dashboard password, entered privately without command-line arguments.
- Ollama on a private LAN, or an OpenAI-compatible HTTPS provider API, or no AI.
- Optionally an independent read-only forecast service such as http://192.168.1.21:8766.
- Optionally Schwab *developer* app key, secret, and registered callback URL.

Configuration files are generated with permissions 0600 under the new data
directory's config/ folder. A locally generated TLS certificate is placed in
tls/. The certificate is self-signed, so browsers will show an expected warning.

All real broker order submission remains disabled by default. The live-trader
service is behind an explicit Docker Compose profile and is NOT started.

Visit https://YOUR_TRUENAS_IP:8765 and log in with your dashboard password.
If you entered bind address 0.0.0.0, replace it with your actual NAS IP in the URL.

## 2. Connection options

### Ollama (local network)
Supply a private endpoint, for example:

    http://192.168.1.21:11434

Use the API listener, NOT an Open WebUI browser URL. Check that the NAS can reach
GET /api/tags and that Ollama listens on a LAN interface. Pull a compatible model,
for example qwen3.5:4b, on the separate AI computer.

### Other AI APIs
The current adapter accepts OpenAI-compatible chat-completions endpoints.
Provide an HTTPS API origin, the completion route (e.g. /v1/chat/completions),
API key and exact model ID. Provider keys stay in a private env file.

This does not automatically support native Anthropic or Gemini protocols.
Their native SDK/API adapters are future additions. AI decisions only assess
public, timestamped news and cannot replace mechanical risk controls.

### Forecast service
For an independent Windows inference computer, enter its private LAN forecast
service URL, e.g. http://192.168.1.21:8766.
The dashboard displays the five ranked research candidates from the service.
No trading orders are issued by the forecast API.

## 3. Schwab authorization

Schwab credentials consist of your own developer APP KEY, APP SECRET and
registered CALLBACK URL. Do not enter your Schwab username or password in the
installer, dashboard, repository or shell command. User sign-in occurs only
on Schwab's website via OAuth.

After completing step 1 and configuring an approved Schwab developer application,
run this from the repository directory (adjust the data directory):

    docker compose \
      --env-file /mnt/POOL/apps/auto-trader/config/compose.env \
      -f deploy/docker-compose.yml \
      --profile live run --rm --no-deps --interactive --tty \
      --entrypoint python live-trader /app/schwab_oauth.py

This manual OAuth tool opens/prints the authorized Schwab login flow and asks for
the final returned redirect URL. It stores the resulting token privately in
state/schwab_token.json and refuses to overwrite a nonempty existing token.

**Authorization is not permission to trade.** Live orders still require a
brokerage account hash selected and verified separately, risk checks, and
deliberate opt-in. The live-trader container is NOT started by the installer.
Never enable LIVE_TRADING or resume operator mode without reviewing live risk
limits and using read-only account verification first.

## 4. Optional simulator

From the repository directory, run:

    docker compose --env-file /mnt/POOL/apps/auto-trader/config/compose.env \
      -f deploy/docker-compose.yml --profile paper up -d --build paper

Simulation is not a substitute for broker sandbox validation.

## 5. Upgrades and rollback

Tag v1.0.0 is the recoverable archival build; v0.9.0-beta is the previous build.
Back up your private data directory and OAuth tokens before updating. Never
replace a production config folder by re-running the first-time setup wizard.
Production deployment should pin a tested release tag, not track an unreviewed
feature branch.

## Security and limitations

- Repository cloning and Docker image builds are carried out on your TrueNAS.
- No Schwab password is stored by this application.
- The historical v1.0.0 snapshot contains machine-specific LAN configuration.
  The portable branch removes that hardcoding.
- Do not expose the dashboard, Ollama API, or forecast service directly to the internet.
- Historical forecasts are experimental and may underperform a trivial benchmark.
- Initial installation tests do not prove that trading will be profitable.
