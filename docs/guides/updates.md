# Auto Trader update notifications (private GitHub)

[Operations](operations.md) · [Security](security.md) · [Architecture](../architecture.md)

From **v1.0.1**, an authenticated dashboard can show **Update vX.Y.Z available** in the top bar.

## How the private-repo check works

- The **TrueNAS host**, not the dashboard container, uses an existing GitHub deploy SSH key.
- The read-only host checker, `tools/check_updates.py`, lists stable `vMAJOR.MINOR.PATCH` Git tags and stores `update_status.json` in persistent application state.
- The dashboard's authenticated `GET /api/update` compares that saved latest version against its own installed `/app/VERSION`.
- The browser checks that authenticated endpoint at login and every minute. Clicking the notice opens the new release's GitHub tag; it **never auto-installs code**.
- No GitHub key, OAuth token, Docker socket, or repository write permission goes inside the dashboard container.
- Prereleases (`-beta`, `-dev`) do **not** trigger stable update prompts.

## Scheduled host check on TrueNAS SCALE

Only configure this after securely enrolling the intended deploy key with GitHub and verifying SSH host keys. The key used by this private project is held on the **TrueNAS host**, not inside Docker.

Example command (adjust actual directories and key paths; run on the **host** with permissions to update the application state):

```sh
/usr/bin/python3 /mnt/POOL/apps/auto-trader/tools/check_updates.py \
  --repo git@github.com:Zoncko98/Auto-Trade.git \
  --state-dir /mnt/POOL/apps/auto-trader/state \
  --ssh-key /home/your-user/.ssh/auto-trader-github-readonly
```

Use TrueNAS **System Settings → Advanced → Cron Jobs** to schedule a check every **30 minutes**. Run it under a trusted account with access to the private host key and writable app state. Do not put the key contents or passwords in the Cron command. We recommend a dedicated **read-only** GitHub deploy key for update checks; a write-enabled key is unnecessary.

After each check, the JSON status is updated atomically. If GitHub is unreachable or auth fails, the checker fails rather than inventing a newer version; the dashboard may show the previous cached result until its next successful check.

## Important upgrade behavior

The v1.0.0 dashboard predates the notification feature. It cannot display a new update prompt before this feature is first installed. Install **v1.0.1** once as a bootstrap. From then on, later stable Git tags can trigger the notice.

**No forced updates or live-trader restarts.** An update must be reviewed and installed separately after a backup. The update notice merely alerts you and links to release notes.

### First-time setup / private repository

This is a private repository. The checker must authenticate with an authorized GitHub SSH deploy key and a trusted GitHub known_hosts entry. Do not expose `.ssh` into containers. Do not use the public GitHub API unauthenticated endpoint; it will not reliably report a private repository's releases.

For installation and backup details, see [operations](operations.md).
