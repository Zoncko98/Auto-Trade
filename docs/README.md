# Installation & documentation center

**[Home](../README.md) | [TrueNAS SCALE](install/truenas-scale.md) | [Linux Docker](install/docker-linux.md) | [Unraid](install/unraid.md) | [Synology / QNAP](install/synology-qnap.md) | [Proxmox](install/proxmox.md) | [Windows / WSL2](install/windows-wsl.md)**

These links provide **GitHub README navigation resembling installation tabs**. GitHub's built-in top navigation cannot be customized with true tabs from Markdown.

## Select your host

| Host | Preferred deployment | Read first |
| --- | --- | --- |
| **TrueNAS SCALE 25.10+** | Shell/SSH + local Docker Compose build | [TrueNAS guide](install/truenas-scale.md) |
| **Ubuntu / Debian / Linux** | Docker Engine + Compose, `--platform docker` | [Docker guide](install/docker-linux.md) |
| **Unraid** | A separate Linux VM, or an administrator-managed Compose setup | [Unraid guide](install/unraid.md) |
| **Synology / QNAP** | Linux shell/VM with working Docker Compose | [NAS guide](install/synology-qnap.md) |
| **Proxmox** | Docker inside a dedicated Linux VM | [Proxmox guide](install/proxmox.md) |
| **Windows host** | Docker Desktop Linux containers + WSL2 Ubuntu | [Windows guide](install/windows-wsl.md) |

**Validation labels:** *Working installation* refers to the original project TrueNAS setup; *unit/Compose validated* refers to checks of the portable installer; *guide only* means no end-to-end test has yet been run on that platform.

## Configure and operate

**[AI & Ollama](guides/ai-setup.md) | [Schwab OAuth](guides/schwab.md) | [Backup, upgrade & rollback](guides/operations.md) | [Troubleshooting](guides/troubleshooting.md) | [Security](guides/security.md)**

Read the [architecture](architecture.md), [complete change history](../CHANGELOG.md), and [supported/untested feature matrix](status.md).

## First install checklist

1. Access this **private** GitHub repository using an authorized account/key; verify host OS and Docker/Compose support.
2. Select a dedicated empty persistent host directory (do **not** reuse a live install).
3. Run the relevant `install.sh --platform truenas` or `--platform docker` wizard.
4. Enter **only** application-side developer keys. Schwab website sign-in remains on Schwab's OAuth page.
5. Confirm only the HTTPS dashboard started. Inspect its `/health` endpoint and UI; do not enable live trading as part of installation.
6. Separately configure/test AI and any research service; confirm the forecast has trustworthy timestamps and flags.
7. Back up config, token data and order ledger **privately** before upgrading.

**Security:** No live broker orders are enabled automatically, and forecasts are not autonomous order instructions. Do not expose APIs to WAN.

## Known distribution constraints

The current Compose file **builds from source**, so you need the checkout, Docker build support and a shell. It is **not yet** a standalone image-based manifest for TrueNAS **Apps → Install via YAML**, Synology Container Manager Project, or an Unraid Community Applications entry. Those platform UI options are documented for future packaging, not presented as fully working one-click installers.
