# TrueNAS production baseline (2026-11-02)

## Existing running deployment

- TrueNAS app: `auto-trader` (custom app; TrueNAS package label `1.0.0_custom`)
- Deployment image: `ghcr.io/zoncko98/auto-trade:stable` (mutable image tag)
- Persistent state: `/mnt/Home/auto-trader/state`
- Persistent logs: `/mnt/Home/auto-trader/logs`
- The production app remained running throughout this Git branch consolidation.
- Application source commit inside the deployed container has **not** been independently verified; do not treat the Git branch HEAD as a confirmed exact copy of the running container.

## Recovery points (stored on TrueNAS, not committed)

- ZFS snapshot: `Home@autotrader-pre-consolidation-20261102`, nonrecursive. Contains the `/mnt/Home/auto-trader` directory as part of the `Home` root dataset. May also contain other directories in that dataset.
- Git bundle: `/home/truenas_admin/auto-trader-backups/pre-consolidation-2026-11-02/all-branches.bundle`
- All old branch refs are saved in `git-refs.txt` in that backup directory.
- TrueNAS app metadata is saved as `truenas-app-instance.json` in the backup directory.
- The ZFS snapshot captures persistent data, **not** the container image. The Git bundle captures source history, **not** secrets or live container state.
- No credentials have been committed to GitHub.

## Development policy

Continue development on GitHub `main` (source VERSION 1.2.0) and use reviewed feature branches as needed. The source version is not proof that the existing TrueNAS image was upgraded; confirm the deployed image digest and runtime version independently. Preserve separate paper and live execution controls and do not send live brokerage orders as tests.
