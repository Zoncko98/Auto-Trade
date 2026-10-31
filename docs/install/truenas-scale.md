# Install on TrueNAS SCALE

**[Installation hub](../README.md) | [Docker / Linux](docker-linux.md) | [AI & Ollama](../guides/ai-setup.md) | [Troubleshooting](../guides/troubleshooting.md)**

**Status: Existing home setup working; fresh portable install not yet end-to-end validated.** Targets TrueNAS SCALE **25.10+** and its Docker-based Apps environment. This guide uses a TrueNAS shell and a **source-built Compose application**, not the catalog or **Apps → Install via YAML** screen.

## Prerequisites

- Admin SSH or Shell access; an applications storage pool; working Git, Python 3, OpenSSL, Docker Engine and Compose plugin.
- A separate, empty dataset/folder for persistent data, such as `/mnt/POOL/apps/auto-trader-data`. Replace `POOL` with your actual pool.
- An unused HTTPS port (default 8765) and browser on the LAN.
- An authorized SSH key for this **private GitHub repo**. Do not copy secrets into a shared shell history.

**Do not re-run against an existing production directory**, such as one already holding broker tokens or order history.

## Shell setup

```sh
# Choose a suitable persistent checkout location on your pool.
mkdir -p /mnt/POOL/apps/auto-trader-src
cd /mnt/POOL/apps/auto-trader-src

# Private repo: requires approved GitHub SSH access.
git clone --branch main https://github.com/Zoncko98/Auto-Trade.git
cd Auto-Trade

# Verify prerequisites before installing:
docker compose version
python3 --version
openssl version

# First-time setup; builds/starts ONLY the dashboard.
sudo sh install.sh --platform truenas
```

The wizard asks for a **different** storage path, e.g. `/mnt/POOL/apps/auto-trader-data`; server LAN binding address (or `0.0.0.0`), HTTPS host port; long dashboard password; Ollama or compatible AI endpoint; optional forecast service; and optional Schwab developer app details.

Note: The original `v1.0.0` release tag is an archival snapshot of one machine and **not** this portable installer. The first setup creates private `config/*.env`, a self-signed TLS certificate, state and logs outside the checkout.

## Open and verify

```sh
# Replace POOL and DATA as configured by the wizard.
docker compose \
  --env-file /mnt/POOL/apps/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml ps

# Replace 8765 if you chose a different host port.
curl -kfsS https://127.0.0.1:8765/health
```

Use `https://TRUENAS-LAN-IP:8765` in a browser, accept the local self-signed certificate warning and sign in. A bind address of `0.0.0.0` is not a URL: substitute the NAS's actual IP.

**Do not deploy `--profile live` during the first installation.** Broker authorization is a separate, deliberate step described in the [Schwab guide](../guides/schwab.md).

## TrueNAS Apps user interface (future method)

TrueNAS offers **Apps → Discover → Install via YAML**, which accepts custom Docker Compose YAML; it is not currently a tested installation path for **this repository**. Our portable Compose file has a **source build context**, local env files and host-path dependencies. A self-contained YAML app needs published images and a properly prepared configuration/volumes manifest first. **Do not simply paste `deploy/docker-compose.yml` into the UI and expect it to work.**

Official guide: https://apps.truenas.com/managing-apps/installing-custom-apps/

## Storage and maintenance

Store state/config outside both the OS boot device and the Git checkout. Do not overwrite existing datasets; [back up and update carefully](../guides/operations.md). Avoid modifying a live trading container during installation tests.

**Tested:** Existing TrueNAS v1.0.0 deployment and LAN forecast connection; portable Compose config and setup unit tests. **Not yet tested:** a complete clean TrueNAS installation and UI catalog packaging.
