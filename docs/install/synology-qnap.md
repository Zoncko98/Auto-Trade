# Synology DSM & QNAP QTS / QuTS installation

**[Installation hub](../README.md) | [Generic Docker](docker-linux.md) | [Unraid](unraid.md) | [Troubleshooting](../guides/troubleshooting.md)**

**Status: Guidance only. The current repository is not packaged for Synology Package Center, QNAP App Center, Synology Container Manager Project or QNAP Container Station UI.** CPU architecture and Docker feature availability vary by model and OS version.

## Option A — supported Linux VM or shell with Docker Compose

If your NAS can host an Ubuntu/Debian Linux VM, this is the preferred repeatable route. Install Docker Engine, Git, Python 3, OpenSSL and the Compose plugin, then follow [Docker / Linux](docker-linux.md) with `--platform docker`.

If your specific NAS offers a supported SSH Docker + Compose environment, the same CLI installer may work with persistent directories such as:

- Synology example: `/volume1/docker/auto-trader-data`
- QNAP example: a path under your verified persistent share mount, e.g. `/share/Container/auto-trader-data`

Paths are **examples only**. Check actual mount paths and ACLs on the NAS; ensure they are writable by the Docker daemon and aren't publicly shared. Do not create data in the app source checkout.

## Option B — native vendor UI (planned)

- Synology Container Manager includes **Projects** backed by Compose YAML: https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project?version=7
- QNAP Container Station can operate Docker containers; follow your device's current vendor documentation for applications, paths and Compose support.

The current `deploy/docker-compose.yml` uses `build:` paths relative to the Git checkout and references installer-created local env files. **It is not a complete standalone vendor UI manifest.** To support direct Synology/QNAP UI installation, we still need versioned container images plus model-safe volume and secret configuration templates.

## Device suitability

- The dashboard is lightweight, but the live worker has Python/Schwab dependencies; these have not been tested on every CPU architecture.
- **Do not run Chronos-Bolt or FinBERT on underpowered NAS hardware.** Deploy the optional model service on a separate Windows computer, following [AI guide](../guides/ai-setup.md).
- Protect state, tokens and TLS keys from shared folder browsing. Use LAN-only access.
- Always install dashboard first and leave live execution disabled.
