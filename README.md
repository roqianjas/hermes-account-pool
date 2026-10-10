# hermes-account-pool

Manage several accounts per provider in the [Hermes Agent](https://hermes-agent.nousresearch.com/docs) credential pool: park, inspect, track and balance them from one `hermes account` command.

Hermes already rotates to the next account when one hits a limit. This plugin adds the rest.

## Provider support

| Feature | Providers |
|---|---|
| `list`, `check`, `add`/`remove`, `park`/`unpark` (also `--until`), `who`, `doctor`, sign-in alerts, refresh-cooldown recovery | **Every provider in the credential pool** (OAuth and API-key entries) |
| `relogin` | Every provider with OAuth sign-in. Email verification needs an identity adapter. |
| `usage`, `report`, usage-based `balance`, "all accounts high" alert, real-email lookup | **Providers with an adapter.** Built in: **`anthropic`** (Claude Pro / Max / Team OAuth). |

Provider-specific code lives in [`plugins/account-pool/providers.py`](plugins/account-pool/providers.py). [CONTRIBUTING.md](CONTRIBUTING.md) explains how to add an adapter, for example for Codex or another provider with a quota endpoint. Without an adapter, `usage` and `report` say so plainly, and `balance` still unparks timed parks, retries refresh cooldowns and sends sign-in alerts, but leaves the order unchanged.

## Features

- **`add` and `remove`**: sign in a new account and verify its real email. A wrong-account or duplicate sign-in is thrown away, and the new account is balanced right away. `remove` asks for confirmation, refuses to delete the last working account, and also handles parked accounts.
- **Park and unpark**: take an account out of rotation without deleting its login, either until you unpark it or until a set time (`--until 17:00`).
- **`who`**: shows which session (profile, platform, model) is using which account.
- **`doctor`**: checks the whole setup in one command.
- **`relogin`**: signs an OAuth account in again, checks the real email when an adapter can, and keeps its label and position.
- **Alerts** by desktop notification and Telegram when an account needs sign-in, or (with a usage adapter) when every account is above 80%.
- **Auto-recovery** for accounts stuck in a cooldown after a token refresh failed during a network drop.
- With a usage adapter:
  - **Live usage** for every account, including parked ones (Anthropic: the 5-hour window).
  - **`balance`**: puts the least-used account first and benches accounts at ≥ 90% before they run out, so new sessions never wait in a 600-second retry on a nearly full account.
  - **`report`**: usage history, showing load per account, the busiest hours, and how long every account was full.

A systemd user timer runs `balance` every 5 minutes. It uses no AI tokens.

## Commands

```
hermes account <provider> <action> [target] [options]

  list                                  accounts in rotation and parked accounts
  check                                 health: dead, rate-limited, wrong label, duplicate, real email
  usage                                 live usage per account, parked included (adapter)
  who      [--minutes N]                which session is on which account
  report   [--hours N]                  usage history: load per account, busiest hours (adapter)
  add      <email> [--key] [--yes]      sign in a new account: verified, no duplicates (--key: API key)
  remove   <target> [--yes]             delete an account's login (parked accounts too)
  park     <target> [--until T]         take an account out of rotation (T = 17:00, +2h, 90m)
  unpark   <target>                     return a parked account to rotation
  relogin  <target> [--yes]             sign an account in again, verified, same label and position
  balance  [--dry-run] [--threshold N]  order by usage, bench >= N% (90), auto-recover, alerts
  doctor                                check strategy, timer, files, pools, alerts
  notify   [status|test|...]            alert channels: desktop and Telegram
  help
```

A target can be an account label (email), a list number, or an id.

```
$ hermes account anthropic usage
[anthropic] 5-hour usage
  account                            state     used                          resets
  -- in rotation --
  alice@example.com                  active      2%  [....................]  16:49
  bob@example.com                    active      3%  [....................]  17:00
  carol@example.com                  active     10%  [##..................]  17:10
  -- parked (not used by Hermes) --
  frank@example.com                  PARKED     30%  [======..............]  15:50
```

## Requirements

- Hermes Agent ≥ 0.21 on Linux, with systemd for the timer.
- Two or more accounts of one provider. After installing, add them from the **default** profile with
  `hermes account anthropic add you@example.com`. For OAuth, use a private/incognito browser window for each account.
- Optional: `notify-send` for desktop alerts, and a configured Telegram bot with `TELEGRAM_ALLOWED_USERS` for Telegram alerts.

## Install

```bash
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
```

`install.sh` does the following:

1. Copies both plugins to `$HERMES_HOME/plugins/` and enables `account-pool` in the default profile.
2. Symlinks and enables `account-pool-tracker` in every profile under `$HERMES_HOME/profiles/`.
3. With `--set-strategy`, sets `credential_pool_strategies.<provider>` to `fill_first` in every profile. `balance` needs this, because `round_robin` reshuffles the order on every session.
4. Installs and starts `hermes-account-balance.timer` (every 5 minutes).
5. Runs `hermes account <provider> doctor`.

Options:

- `--provider <name>`: the provider(s) to balance; repeat it for several (default: `anthropic`). Each one gets its own `ExecStart` line in the timer.
- `--no-tracker`, `--no-timer`.

Running sessions pick up the tracker after `/reset`, or after a gateway or desktop restart.

To remove everything, run `./uninstall.sh`. It leaves the accounts in your credential pool untouched.

## How it works

| Piece | Role |
|---|---|
| `plugins/account-pool/providers.py` | Provider adapters: usage, identity, and parked-token refresh. |
| `plugins/account-pool` | The `hermes account` CLI. It changes the pool only through Hermes' own `CredentialPool` API. Install it in the default profile only, so worker bots cannot change accounts. |
| `plugins/account-pool-tracker` | A `post_api_request` hook that records `{profile, session, platform, model, account label}`. It adds no commands or tools, stores no tokens, and swallows every error. |
| `systemd/` | A timer that runs `hermes account <provider> balance` every 5 minutes. |

Data files, all mode `600`, in `$HERMES_HOME`:

| File | Content |
|---|---|
| `account-pool-parked.json` | Parked accounts (**contains OAuth tokens**) |
| `account-pool-sessions.json` | Sessions and their account, last 24 h |
| `account-pool-history.jsonl` | Usage snapshots every 5 minutes, about 14 days |
| `account-pool-alerts.json` | Alerts already sent (one message per incident) |
| `account-pool.json` | Alert settings |

Each `balance` run:

1. Unparks accounts whose `--until` time has passed.
2. Retries the token refresh for accounts in a refresh cooldown.
3. With a usage adapter: reads the usage, benches accounts at ≥ the threshold until their reset, and orders the rest from least to most used.
4. Writes a history snapshot.
5. Sends alerts for new problems.

If every account is at or above the threshold, only the ones at 100% are benched. If usage cannot be read, the order is left unchanged.

## Limitations

- Only `anthropic` has an adapter today, and the other providers' generic commands were tested with API-key entries only.
- Anthropic usage comes from `https://api.anthropic.com/api/oauth/usage`, which is **not a documented API**. If it changes, `usage`, `balance` and `report` stop reordering accounts, `doctor` reports FAIL, and Hermes' built-in rotation keeps working.
- Running sessions are not moved to another account until they hit a limit. Moving them would throw away the prompt cache.
- Weekly quotas are not exposed for Team accounts.
- `who` finds the agent object by scanning running thread frames. A future Hermes refactor may leave `who` empty, but it never breaks the bots.
- Anthropic refresh tokens are single-use. Never share a Hermes login with another app or machine.

## Contributing

Adapters for more providers are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

[`docs/hermes-account-pool.pdf`](docs/hermes-account-pool.pdf) is the full guide, written in Indonesian. `docs/make_doc.py` regenerates it with reportlab and DejaVu fonts.

## License

MIT
