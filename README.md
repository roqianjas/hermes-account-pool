# hermes-account-pool

Run several accounts of one provider in [Hermes Agent](https://hermes-agent.nousresearch.com/docs) and manage them from one command, `hermes account`. Add accounts with a verified email, see live usage per account, spread the load before an account runs out, park accounts for a while, see which bot is on which account, and get an alert when something needs you.

Version 3.4.3 · MIT · Hermes Agent ≥ 0.21 · Linux with systemd · Indonesian PDF guide in [`docs/`](docs/hermes-account-pool.pdf)

## Contents

- [Why this plugin](#why-this-plugin)
- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Install, update, uninstall](#install-update-uninstall)
- [Concepts](#concepts)
- [Adding and removing accounts](#adding-and-removing-accounts)
- [Command reference](#command-reference)
- [Alerts](#alerts)
- [How balance works](#how-balance-works)
- [The timer](#the-timer)
- [Providers](#providers)
- [Files and security](#files-and-security)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Limitations](#limitations)
- [Contributing, changelog, license](#contributing-changelog-license)

## Why this plugin

Hermes already keeps a pool of accounts per provider and moves a session to the next account when the current one hits a limit. What it does not do on its own:

| You want to | Plain Hermes | With this plugin |
|---|---|---|
| Add an account | `hermes auth add`, no check of which account you actually signed in as | `add` verifies the real email and throws away wrong or duplicate sign-ins |
| See how full each account is | Not shown | `usage`, live, parked accounts included |
| Avoid sessions waiting on a nearly full account | A session waits up to 600 s on a 429, then rotates | `balance` puts the least-used account first and benches accounts at ≥ 90% |
| Take an account out for a few hours | Delete it and sign in again later | `park --until 17:00`, login kept |
| Know which bot uses which account | Not shown | `who` |
| Hear about a dead login or a full pool | Not reported | Desktop and Telegram alerts |
| Recover accounts stuck after a network drop during a token refresh | Waits for the cooldown | Retried automatically every 5 minutes |

The plugin changes the pool only through Hermes' own `CredentialPool` API and uses no AI tokens.

## Quick start

```bash
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy                      # plugins, fill_first strategy, 5-minute timer

hermes account anthropic add alice@example.com   # one sign-in per account, verified
hermes account anthropic add bob@example.com
hermes account anthropic doctor                  # everything OK?
hermes account anthropic usage                   # live usage per account
```

From then on the timer keeps the pool ordered. Day to day you mostly need `usage`, `who`, `park` and `doctor`.

## Requirements

- Hermes Agent ≥ 0.21 on Linux. The timer needs systemd user services (`systemctl --user`).
- Two or more accounts of the same provider. Built-in usage support: Claude Pro / Max / Team (`anthropic`) and ChatGPT Plus / Pro / Team (`openai-codex`). Other providers get the generic commands (see [Providers](#providers)).
- Optional: `notify-send` (package `libnotify-bin`) for desktop alerts, and a Telegram bot configured in Hermes with `TELEGRAM_ALLOWED_USERS` for Telegram alerts.

## Install, update, uninstall

### Install

```bash
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
```

`install.sh` does five things:

1. Copies `account-pool` and `account-pool-tracker` to `$HERMES_HOME/plugins/` (default `~/.hermes/plugins/`) and enables `account-pool` in the **default profile only**.
2. Symlinks and enables `account-pool-tracker` in every profile under `$HERMES_HOME/profiles/`, so `who` can see every bot.
3. With `--set-strategy`: sets `credential_pool_strategies.<provider>: fill_first` in the default profile and every other profile. `balance` needs this (see [Concepts](#concepts)).
4. Installs and starts `hermes-account-balance.timer`, which runs `balance` every 5 minutes, and runs it once right away.
5. Runs `hermes account <provider> doctor`.

| Option | Effect |
|---|---|
| `--provider <name>` | Provider the timer balances (default `anthropic`). Repeat for several: `--provider anthropic --provider openai-codex`. Each gets its own `ExecStart` line. |
| `--set-strategy` | Set `fill_first` for each provider in every profile. Without it the strategy is left alone and `doctor` tells you if it is wrong. |
| `--no-tracker` | Skip the session tracker. `who` stays empty. |
| `--no-timer` | Skip the timer. Run `balance` yourself. |
| `-h`, `--help` | Show the options. |

A custom `HERMES_HOME` is respected and written into the service unit. Running sessions load the tracker after `/reset` or after a gateway or desktop restart.

Check the result:

```bash
hermes account anthropic doctor
systemctl --user list-timers hermes-account-balance.timer
```

### Update

```bash
cd hermes-account-pool
git pull
./install.sh                # add the same --provider options you installed with
```

The previous plugin folder is backed up to `$HERMES_HOME/plugin-backups/<name>.<timestamp>` (outside `plugins/`, so Hermes never loads it twice). Accounts, parked accounts, history and settings are kept. `install.sh` without `--set-strategy` leaves your strategy as it is.

### Uninstall

```bash
./uninstall.sh
```

It removes the timer, both plugins and the tracker symlinks. Your accounts in the credential pool are not touched. Parked accounts are **not** returned to rotation: the script warns you and asks first, so unpark them before uninstalling if you want them back. Data files and `credential_pool_strategies` stay; the script lists the files you can delete by hand.

## Concepts

**Credential pool.** Hermes keeps the accounts of each provider in one list in `~/.hermes/auth.json`. Every profile shares it, unless a profile was given its own pool by running `hermes -p <profile> auth add` (`doctor` warns about that).

**Strategy `fill_first`.** A new session takes the first healthy account in the list. When it hits a limit, Hermes moves the session to the next one. `balance` works by reordering the list, so it needs `fill_first`. With `round_robin` the order is reshuffled on every session and balancing has no effect.

**Account states.**

| State | Set by | In rotation | Ends when |
|---|---|---|---|
| `active` / `ok` | | yes | |
| `BENCHED` | `balance`, at ≥ threshold (90%) | no | the usage window resets, or usage drops under the threshold |
| `LIMITED` / `RATE LIMITED` | Hermes, after a 429 or 402 from the provider | no | the provider's reset time (or 1 hour) |
| `COOLING DOWN` | Hermes, after a failed token refresh (often a network drop) | no | `balance` retries the refresh every 5 minutes |
| `DEAD` | Hermes, when the provider rejects the refresh token | no | you run `relogin` |
| `PARKED` | you, with `park` | no, but the login is kept | you run `unpark`, or the `--until` time passes |

**Park, bench, remove.** Park is your decision and keeps the login. Bench is automatic and temporary. Remove deletes the login; using that account again needs a new sign-in.

**Adapter.** Usage and real-email lookups need each provider's own API. That code lives in one adapter per provider in [`providers.py`](plugins/account-pool/providers.py). Without an adapter the generic commands still work.

**Default profile only.** The `hermes account` command is installed in the default profile, so worker bots cannot add, remove or reorder accounts. Accounts added from the default profile are shared by every profile.

## Adding and removing accounts

Run these from the **default** profile (no `-p`).

### Add an account

```bash
hermes account anthropic list                 # make sure the email is not in the pool yet
hermes account anthropic add you@example.com
```

1. Answer `y`. Hermes prints a sign-in link.
2. Open the link in a browser that is signed in as **that** account: its own Chrome profile, or a private / incognito window where you sign in. Check that the page says `Logged in as you@example.com`; if not, click **Switch account**. A browser signed in as another account would hand Hermes that account instead.
3. If the page says **"Sign in again to continue"**, that is normal: Anthropic asks for a fresh sign-in when the browser's login is old. Click it and sign in as the same account. Plain `hermes auth add` gets the same page.
4. Authorize, copy the code, paste it into the terminal and press Enter.
5. Look for `Verified: you@example.com` and `Added ...`. The account is balanced right away.
6. Check it: `hermes account anthropic check` (real email) and `hermes account anthropic usage`.

```
$ hermes account anthropic add you@example.com
Add you@example.com to anthropic
  1. Open the sign-in link in a browser that is signed in as THIS account:
     its own Chrome profile, or a private / incognito window.
  2. Make sure the page says: Logged in as you@example.com  (otherwise: Switch account)
     "Sign in again to continue" is normal when that browser login is old.
  3. Authorize, then paste the code back here.
  The account is kept only if the sign-in really is that account and not a duplicate.
Continue? [y/N] y
   ... Hermes sign-in: open the link, authorize, paste the code ...
Verified: you@example.com
Added you@example.com (id=4f1c2a) to anthropic.
```

What `add` can answer:

| Situation | Message | Pool |
|---|---|---|
| Correct sign-in | `Verified ... Added ...` | account added and ordered |
| Browser signed in as another account | `Signed in as X, not you@example.com. The sign-in was discarded.` | unchanged |
| Browser signed in as an account already in the pool | `X is already in the pool as '...' (id=...). The duplicate sign-in was discarded.` | unchanged |
| Email already in rotation | `... is already in rotation. To sign it in again: ... relogin ...` | unchanged, refused before sign-in |
| Email is parked | `... is parked. Return it with: ... unpark ...` | unchanged, refused before sign-in |
| Sign-in failed | `Sign-in did not complete. Nothing was added.` | unchanged |
| You pressed Ctrl+C | `Cancelled (Ctrl+C). Nothing was added.` (exit code 130) | unchanged; a half-saved entry is removed |

After a `discarded` message, switch the browser to the right account (or use a fresh private window) and run `add` again. Running sessions keep their current account; the new account is used from the next session (or after `/reset`).

Options: `--yes` skips the confirmation. `--key` adds an API-key account instead of an OAuth sign-in: the plugin asks for the key without echoing it, so it never shows up on the command line or in `ps`.

### Remove an account

```
$ hermes account anthropic remove bob@example.com
Remove bob@example.com (id=9f2a02) from anthropic.
Its login is deleted; to use it again you must sign in again (add).
To take it out of rotation for a while instead: hermes account anthropic park bob@example.com
Delete it? [y/N] y
Removed bob@example.com.
```

The target can be an email or an id. `remove` refuses the last working account and also deletes parked accounts. To take an account out only for a while, use `park`.

### Avoid

- `hermes -p <profile> auth add`: that profile gets its own separate pool and stops using the shared accounts (`doctor` reports it).
- Plain `hermes auth add`: there is no email check, so labels can be wrong and duplicates can slip in.
- Copying Hermes' tokens to another app or machine: refresh tokens are single use, so one side gets signed out. Signing in to the same account separately in another app is fine.

### Codex

The same commands work for `openai-codex`: `hermes account openai-codex add you@example.com` with a ChatGPT sign-in, in a browser signed in as that account. This only puts the account in the pool. Making a profile use Codex (main model or fallback) is a normal Hermes setting.

## Command reference

```
hermes account <provider> <action> [target] [options]

  list                                  accounts in rotation and parked accounts
  check                                 health: dead, rate-limited, wrong label, duplicate, real email
  usage                                 live usage per account, parked included (adapter)
  who      [--minutes N]                which session is on which account (default 30 min)
  report   [--hours N]                  usage history: load per account, busiest hours (adapter)
  add      <email> [--key] [--yes]      sign in a new account: verified, no duplicates
  remove   <target> [--yes]             delete an account's login (parked accounts too)
  park     <target> [--until T]         take an account out of rotation
  unpark   <target>                     return a parked account to rotation
  relogin  <target> [--yes]             sign an account in again, verified, same label and position
  balance  [--dry-run] [--threshold N]  order by usage, bench >= N% (90), auto-recover, alerts
  doctor                                check strategy, timer, files, pools, alerts
  notify   [status|test|...]            alert channels: desktop and Telegram
  help                                  show the help
```

A **target** is an account label (email), its number in `list`, or its id. `unpark` takes a label or id. `hermes account`, `hermes account help`, `hermes account --help` and `hermes account <provider> help` all show the help.

The examples below are based on a real pool, with the accounts renamed and some times shortened for the page.

### list

```
$ hermes account anthropic list
[anthropic] in rotation (8):
  #1  erin@example.com                   id=12e90b  status=ok
  #2  frank@example.com                  id=025bb6  status=ok
  ...
  #8  heidi@example.com                  id=36c28f  status=ok
[anthropic] parked (1):
  -   ivan@example.com                   id=9e95ee  since 2026-10-10 18:07  until 2026-10-10 21:00
```

The order is the order new sessions take accounts in. Changes nothing.

### check

```
$ hermes account anthropic check
[anthropic] in rotation: 8   parked: 1
  OK #1 id=12e90b  label=erin@example.com
        account : erin@example.com
  ...
  -- parked  id=9e95ee  label=ivan@example.com  (since 2026-10-10 18:07)
  All accounts in rotation are healthy.
```

`account` is the real email reported by the provider (adapter needed). Problems appear as `issue` lines, and the exit code is 1 when any account needs attention.

| Issue | Meaning | Fix |
|---|---|---|
| `DEAD: sign in again` | The provider rejected the refresh token | `relogin <target>` |
| `RATE LIMITED (HTTP 429)` | The provider's own limit | Wait for the reset; Hermes uses other accounts meanwhile |
| `BENCHED by balance` | At or above the threshold | Nothing: released at the reset |
| `COOLING DOWN` | A token refresh failed, usually a network drop | Nothing: `balance` retries it |
| `WRONG LABEL: the real account is X` | The label is not the account that signed in | `relogin` in a browser signed in as the labelled account, or `remove` it |
| `DUPLICATE` | The same account is in the pool twice | `remove <id>` of one of them |

### usage

```
$ hermes account anthropic usage
[anthropic] 5-hour usage
  account                            state     used                          resets
  -- in rotation --
  frank@example.com                  active      2%  [....................]  21:00
  erin@example.com                   active      3%  [....................]  20:10
  dave@example.com                   active      3%  [....................]  21:30
  ...
  heidi@example.com                  active     17%  [###.................]  19:50
  -- parked (not used by Hermes) --
  ivan@example.com                   PARKED     29%  [=====...............]  20:30
```

- The percentages are the same numbers claude.ai shows as "Current session". For `openai-codex` the line ends with both windows, for example `(5h 12% · week 78%)`, and the stricter one is used.
- If the usage endpoint does not answer, the line shows the value the timer recorded last, `(last known, 3 min ago)`, at most 15 minutes old and only while that window has not reset. Otherwise it shows the reason, for example `n/a (usage endpoint rate-limited, retry in a few minutes)`, `n/a (sign-in rejected (401))` or `n/a (usage endpoint unreachable ...)`. API-key entries show `API key: no account usage`.
- Expired access tokens are refreshed first, the same way Hermes does when it uses an account. For parked accounts the new token pair is written back to the parked file at once, because refresh tokens are single use.

### who

```
$ hermes account anthropic who
[anthropic] sessions active in the last 30 min: 2
  erin@example.com                   (idle)
  frank@example.com                  (idle)
  ...
  heidi@example.com
      worker-2             cli       20261010_181340_51b808 claude-sonnet-5-5    4m ago
      worker-1             cli       20261010_181338_ad9f75 claude-sonnet-5-5    6m ago
```

Columns: profile, platform, session id, model, last API call. `--minutes 120` widens the window. A session that rotated shows `(moved from <account>)`. The data comes from the tracker plugin; a session appears after its next API call.

### report

```
$ hermes account anthropic report --hours 24
[anthropic] usage report: last 24h (45 snapshots, 5.7h covered, from 10-10 12:53)
  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.
  account                              used  share  peak  time >= 90%
  heidi@example.com                      17    28%   17%         0 min
  bob@example.com                        11    18%    9%         0 min
  carol@example.com                      11    18%   11%         0 min
  ...
  total                                  60
  Busiest hours: 18:00-19:00 (25), 13:00-14:00 (18), 17:00-18:00 (14)
  Time with EVERY account >= 90%: 0 min
```

- `used`: the sum of usage increases. 100 equals one full 5-hour window.
- `peak`: the highest value seen. `time >= 90%`: how long the account was nearly full.
- With at least 2 hours of data and some real load, the report adds advice: when every account was ≥ 90% at the same time, it suggests adding an account; when one account carried more than half the load, it points you to `who`.
- The default window is 24 hours (`--hours N`). History covers at least the last 14 days.

### park and unpark

```bash
hermes account anthropic park frank@example.com                    # until you unpark it
hermes account anthropic park frank@example.com --until 17:00      # today, or tomorrow if 17:00 has passed
hermes account anthropic park frank@example.com --until +2h        # also 90m, 1d
hermes account anthropic park frank@example.com --until '2026-10-12 08:00'
hermes account anthropic unpark frank@example.com
```

Parking moves the account and its login out of the pool into `account-pool-parked.json`. Hermes does not see it, and `usage` still shows its usage. A timed park ends at the first timer run after that time (within 5 minutes). The last working account cannot be parked. Typical uses: keep an account's quota free for your own use in claude.ai, or rest an account that is close to its weekly limit.

### balance

```
$ hermes account anthropic balance --dry-run
2026-10-10 18:39:48 [anthropic] balance (dry run):
  - order: frank(2%) > erin(3%) > dave(3%) > alice(4%) > carol(5%) > bob(7%) > grace(12%) > heidi(17%)
```

The timer runs `balance` every 5 minutes; you rarely need it by hand. `--dry-run` shows the plan without changing anything. `--threshold N` (1 to 100, default 90) sets the bench level. Other lines you may see: `unpark X (park --until ... reached)`, `recovered: X (token refresh retried)`, `bench X (93%) until 17:10`, `release X (40%)`. See [How balance works](#how-balance-works).

### relogin

```bash
hermes account anthropic relogin alice@example.com
```

Signs an OAuth account in again, for example after `DEAD` or `WRONG LABEL`. The new login is added first and its real email checked. If it matches, it replaces the old entry in the same position with the same label. If it does not, the new login is discarded and the old entry is left as it was. Parked accounts must be unparked first. Needs an interactive terminal to paste the code. Ctrl+C cancels cleanly.

### doctor

```
$ hermes account anthropic doctor
[anthropic] doctor
  OK    strategy fill_first in 6 profiles
  OK    every profile uses the shared account pool
  OK    session tracker active in every profile
  OK    auth.json permissions 600
  OK    account-pool-parked.json permissions 600
  OK    balance timer active, last run 2026-10-10 18:36:09 WIB
  OK    usage history last written 4 min ago
  OK    8 accounts in rotation, 1 parked
  OK    usage endpoint reachable
  OK    alert channels: desktop, telegram via default (delivery is tested with: ...)
  0 failure(s), 0 warning(s).
```

Run it after installing, after a Hermes update, or when bots behave oddly. Every FAIL or WARN line includes the fix. Exit code 1 when there is a FAIL. For a provider with no accounts it says `not in use, nothing to check`.

### notify

```bash
hermes account anthropic notify                       # status
hermes account anthropic notify test                  # send a test alert to every channel
hermes account anthropic notify desktop-off           # desktop-on to undo
hermes account anthropic notify telegram-off          # telegram-on to undo
hermes account anthropic notify telegram-via=<profile>  # send with another profile's bot
```

See [Alerts](#alerts).

### Errors and exit codes

Wrong input is refused with a short message:

```
$ hermes account anthropic lst
'lst' is not an action. Did you mean: list?
$ hermes account anthropic usage --hours 5
--hours only applies to: report
$ hermes account anthropic park frank@example.com --until 25:99
Cannot read --until '25:99'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'.
$ hermes account anthorpic list
Unknown provider 'anthorpic'. Providers in your pool: anthropic. All providers: hermes auth list
```

| Exit code | Meaning |
|---|---|
| 0 | Done |
| 1 | The command ran and found a problem: `check` or `doctor` failures, a discarded or failed sign-in, a refused remove, a confirmation answered with no (or Ctrl+D), `notify test` reached no channel |
| 2 | Wrong usage: missing or unknown action, provider, target or option |
| 130 | Cancelled with Ctrl+C |

## Alerts

| Alert | When | Sent |
|---|---|---|
| Account needs sign-in | An account becomes `DEAD` | Once per account |
| Every account above 80% | Every account in rotation is at or above 80% (adapter needed) | Once, plus a message when the pool recovers |

Alerts are sent by `balance`, so they need the timer. Channels:

- **Desktop**: `notify-send`, on by default.
- **Telegram**: on automatically when Hermes has a Telegram bot. The message goes with `hermes send` to the first user in `TELEGRAM_ALLOWED_USERS` (your private chat), using the default profile's bot. If the default profile has no working bot, use another profile's: `notify telegram-via=<profile>`.

Run `notify test` after setting up. Settings are stored in `$HERMES_HOME/account-pool.json`, created on the first change. You can also edit it; the alert level is `alert_all_above`:

```json
{"notify": {"desktop": true, "telegram": "auto", "telegram_via": "default"}, "alert_all_above": 80}
```

## How balance works

Each run, for one provider:

1. **Timed parks**: unparks accounts whose `--until` time has passed.
2. **Recovery**: retries the token refresh for accounts in a refresh cooldown.
3. **Usage** (adapter needed): reads every account's usage, refreshing expired access tokens first.
4. **Bench and release**: accounts at or above the threshold are benched until their window resets; benched accounts that dropped below it are released. Benches are marked `[account-pool]`, and limits set by the provider itself are never touched.
5. **Order**: least used first, then benched accounts, then accounts whose usage could not be read, then `DEAD` accounts.
6. **History**: one snapshot per run for `report` and for the `last known` fallback. Values taken from that fallback are never written back.
7. **Alerts** for new problems.

Safety rules:

- If **every** account is at or above the threshold, only accounts at 100% are benched, so the pool is never emptied for being nearly full.
- If no usage can be read at all, the order is left unchanged. Recovery, timed unparks and alerts still run.
- Running sessions are not moved. Moving a session to another account would throw away its prompt cache.

Why benching at 90% helps: when an account hits its limit, Hermes retries once and can wait up to 600 seconds before rotating. Benching just before the limit means new sessions start on an account with room.

## The timer

```bash
systemctl --user list-timers hermes-account-balance.timer           # status and next run
journalctl --user -u hermes-account-balance.service -n 20 -o cat    # recent runs
systemctl --user start hermes-account-balance.service               # run now
systemctl --user disable --now hermes-account-balance.timer         # stop
systemctl --user enable --now hermes-account-balance.timer          # start again
```

- **Interval**: `systemctl --user edit --full hermes-account-balance.timer`, change `OnUnitActiveSec=5min`. Every run reads each account's usage once, so do not go much below 5 minutes.
- **Threshold**: `systemctl --user edit --full hermes-account-balance.service`, add `--threshold 85` to the `ExecStart` line.
- **More providers**: re-run `./install.sh --provider anthropic --provider openai-codex`, or add one more `ExecStart=... account <provider> balance` line. `doctor` warns when the timer does not cover a provider that has accounts.

The timer uses no AI tokens; it only calls the usage endpoints.

## Providers

| Feature | Providers |
|---|---|
| `list`, `check`, `add`/`remove`, `park`/`unpark` (also `--until`), `who`, `doctor`, sign-in alerts, refresh-cooldown recovery | **Every provider in the credential pool** (OAuth and API-key entries) |
| `relogin` | Every provider with OAuth sign-in. Email verification needs an identity adapter. |
| `usage`, `report`, usage-based `balance`, "all accounts high" alert, real-email lookup | **Providers with an adapter.** Built in: **`anthropic`** (Claude Pro / Max / Team, 5-hour window) and **`openai-codex`** (ChatGPT Plus / Pro / Team, 5-hour **and** weekly window). |

Without an adapter, `usage` and `report` say so plainly, and `balance` still unparks timed parks, retries refresh cooldowns and sends sign-in alerts, but leaves the order unchanged.

**Codex.** The stricter of the 5-hour and weekly limits drives `balance`, and `usage` shows both (`5h 12% · week 78%`). A Codex account that is also signed in to Codex CLI or VS Code shares its quota with them. Hermes keeps its own Codex sign-in and never reuses `~/.codex/auth.json`.

**The plugin only manages accounts inside a provider.** Whether a profile uses a provider at all (main model, fallback order) stays a normal Hermes setting, and the plugin never changes it. A provider with no accounts yet is idle: `hermes account openai-codex doctor` says "not in use".

Adding an adapter for another provider is a single class; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Files and security

| Piece | Role |
|---|---|
| `plugins/account-pool/` | The `hermes account` command (`__init__.py`) and the provider adapters (`providers.py`). Default profile only. |
| `plugins/account-pool-tracker/` | A `post_api_request` hook that records `{profile, session, platform, model, account label}`. No commands, no tools, no tokens; it swallows every error so it can never break a bot. |
| `systemd/` | The service and timer templates used by `install.sh`. |

Data files, all mode `600`, in `$HERMES_HOME`:

| File | Content |
|---|---|
| `account-pool-parked.json` | Parked accounts. **Contains OAuth tokens.** |
| `account-pool-sessions.json` | Sessions and their account, last 24 hours (no tokens) |
| `account-pool-history.jsonl` | Usage snapshots, one per timer run. Trimmed to the last 14 days once the file passes 3 MB. |
| `account-pool-alerts.json` | Alerts already sent, so each incident is reported once |
| `account-pool.json` | Alert settings |

How tokens are handled:

- Tokens are never printed or logged. They only go into request headers to the provider's own endpoints.
- The plugin talks to the provider's API (usage, profile, token refresh) and, for alerts, to Telegram through Hermes' own `hermes send`. Nothing else.
- Refresh tokens can be single use. Every refresh is written back at once, under a file lock for parked accounts.
- API keys for `add --key` are read without echo inside the plugin, never from the command line.
- The repository's `.gitignore` excludes `*.json`, `*.jsonl` and `.env`, so state files cannot be committed by accident.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `usage` shows `n/a (usage endpoint rate-limited ...)` or `last known` | The usage endpoint was queried very often in a short time (by this plugin, other usage tools, or Hermes Desktop's model picker). This is the measuring endpoint, not your model quota. | Wait a few minutes. Bots are not affected, and `balance` keeps accounts without data after the others. |
| Sign-in page says "Sign in again to continue" | The browser's login is old (Anthropic policy) | Click it and sign in as the same account |
| `add` says `discarded` | The browser was signed in as another account, or as one already in the pool | Use that account's own Chrome profile or a fresh private window, then run `add` again |
| `Cancelled (Ctrl+C). Nothing was added.` | You pressed Ctrl+C during sign-in | Expected. Run `add` again when ready. |
| A bot says "retrying in 600s" | Its account hit a 429 before `balance` benched it | `hermes account anthropic balance`, then stop and resend the message in that session |
| `check`: `DEAD` | Login revoked, or the token was used by another app or machine | `hermes account anthropic relogin <email>` |
| `check`: `WRONG LABEL` or `DUPLICATE` | Added with plain `hermes auth add` while signed in as another account | `relogin` the right account, or `remove <id>` the extra entry |
| `who` is empty | Sessions started before the tracker was installed | `/reset` the session, or restart the gateway or desktop |
| No Telegram alert | The bot token of the sending profile is invalid | `notify test`; switch with `notify telegram-via=<profile>` |
| `report`: not enough history | The timer is off or was just installed | `doctor`, then wait for a few runs |
| A `--until` park did not end | The timer is off | `systemctl --user enable --now hermes-account-balance.timer` |
| `doctor`: strategy is not fill_first | A profile uses `round_robin` or another strategy | `hermes -p <profile> config set credential_pool_strategies.<provider> fill_first` |
| `doctor`: profiles with their OWN pool | Someone ran `hermes -p <profile> auth add` | Remove those entries in that profile (`hermes -p <profile> auth remove ...`) and add the accounts from the default profile |
| `doctor`: last run failed | The timer's last `balance` failed | `journalctl --user -u hermes-account-balance.service -n 20` |
| `hermes account`: unknown command | Run with `-p <profile>`; the plugin is in the default profile only | Run it without `-p` |

## FAQ

**My quota in claude.ai (or another usage tool) is fine. Why does `usage` say rate-limited?**
Two different limits. Your model quota is what the bots spend. The usage endpoint that tools read to *display* that quota has its own request limit. When it is hit, only the display is affected: bots keep running, and the plugin shows the last known value.

**Does the plugin use AI tokens?**
No. It reads usage and reorders the pool. No model is called.

**Does `balance` move running sessions to a less used account?**
No. A running session keeps its account until it hits a limit; moving it would discard the prompt cache. New sessions take the least used account.

**Does the plugin change my fallback provider or models?**
No. Fallback, models and which provider a profile uses stay in your Hermes configuration. The only setting the project writes is `credential_pool_strategies`, and only when you pass `install.sh --set-strategy`.

**Can I use the same account in claude.ai, Claude Code or Codex CLI at the same time?**
Yes, with a separate sign-in there. The quota is shared, so that use shows up in `usage`. Never copy Hermes' tokens to another app or machine.

**What happens if the provider changes the usage endpoint?**
`usage`, `report` and usage-based ordering stop, `doctor` reports FAIL, and Hermes' built-in rotation keeps working as before.

**Can a worker bot run `hermes account`?**
No. The command is installed in the default profile only, on purpose. Bots run the tracker, which only records which account they use.

**How many accounts do I need?**
At least two. `report` tells you when the whole pool was nearly full at the same time, which is the signal to add one.

## Limitations

- Usage comes from **undocumented endpoints**: `https://api.anthropic.com/api/oauth/usage` and `https://chatgpt.com/backend-api/wham/usage` (the one behind Codex CLI's `/status`). They can change or rate-limit without notice. The plugin sends the same client headers as Hermes' own usage fetcher.
- Anthropic weekly quotas are not exposed for Team accounts, so `balance` uses the 5-hour window for `anthropic`.
- Adapters exist for `anthropic` and `openai-codex`. The generic commands were tested for other providers with API-key entries only. The Codex adapter was verified read-only against a real ChatGPT Team account; `add` with a real Codex sign-in has not been run yet.
- `who` finds the agent object by scanning running thread frames. A future Hermes refactor may leave `who` empty, but it can never break the bots.
- `add` and `relogin` with OAuth need an interactive terminal to paste the code.
- Linux with systemd only, for the timer. The commands themselves work wherever Hermes runs.

## Contributing, changelog, license

- Adapters for more providers are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers the adapter interface, the rules for handling tokens, and how to test in a sandbox without touching your real pool.
- [CHANGELOG.md](CHANGELOG.md) lists every release.
- [`docs/hermes-account-pool.pdf`](docs/hermes-account-pool.pdf) is the full guide in Indonesian. `docs/make_doc.py` regenerates it (reportlab, DejaVu fonts).
- License: MIT, see [LICENSE](LICENSE).
