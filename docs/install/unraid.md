# Unraid installation guide

**[Installation hub](../README.md) | [Linux Docker](docker-linux.md) | [Proxmox](proxmox.md) | [Current status](../status.md)**

**Status: Guidance only. No Unraid package or end-to-end install has been tested.**

Unraid includes Docker and the popular Community Applications catalog, but **does not natively include Docker Compose as an officially integrated Unraid app configuration method**. Auto Trader has **not** been submitted as an Unraid Community Applications template. Official reference: https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/overview/

## Recommended approach: a small Linux VM

1. Create an Ubuntu/Debian VM on Unraid with appropriate disk/network resources.
2. Install Docker Engine + the Docker Compose plugin inside that VM.
3. Assign persistent storage inside the VM or a carefully configured share; avoid attaching live broker token directories to an unsecured share.
4. Follow the standard [Linux Docker instructions](docker-linux.md) using `--platform docker`.
5. Access the dashboard on the VM's LAN IP/HTTPS port. Configure optional Ollama and forecast services independently.

The VM approach avoids depending on unofficial Unraid host-level Compose plugins.

## Advanced alternative: administrator-managed Compose on Unraid

If you already operate a compatible third-party Compose plugin or SSH-managed Docker Compose environment, you may adapt the [Linux guide](docker-linux.md) with a persistent path such as `/mnt/user/appdata/auto-trader-data`. This is **untested**; ensure the tool's YAML parser supports source `build:`, profile services, bind mounts, `--env-file` and restricted file permissions. The installer needs a POSIX shell, Python 3 and OpenSSL on the environment where it runs.

**Do not treat a YAML paste into the Unraid Docker UI as a tested installation**; a proper Unraid template and image publication remain future work.

## Important safeguards

- Start dashboard-only; live profile stays off.
- Do not store OAuth tokens on broadly shared SMB/NFS folders.
- Use the [Schwab guide](../guides/schwab.md) for separate broker authorization, and [operations](../guides/operations.md) for backups and updates.
- Do not open public WAN ports for dashboard, Ollama or research services.
