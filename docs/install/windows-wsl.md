# Windows / Docker Desktop / WSL2

**[Installation hub](../README.md) | [Linux Docker](docker-linux.md) | [Separate Windows AI service](../../ai-workstation/README.md)**

**Status: Guide only; no full Windows Docker Desktop installation verified.** The primary Auto Trader containers are **Linux images**, not native Windows services.

## Recommended setup

1. Install Docker Desktop with Linux-container / WSL2 integration enabled; consult https://docs.docker.com/compose/install/.
2. Install an Ubuntu WSL2 distribution and confirm `docker compose version` works **from within the Ubuntu shell**.
3. Install Git, Python 3 and OpenSSL within Ubuntu. Keep the repository and Docker bind-mounted data on a **Linux filesystem** (e.g. `/home/your-user/apps/Auto-Trade` and `/home/your-user/auto-trader-data`) rather than a Windows network share.
4. From the WSL2 Ubuntu terminal, follow [Linux Docker instructions](docker-linux.md) with `sh install.sh --platform docker`. Use a new Linux data directory.
5. Publish only the selected dashboard HTTPS port through Docker Desktop and verify LAN reachability. WSL2/Windows firewall/port forwarding behavior varies by Docker Desktop configuration; not yet tested for this project.

**Do not run `install.sh` directly in PowerShell:** it is a POSIX shell script. The optional **Windows AI workstation** is a different component with its own PowerShell setup instructions: [ai-workstation README](../../ai-workstation/README.md).

The experimental live worker uses Linux-specific mechanisms such as file locking; it therefore runs **inside Linux containers**, not as a native Python Windows trading service.

## Security

Windows Defender Firewall should limit access to approved LAN devices. Keep TLS keys and Schwab token files in Linux-only protected paths, not synced consumer cloud folders. Start dashboard-only; do not automatically enable brokerage orders.
