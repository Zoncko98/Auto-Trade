# Operating, backing up and updating Auto Trader

**[Docs](../README.md) | [Schwab](schwab.md) | [Security](security.md) | [Troubleshooting](troubleshooting.md)**

These commands operate on a **portable installation** where the wizard generated `<DATA>/config/compose.env`. Replace sample paths with the actual host data directory.

## Observe status

```sh
# From the repository checkout:
docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml ps

docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml logs --tail=80 dashboard

curl -kfsS https://127.0.0.1:8765/health
```

The HTTPS port is configurable; if another value was selected, use that instead. The local certificate is initially self-signed.

## Paper simulation (optional)

```sh
docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml --profile paper up -d --build paper
```

Paper simulation remains separate from real brokerage activity and must not be confused with a validated live strategy.

## Backups

Back up **both**:
1. **Source version:** Git commit/tag/branch, or a clean Git archive. The archived v1.0.0 tag remains available for reference.
2. **Private persistent host data:** `config/`, `state/` (especially Schwab OAuth token, order ledger, operator state and history), `tls/` and any relevant `logs/`.

Stop relevant containers safely before taking a consistent filesystem snapshot. Do **not** delete or edit the order ledger if a brokerage order's outcome is still unresolved; reconcile with the broker first.

Recommended strategy: encrypted local and offsite backups with controlled retention. Snapshot the data folder using host storage features (ZFS, Btrfs, hypervisor disk backups) where applicable. **Never** push private state to GitHub.

## Upgrade / rollback procedure

1. Record the current Git commit, tag and resolved Compose version; capture a consistent backup.
2. Review release notes, schema changes, live-trader state and migration instructions.
3. **Do not re-run `install.sh` on an occupied data directory.** The wizard intentionally refuses to overwrite configured secrets.
4. On a maintenance window, check out a **tested, specific** release tag on a separate checkout or after making an explicit backup; validate Compose and unit tests.
5. Rebuild/recreate **dashboard only** initially, leaving the broker worker untouched:
   ```sh
   docker compose --env-file /srv/auto-trader-data/config/compose.env \
     -f deploy/docker-compose.yml up -d --no-deps --build dashboard
   ```
6. Verify HTTPS health, UI login, status, model endpoint and forecasts before considering any changes to the trading worker.
7. If rollback is needed, restore the matching code revision **and** any compatible persistent-data snapshot; avoid restoring stale order state over unresolved brokerage actions.

**Current status:** No automatic upgrade migration or fully-tested one-click rollback utility is shipped. The development branch is not a stable upgrade target for active broker execution.

## Safe shutdown

```sh
docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml stop dashboard paper
```

Stop the live profile only after checking open orders and order reconciliation; halting a worker does not necessarily cancel an accepted broker order.

## Fresh deployments vs existing installs

A clean install should use a new dedicated data directory and HTTPS port. Avoid sharing the existing production data path with an experimental install. Keep model services on separate LAN hosts if the NAS lacks compute capacity.
