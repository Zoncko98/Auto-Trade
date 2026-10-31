# Install on standard Linux / Docker Engine

**[Installation hub](../README.md) | [TrueNAS](truenas-scale.md) | [AI & Ollama](../guides/ai-setup.md) | [Schwab](../guides/schwab.md)**

**Status: Installer/Compose validated; fresh Ubuntu/Debian installation still needs an end-to-end test.** Use any reasonably current Linux host with Python 3, OpenSSL, Git, Docker Engine and the Docker Compose plugin. Use **Linux containers**, not Windows containers.

## Prepare the host

Install [Docker Engine and Compose](https://docs.docker.com/compose/install/linux/) through your distribution's supported method. Confirm:

```sh
docker version
docker compose version
python3 --version
openssl version
git --version
```

Choose a **new empty** host data directory such as `/srv/auto-trader-data`. The installer creates the configuration, TLS, state and logs folders; do not reuse old production data. Ensure Docker has read/write access to that directory.

## Clone and configure

```sh
mkdir -p ~/apps
cd ~/apps
git clone --branch feature/truenas-portable-installer git@github.com:Zoncko98/Auto-Trade.git
cd Auto-Trade

# Interactive wizard + dashboard build.
sudo sh install.sh --platform docker
```

The repository is private; the SSH clone requires an approved GitHub account/key. If Docker Engine is available to an unprivileged user, run without sudo **only if** the user can create and protect the chosen storage folder.

During the wizard, select:
- Persistent data path (e.g. `/srv/auto-trader-data`), LAN host binding and HTTPS port (8765 default).
- Dashboard password (at least 20 supported characters; use a password manager).
- External Ollama IP/model, or an OpenAI-compatible HTTPS endpoint, or AI disabled.
- Optional research API and Schwab developer app credentials. No Schwab website login password is requested.

Only the dashboard is started. The script builds from checked-out source; it does not pull a published Auto Trader image.

## Check service

```sh
docker compose \
  --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml ps

curl -kfsS https://127.0.0.1:8765/health

docker compose \
  --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml logs --tail 60 dashboard
```

Then open `https://SERVER-LAN-IP:8765` and sign in.

For a separate paper simulation, see [operations](../guides/operations.md). **Never activate the live profile until Schwab OAuth, account selection and broker checks are complete.**

## Docker-host differences

- On SELinux distributions, bind mount labels and permissions can require host-specific work; not tested.
- On ARM NAS devices, build compatibility for all Python dependencies has **not** been validated.
- Docker Desktop and WSL2 need a different host filesystem strategy; use the [Windows guide](windows-wsl.md).
- If port 8765 is occupied, choose another during setup; don't expose the API through a WAN port forward.
- The `--platform docker` option accepts Linux paths beyond `/mnt/POOL`. This does not imply a vendor-specific app integration.

Official references: https://docs.docker.com/compose/gettingstarted/ and https://docs.docker.com/reference/cli/docker/compose/up/
