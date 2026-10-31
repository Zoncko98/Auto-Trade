# TrueNAS Apps updates from private GitHub Container Registry

[Documentation hub](../../docs/README.md) · [TrueNAS install](../../docs/install/truenas-scale.md) · [Backup/rollback](../../docs/guides/operations.md)

## What this changes

Auto Trader now has a CI pipeline that builds separate **linux/amd64** images for the dashboard, paper worker, and optional live worker. It pushes them to the **private** GitHub Container Registry (GHCR) on each stable release tag.

| Image | Service | Auto-start trading? |
| --- | --- | --- |
| `ghcr.io/zoncko98/auto-trade-dashboard:stable` | HTTPS dashboard | No |
| `ghcr.io/zoncko98/auto-trade-paper:stable` | Existing `tradepilot` paper container | Paper only |
| `ghcr.io/zoncko98/auto-trade-live:v1.0.3` | Separately gated live broker worker | Not deployed automatically |

The live-worker image is deliberately **version-pinned**, not tagged stable, to discourage accidental upgrades during open brokerage orders.

The workflow also produces immutable `:v1.0.x` tags for rollback, plus `:candidate` images on development pushes to `main`.

**Important:** `:stable` is intentionally mutable, allowing TrueNAS to recognize a **new image digest**. A pinned `:v1.0.x` tag stays fixed and does not itself signal new versions. Existing v1.0.x app release tags remain unchanged.

## First-time registry login (TrueNAS web UI only)

1. In GitHub, create a **personal access token (classic)** with the minimum `read:packages` scope, and ensure your account is allowed to pull the private Auto Trader GHCR packages. Depending on the package/repository access rules, `repo` scope may also be needed for private repository-linked packages. Keep the token secret and never paste it into Auto Trader, a support ticket, or this chat.
2. Open **TrueNAS → Apps → Configuration → Sign-in to a Docker registry** (menu naming can vary slightly).
3. Select **Other Registry**, set the registry URI to `https://ghcr.io`, use your GitHub username and the private token as its password. Save.
4. Enable **Apps → Configuration → Settings → Check for Docker image updates**.
5. Confirm the GitHub Actions release workflow has successfully published the private images before switching a running app to those images.

This step is required because TrueNAS cannot pull a **private** GHCR image using only the repository's SSH deployment key. GitHub Actions uses its own `GITHUB_TOKEN` when publishing, but TrueNAS requires separate pull credentials.

## Migrate the existing TrueNAS `tradepilot` app (web UI)

**Back up** the existing `/mnt/POOL/trading-bot/state`, config and logs first, preserving broker/order state. Do not overwrite, delete, or reset running state.

1. Open TrueNAS **Apps → Installed → tradepilot → Edit**.
2. In the existing custom app YAML, **replace the `build:` block** with:

   ```yaml
   image: ghcr.io/zoncko98/auto-trade-paper:stable
   ```

3. Keep all existing `env_file`, `volumes`, state paths, read-only protections, network settings and container identity.
4. Save. TrueNAS should pull the image via the private registry credentials and recreate the selected custom app.
5. Verify startup, persisted state, logs and paper trading safeguards before proceeding.

A reference YAML for new installations is at [tradepilot.yml](./tradepilot.yml). **Do not paste the template blindly into an existing configured instance**; it uses `POOL_NAME` placeholders and will not preserve installation-specific differences automatically.

## Dashboard in TrueNAS Apps

The dashboard currently runs as a **separate Docker Compose container**, not as the `tradepilot` app in the TrueNAS Apps list. Updating `tradepilot` alone does not update the dashboard.

To make it manageable from TrueNAS Apps:

1. After testing the private dashboard image, open **TrueNAS → Apps → Discover → ⋮ → Install via YAML** (custom app).
2. Use the [dashboard.yml](./dashboard.yml) template, replacing `POOL_NAME`, `NAS_LAN_IP`, `OLLAMA_LAN_IP` and any differing real mount paths. Reuse the existing persistent dashboard config, state, and TLS cert files.
3. The old `trading-dashboard` container must be **stopped or retired at a planned maintenance window** before the new TrueNAS-managed app binds HTTPS port 8765. Starting two containers on the same port will fail. Do not use `docker compose down` against the broader trading stack without first checking what it would stop.
4. Install the new TrueNAS custom app; verify HTTPS login, Profile, forecast and persistent state.
5. Confirm only one dashboard container owns the selected HTTPS port. Leave Schwab live worker independently managed.

This is an **intentional migration**, not a silent conversion. No service should be removed or restarted without a successful registry pull and a recoverable backup.

## Normal updates: no more shell

1. GitHub release tag is pushed → GitHub Actions runs tests and publishes a new `:stable` image for each component.
2. TrueNAS automatically checks the registry for updated image digests when **Check for Docker image updates** is enabled.
3. Open **Apps → Installed** to inspect the update indicator and apply the image update through the GUI.
4. Confirm the app starts and retained state is intact. For high-risk releases, review release notes and back up before clicking Update.

The TrueNAS **Source: N/A** field may stay that way: this remains a custom app, not an official catalog-managed package. The image-update indication and catalog-version upgrades are different mechanisms.

### Security and compatibility

- Repo and GHCR packages remain **private**.
- Never put GitHub tokens, Schwab tokens, dashboard passwords or private keys in YAML tracked by Git.
- Do **not** deploy the `auto-trade-live` image as part of ordinary GUI updates until its order-safety and broker reconciliation checks have been separately validated.
- `:stable` targets **linux/amd64** initially. Other architectures need a separately tested image build.
- Update detection in TrueNAS for the new private image has **not been confirmed** until the registry credentials are entered and one image update is applied through the Apps UI.
- The Auto Trader internal Profile release notice remains an independent feature and will not directly control the TrueNAS image updater.

Official references: [TrueNAS Apps settings](https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/), [TrueNAS custom apps](https://apps.truenas.com/managing-apps/installing-custom-apps/), [GHCR auth](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).


## Public release registry note

The GitHub source can be public while earlier GHCR packages remain private. Once the repository is made public, check each GitHub Container Registry package's **Package settings** and change its visibility to Public if desired; this is a separate GitHub setting. Only then can TrueNAS pull without a registry token. Do not include brokerage keys or personal configuration when editing TrueNAS app YAML.
