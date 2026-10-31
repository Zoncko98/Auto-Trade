# Setup and account navigation — development branch

Status: Unreleased, on feature/workspace-account-tiles. The installed TrueNAS application remains at v1.0.11.

## Account protection

New setup or changed passwords: 10–256 characters, one uppercase A–Z letter, one 0–9 number, and one symbol. Existing stored passwords are not revalidated until voluntarily changed, so existing users continue to log in. Longer password-manager credentials are recommended. Server-side validation, PBKDF2 hashing, session revocation and login rate limiting remain in place.

## Where settings now live

| UI | Purpose |
| --- | --- |
| First-run setup | Pairing code, create administrator, choose AI provider/model. No brokerage authorization. |
| Profile > AI & Forecast Settings | Ollama or authorized companion URL/model; optional advanced forecast mode and connection test. No Schwab credentials. |
| Broker Connections > Schwab | Developer app key/secret, exact callback, official OAuth sign-in, verified account selection, quote monitoring and live order on/off with confirmation. |
| Paper > Risk Settings | Paper background simulator start/stop and independently controlled simulator risk limits. |
| Workspace tiles | Select active Schwab or Paper view; unsupported providers remain greyed out Coming Soon. |

All settings writes include only the fields owned by the current screen. The backend validates and merges the partial update with previously saved protected settings. Broker OAuth still validates state and the approved callback, and no credentials are displayed publicly.

## UI recommendations for the next polish pass

- A dashboard onboarding checklist with optional connection status cards instead of lengthy installation paragraphs.
- Hide advanced model and forecast fields in an expandable Advanced section; show model choice and a test button first.
- Consistent connection badges: Connected, Needs setup, Disconnected, Stale, each with the timestamp and source.
- Clearly distinguish total brokerage equity, settled available cash and paper simulation equity.
- Verify existing full-suite legacy test failures before catalog submission.

Tests: app/test_unified_setup.py, app/test_profile_update.py, app/test_password_policy_ui.py and tests/test_setup_pages.cjs.
