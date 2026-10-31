# One-app installation (recommended)

Please use the [GUI-first TrueNAS guide](deploy/truenas-apps/README.md). The following standalone installer is a legacy/advanced alternative.

# Auto Trader — choose an installation guide

**[TrueNAS SCALE](docs/install/truenas-scale.md) | [Linux Docker](docs/install/docker-linux.md) | [Unraid](docs/install/unraid.md) | [Synology & QNAP](docs/install/synology-qnap.md) | [Proxmox](docs/install/proxmox.md) | [Windows/WSL2](docs/install/windows-wsl.md)**

The complete [documentation hub](docs/README.md) contains platform-specific prerequisites, deployment commands, AI integration, Schwab OAuth setup, backup and troubleshooting instructions.

The **v1.0.0** tag is an archived working-system snapshot, **not** the portable install branch. Fresh installations should use `feature/truenas-portable-installer` (v1.1.0-dev) and an **empty, dedicated data directory**; never point the wizard at a running production instance.

For new TrueNAS installations:

```sh
git clone --branch main https://github.com/Zoncko98/Auto-Trade.git
cd Auto-Trade
sudo sh install.sh --platform truenas
```

For a standard Linux server with Docker Engine and the Compose plugin:

```sh
git clone --branch main https://github.com/Zoncko98/Auto-Trade.git
cd Auto-Trade
sudo sh install.sh --platform docker
```

**After the GitHub repository is set Public, HTTPS cloning works without a GitHub account.** If a user has authorized HTTPS credentials instead, they can use the corresponding HTTPS repository URL. The installer builds the dashboard image locally; it does not publish a prebuilt image.

The wizard asks for your private host data path, server binding address/port, dashboard password, optional AI services and Schwab **developer app** credentials. It creates TLS files and private configuration outside Git and starts **dashboard only**. **Never enter your Schwab website login password.**

Read [platform instructions](docs/README.md) and [current limitations](docs/status.md) before installing. No clean-hardware multi-platform acceptance test has been completed yet.


[AI OAuth provider setup, Ollama models, and broker feed](docs/guides/oauth-providers.md).
