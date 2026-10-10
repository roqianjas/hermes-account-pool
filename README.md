# hermes-account-pool

Run several accounts of one provider in [Hermes Agent](https://hermes-agent.nousresearch.com/docs) and manage them from one command, `hermes account`, or from an Accounts page in Hermes Desktop. Add accounts with a verified email, see live usage per account, spread the load before an account runs out, park accounts for a while or on a weekly schedule, see which bot is on which account and how many tokens each bot uses, and get an alert or a daily summary.

Version 3.7.0 · MIT · Hermes Agent ≥ 0.21 · Linux with systemd · Indonesian PDF guide in [`docs/`](docs/hermes-account-pool.pdf)

## Contents

- [Why this plugin](#why-this-plugin)
- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Install, update, uninstall](#install-update-uninstall)
- [Concepts](#concepts)
- [Adding and removing accounts](#adding-and-removing-accounts)
- [Command reference](#command-reference)
- [Hermes Desktop page](#hermes-desktop-page)
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
| Keep an account free at the same hours every week | Not possible | `schedule <account> --every "mon-fri 09:00-17:00"` |
| Know which bot uses which account | Not shown | `who` |
| Know how many tokens each bot uses, and what that would cost on the API | Not shown | `report`: tokens per account, bot and model, priced at API list prices, and the load per hour for the last 7 days |
| Hear about a dead login or a full pool | Not reported | Desktop and Telegram alerts, and an optional daily summary |
| Recover accounts stuck after a network drop during a token refresh | Waits for the cooldown | Retried automatically every 5 minutes |
| See all of it in one place | Not shown | The Accounts page in Hermes Desktop |

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

From then on the timer keeps the pool ordered. Day to day you mostly need `usage`, `who`, `park` and `doctor`. In Hermes Desktop, restart the app once and switch the page on in Capabilities > Plugins to get the same in a page ([Hermes Desktop page](#hermes-desktop-page)).

## Requirements

- Hermes Agent ≥ 0.21 on Linux. The timer needs systemd user services (`systemctl --user`).
- Two or more accounts of the same provider. Built-in usage support: Claude Pro / Max / Team (`anthropic`) and ChatGPT Plus / Pro / Team (`openai-codex`). Other providers get the generic commands (see [Providers](#providers)).
- Optional: `notify-send` (package `libnotify-bin`) for desktop alerts, and a Telegram bot configured in Hermes with `TELEGRAM_ALLOWED_USERS` for Telegram alerts.
- Optional: Hermes Desktop with desktop plugins, for the Accounts page. Tested with Hermes Agent 0.21.5.

## Install, update, uninstall

### Install

```bash
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
```

`install.sh` does six things:

1. Copies `account-pool` (with the Hermes Desktop page) and `account-pool-tracker` to `$HERMES_HOME/plugins/` (default `~/.hermes/plugins/`) and enables `account-pool` in the **default profile**, where the command lives.
2. Adds `account-pool` to `plugins.enabled` of every profile under `$HERMES_HOME/profiles/`, for the Accounts page in Hermes Desktop ([why](#why-every-profile-lists-account-pool)). Profiles get no command and no tools from it. A profile with `account-pool` in `plugins.disabled` is skipped.
3. Symlinks and enables `account-pool-tracker` in every profile, so `who` can see every bot and tokens are counted for every bot.
4. With `--set-strategy`: sets `credential_pool_strategies.<provider>: fill_first` in the default profile and every other profile. `balance` needs this (see [Concepts](#concepts)).
5. Installs and starts `hermes-account-balance.timer`, which runs `balance` every 5 minutes, and runs it once right away.
6. Runs `hermes account <provider> doctor`.

| Option | Effect |
|---|---|
| `--provider <name>` | Provider the timer balances (default `anthropic`). Repeat for several: `--provider anthropic --provider openai-codex`. Each gets its own `ExecStart` line. |
| `--set-strategy` | Set `fill_first` for each provider in every profile. Without it the strategy is left alone and `doctor` tells you if it is wrong. |
| `--no-tracker` | Skip the session tracker. `who` stays empty and no tokens are counted. |
| `--no-timer` | Skip the timer. Run `balance` yourself. |
| `-h`, `--help` | Show the options. |

A custom `HERMES_HOME` is respected and written into the service unit. Running sessions load the tracker after `/reset` or after a gateway or desktop restart. The Accounts page needs two more steps in Hermes Desktop, see [Turn the page on](#turn-the-page-on). A profile created after the install needs `./install.sh` again (or `hermes -p <profile> config set plugins.enabled` with `account-pool` added) before Hermes Desktop can show the page while it runs that profile; `doctor` names such profiles.

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

The previous plugin folder is backed up to `$HERMES_HOME/plugin-backups/<name>.<timestamp>` (outside `plugins/`, so Hermes never loads it twice). Accounts, parked accounts, history and settings are kept. `install.sh` without `--set-strategy` leaves your strategy as it is. Restart Hermes Desktop after an update so it loads the new page and its backend.

### Uninstall

```bash
./uninstall.sh
```

It removes the timer, both plugins (the Accounts page included), the tracker symlinks and the `account-pool` entry in each profile's `plugins.enabled`. Your accounts in the credential pool are not touched. Parked accounts are **not** returned to rotation: the script warns you and asks first, so unpark them before uninstalling if you want them back. Data files and `credential_pool_strategies` stay; the script lists the files you can delete by hand.

## Concepts

**Credential pool.** Hermes keeps the accounts of each provider in one list in `~/.hermes/auth.json`. Every profile shares it, unless a profile was given its own pool by running `hermes -p <profile> auth add` (`doctor` warns about that).

**Rotation strategy.** Which account a new session takes is a Hermes setting, per profile and provider: `credential_pool_strategies.<provider>`. The plugin reads it (the Accounts page shows it, `doctor` checks it) and leaves it to you.

| Strategy | A new session takes | With this plugin |
|---|---|---|
| `fill_first` (Hermes' default) | the first usable account in the list | **Use this.** `balance` puts the account with the most quota left first, so each new session starts on it. |
| `round_robin` | the next account in turn, which then moves to the end of the list | Fights `balance`: both rewrite the order, and turns ignore how much quota is left. |
| `least_used` | the account this computer picked least often | Counts picks, not quota: use in claude.ai or Claude Code is not seen. |
| `random` | any usable account | The order `balance` sets is ignored. |

`fill_first` plus the balance timer is a rotation by quota: the top spot moves to whichever account has the most room, every 5 minutes. `install.sh --set-strategy` sets `fill_first` in every profile.

**Running sessions keep their account.** The order decides where a *new* session starts. A running session stays on its account until that account hits a limit; then Hermes moves it to the next usable account, which `balance` keeps the least used. So the accounts with sessions on them drift down the list as their usage grows, and the top account is usually idle: it is waiting for the next session. A session picks its account again after `/reset`, in a new chat, or after a gateway or Hermes Desktop restart. Moving running sessions earlier would throw away their prompt cache, and resending a long context costs more quota than it saves.

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

**Default profile only.** The `hermes account` command is installed in the default profile, so worker bots cannot add, remove or reorder accounts. Accounts added from the default profile are shared by every profile. (Every profile lists `account-pool` in `plugins.enabled` for the Hermes Desktop page, but the command and everything else stay in the default profile, see [Why every profile lists account-pool](#why-every-profile-lists-account-pool).)

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
  report   [--hours N] [--chart]        load and tokens per account, bot and model, API price;
                                        --chart: load by hour for the last 7 days
  add      <email> [--key] [--yes]      sign in a new account: verified, no duplicates
  remove   <target> [--yes]             delete an account's login (parked accounts too)
  park     <target> [--until T]         take an account out of rotation
  unpark   <target>                     return a parked account to rotation
  schedule [<target> --every SPEC]      park an account every week at set hours; no target: list
  unschedule <target>                   remove an account's park schedule
  relogin  <target> [--yes]             sign an account in again, verified, same label and position
  balance  [--dry-run] [--threshold N]  order by usage, bench >= N% (90), auto-recover, alerts
  doctor                                check strategy, timer, files, pools, alerts
  notify   [status|test|summary|...]    alert channels (desktop, Telegram) and the daily summary
  help                                  show the help
```

A **target** is an account label (email), its number in `list`, or its id. `unpark` takes a label or id. `hermes account`, `hermes account help`, `hermes account --help` and `hermes account <provider> help` all show the help.

The examples below are based on a real pool, with the accounts renamed. Clock times are illustrative.

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
[anthropic] usage report: last 24h (288 snapshots, 23.9h covered, from 10-10 06:20)
  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.
  account                              used  share  peak  time >= 90%    tokens     API $
  bob@example.com                       126    27%   60%         0 min     2.7M     $1.53
  carol@example.com                     117    25%   60%         0 min     2.8M     $1.45
  alice@example.com                     112    24%   60%         0 min     3.0M     $1.45
  dave@example.com                      106    23%   60%         0 min     2.5M     $1.23
  total                                 461                               10.9M     $5.66
  Tokens through Hermes: 18.8k input, 252.3k output, 10.1M cache read, 567.8k cache write
  647 requests.
  API $ = these tokens at the provider's API list prices (a subscription is billed flat).
  By profile (bot)                  tokens  requests     API $  share
    worker-1                          5.6M       353     $2.54    51%
    worker-2                          2.4M       136     $1.10    22%
    default                           1.9M       102     $1.72    17%
    worker-3                          1.1M        56     $0.29    10%
  By model                          tokens  requests     API $  share
    claude-sonnet-5-5                 8.0M       489     $3.64    73%
    claude-opus-5-5                   1.9M       102     $1.72    17%
    claude-haiku-4-5                  1.1M        56     $0.29    10%
  Busiest hours: 08:00-09:00 (26), 10:00-11:00 (24), 12:00-13:00 (24)
  Time with EVERY account >= 90%: 0 min
  Load by hour for the last 7 days: hermes account anthropic report --chart
```

- `used`: the sum of usage increases. 100 equals one full 5-hour window.
- `peak`: the highest value seen. `time >= 90%`: how long the account was nearly full.
- `tokens`: the tokens Hermes sent and received on the account in the period: input, output, cache read and cache write, summed. The two lines under the table split the total and count the requests. The session tracker counts them on every API call from version 1.1.0 on, so a period that starts earlier says `counted since`. `-`: no call counted.
- `API $`: what those tokens would cost at the provider's API list prices, per model (input, output, cache read and cache write each at their own price). A subscription is billed flat, so this is what the use is worth, not a bill. Prices come from Hermes itself: its bundled price list, else its models.dev cache; the plugin makes no request for them. `+` means some tokens have no known price (a model without a listed price, or tokens counted before tracker 1.3.0, which did not record the model); those are left out, not guessed.
- `By profile (bot)` and `By model` split the same tokens by the Hermes profile that made the call and by the model. Tokens counted before tracker 1.3.0 show as `(before tracker 1.3.0)`; they leave the report within 8 days.
- `used` and `tokens` measure different things. `used` is the provider's own percentage, which includes the account's use in other apps (claude.ai, Claude Code) and weights token types differently (a cache read costs much less than an output token). `tokens` covers only Hermes on this computer.
- With at least 2 hours of data and some real load, the report adds advice: when every account was ≥ 90% at the same time, it suggests adding an account; when one account carried more than half the load, it points you to `who`.
- The default window is 24 hours (`--hours N`). History covers at least the last 14 days.

`--chart` draws the load per hour for the last 7 days, one row per day, one column per hour (local time). The darker the cell, the more load; `·` is none. The first block is quota used (from the timer's history), the second tokens through Hermes:

```
$ hermes account anthropic report --chart
[anthropic] load by hour (local time; one row per day, one column per hour)
  Load by hour, last 7 days: quota used (5-hour-window percent). Darkest = 26 in one hour.
             00 03 06 09 12 15 18 21
  Mon 10-05  ························
  ...
  Sat 10-10  ······▒██▓█▓██▓▓▓▓█▓▓█▓▓
  Sun 10-11  ▓█▓███░·················
  Load by hour, last 7 days: tokens through Hermes. Darkest = 710.6k in one hour.
             00 03 06 09 12 15 18 21
  ...
```

### park and unpark

```bash
hermes account anthropic park frank@example.com                    # until you unpark it
hermes account anthropic park frank@example.com --until 17:00      # today, or tomorrow if 17:00 has passed
hermes account anthropic park frank@example.com --until +2h        # also 90m, 1d
hermes account anthropic park frank@example.com --until '2026-10-12 08:00'
hermes account anthropic unpark frank@example.com
```

Parking moves the account and its login out of the pool into `account-pool-parked.json`. Hermes does not see it, and `usage` still shows its usage. A timed park ends at the first timer run after that time (within 5 minutes). The last working account cannot be parked. Typical uses: keep an account's quota free for your own use in claude.ai, or rest an account that is close to its weekly limit. For the same hours every week, use a [schedule](#schedule-and-unschedule).

### schedule and unschedule

```
$ hermes account anthropic schedule dave@example.com --every "mon-fri 09:00-17:00"
Schedule saved [anthropic]: dave@example.com is parked Mon-Fri 09:00-17:00.
Next: Mon 10-12 09:00.
Unparking it by hand inside a window keeps it in rotation until the next window.
Undo: hermes account anthropic unschedule dave@example.com

$ hermes account anthropic schedule
[anthropic] park schedules: the balance timer parks the account when a window starts and returns it when it ends.
  dave@example.com                   Mon-Fri 09:00-17:00          next Mon 10-12 09:00
Remove: hermes account anthropic unschedule <target>
```

A schedule parks an account on set days and hours, every week. Use it when you work in claude.ai or Claude Code with that account at fixed hours and want Hermes to leave its quota alone then.

- `--every` takes days and a time range in local time. Days: `mon` to `sun`, ranges (`mon-fri`, `fri-mon`), lists (`sat,sun`), `daily`, `weekdays`, `weekend`. A range that ends before it starts runs past midnight: `daily 22:00-06:00`. One schedule per account; saving again replaces it.
- The timer applies it: on its first run after the window starts it parks the account until the window's end, with the same timed park as `park --until`, so it comes back on the first run after the end. `list` and the page mark such a park `(schedule)`.
- Each window is applied once. Unpark the account by hand inside a window and it stays in rotation until the next window. An account you parked yourself is left as it is.
- The last working account is never parked; the timer tries again on its next run.
- `unschedule <target>` removes the schedule. If the schedule has the account parked at that moment, it stays parked until the window ends; `unpark` it to return it sooner.
- Schedules are stored in `account-pool.json` by label, so they survive `relogin`. A schedule whose account was removed shows as `not in the pool` and `doctor` warns about it.

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
  OK    Accounts page backend enabled in every profile
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
hermes account anthropic notify daily=08:00           # daily summary at 08:00; daily-off to stop
hermes account anthropic notify summary               # send the summary now
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
| 1 | The command ran and found a problem: `check` or `doctor` failures, a discarded or failed sign-in, a refused remove, a confirmation answered with no (or Ctrl+D), `notify test` or `notify summary` reached no channel, `unschedule` of an account without a schedule |
| 2 | Wrong usage: missing or unknown action, provider, target or option |
| 130 | Cancelled with Ctrl+C |

## Hermes Desktop page

`account-pool` also brings an **Accounts** page to Hermes Desktop: the pool, its usage, who is on which account, and the actions of `hermes account`, behind buttons. The command keeps working as before; the page uses the same code.

### Turn the page on

1. Run `install.sh` (it copies the page and lists `account-pool` in every profile).
2. Restart Hermes Desktop. The desktop starts the page's backend together with the other enabled plugins, so the page has no data until this restart.
3. In **Capabilities > Plugins**, find **account-pool** (Agent + Desktop; its desktop name is Accounts) and switch on its **Desktop** half. The page ships switched off, so nothing appears until you do.

**Accounts** now appears in the sidebar. The command palette (Ctrl+K, ⌘K on macOS) has `Accounts: open the account pool`, and the status-bar chip opens it too.

### Why every profile lists account-pool

Hermes Desktop runs its backend under the profile you last used (`hermes --profile <name> serve`), and a backend loads a plugin's page routes only when the plugin is in `plugins.enabled` of **that** profile. With `account-pool` in the default profile alone, the page works while Desktop runs the default profile and shows `The account-pool backend did not answer` while it runs any other.

So `install.sh` adds `account-pool` to `plugins.enabled` of every profile. Nothing else changes in those profiles:

- The agent in a profile loads plugins from that profile's own `plugins/` folder, and `account-pool` is not there (no symlink, unlike the tracker). Bots get no command, no tool and no hook from it.
- If a profile ever does load it, `register()` sees the profile and registers nothing. `hermes -p <profile> account ...` stays an unknown command.
- The page's backend always works on the shared pool in the default Hermes home, whichever profile Desktop runs.

`doctor` checks this when Hermes Desktop has the page: `Accounts page backend enabled in every profile`, or a warning naming the profiles that miss it.

### What the page shows

The header has a provider switch (providers with accounts in the pool, plus the two with built-in adapters), **Live usage**, **Balance now** and **Add account**. The line under it says how old the usage numbers are and when the timer runs next.

| Tab | Content |
|---|---|
| Accounts | The header line shows Hermes' rotation strategy (hover for what each one does); a banner names any profile that does not use `fill_first`, with the command that fixes it. Five cards: accounts in rotation, parked accounts, the account the next session starts on with its usage, sessions in the last 30 minutes, tokens in the last 24 hours with their API price. Then the rotation table in pool order: status, 5-hour usage bar, trend over the last 5 hours, reset time (or `back HH:MM` while benched), tokens in the last 24 hours (hover for input, output, cache, requests, API price, the main model and the current 5-hour window), the profiles using the account (hover for session, platform, model, since when the session is on this account, and the account it moved from) and the row buttons **Sign in again**, **Park**, **Park on a schedule** and **Remove**. A calendar chip next to an account shows its schedule. Parked accounts follow with their last known usage, since when they are parked, when they return (`(schedule)` when a schedule parked them), and **Unpark**, **Park on a schedule** and **Remove**. Then the park schedules, with what each one does now (parked until, next window, or `not in the pool`) and buttons to change or remove it. Active alerts show as a banner on top, a dead account with a **Sign in again** button. |
| Report | The `report` numbers for 24 hours, 3 days or 7 days: load per account, share, peak, time at 90% or more, tokens and their API price, busiest hours and the advice line. Then tokens by profile (bot) and by model, and a chart of the load per hour for the last 7 days (quota used or tokens; hover a cell for its numbers). |
| Health | Timer state, age of the usage history, active alerts. **Run doctor** runs the `doctor` checks; **Check accounts** runs `check` and shows its output. |
| Alerts | Desktop and Telegram switches, the profile whose bot sends Telegram alerts, the daily summary (switch and time), **Send a test alert**, **Send the summary now**, and the alerts active now. |

**Park** asks when the account comes back: when you unpark it, in 1 hour, in 2 hours, or at a time you type (`17:00`, `+90m`, `2026-10-12 08:00`, the same formats as `--until`). **Park on a schedule** asks for the days and the hours (`09:00` to `17:00`), the same as `schedule --every`. **Remove** and **Balance now** ask before they act. Every action reports the same message as the command.

The **status-bar chip** reads `8/8 · 12%`: 8 of 8 accounts in rotation are usable, and the account the next session starts on is at 12%. A dot appears when an alert is active (amber) or no account is usable (red). The chip hides while the provider has no accounts or the backend is not loaded.

### Add an account or sign in again from the page

1. **Add account**, type the account's email, **Start sign-in**. For an existing account, use the key button on its row (or **Sign in again** on a dead-account banner); that is `relogin`.
2. **Anthropic**: click **Copy link** and open the link in a browser signed in as that account (its own browser profile, or a private window). Check `Logged in as ...`, authorize, copy the code, paste it into the page and click **Finish**. **Codex**: open the page shown, enter the code; the page finishes by itself once you confirm.
3. The result is the same as on the command line: `add` keeps the sign-in only when the email matches and the account is not in the pool yet, then balances; `relogin` swaps the new login in at the same position only when it is the same account.

**Open in default browser** is there too, but your default browser is often signed in as another account; **Copy link** into the right browser profile is the safe way. A sign-in that is not finished within 15 minutes expires, and **Cancel** drops it at once. Each sign-in can be finished only once.

### Requests to the provider

| You | Requests |
|---|---|
| Open the page, switch tabs, look at the chip | None. Usage comes from the history the timer writes every 5 minutes, tokens from the tracker, API prices from Hermes' own price list. |
| Live usage | One usage request per account, parked accounts included. At most once every 2 minutes per provider; the button counts down. |
| Balance now | The same as `balance`. At most once a minute, shared with Check accounts. |
| Check accounts | One profile request per account. |
| Run doctor | One usage request. |
| Add account, Sign in again | The sign-in, then one profile request to verify the email. |

The usage endpoint limits requests per account (see [Troubleshooting](#troubleshooting)), so the page never calls it on its own.

### How the page is built and secured

- The page is the plugin's `desktop/plugin.js`, a Hermes Desktop plugin. It imports only the Hermes plugin SDK and React, and talks only to its own backend.
- The backend is `dashboard/plugin_api.py`, mounted by Hermes under `/api/plugins/account-pool/` when `account-pool` is in `plugins.enabled` of the profile Desktop runs. Hermes requires the desktop's session token for every request.
- Responses carry labels, ids, states, percentages and times. Tokens never leave the backend. The state of a sign-in in progress (the PKCE verifier for Anthropic, the device id for Codex) stays in the backend's memory.
- The page always works on the shared pool in the default Hermes home, whichever profile the window shows. Bots cannot use it: it is part of the desktop app, not a tool.
- One action runs at a time; a second click while one runs gets `Another account action is still running`.

## Alerts

| Alert | When | Sent |
|---|---|---|
| Account needs sign-in | An account becomes `DEAD` | Once per account |
| Every account above 80% | Every account in rotation is at or above 80% (adapter needed) | Once, plus a message when the pool recovers |

Alerts are sent by `balance`, so they need the timer. Channels:

- **Desktop**: `notify-send`, on by default.
- **Telegram**: on automatically when Hermes has a Telegram bot. The message goes with `hermes send` to the first user in `TELEGRAM_ALLOWED_USERS` (your private chat), using the default profile's bot. If the default profile has no working bot, use another profile's: `notify telegram-via=<profile>`.

Run `notify test` after setting up.

### Daily summary

`notify daily=08:00` sends a summary of the last 24 hours once a day, on the first timer run after 08:00, to the same channels as the alerts. Turned on after that time, the first one comes the next day. `notify summary` sends one at once, which is also a preview.

```
Hermes anthropic: last 24 h
Tokens: 10.9M in 647 requests, $5.66 at API list prices.
Bots: worker-1 5.6M, worker-2 2.4M, default 1.9M, worker-3 1.1M.
Share of the load: bob 27%, carol 25%, alice 24% and 1 more. Highest 5-hour usage: 60% (bob). Every account >= 90% at once: 0 min.
Busiest hour: 08:00-09:00.
Now: 4 in rotation, 0 parked; new sessions start on alice (59%).
```

Accounts that need a new sign-in and the report's advice are added when there are any. The summary is built from the plugin's files, with no request to the provider. `notify daily-off` stops it.

### Settings file

Settings are stored in `$HERMES_HOME/account-pool.json`, created on the first change. You can also edit it; the alert level is `alert_all_above`, the daily summary time `notify.daily`, and park schedules are under `schedules`:

```json
{"notify": {"desktop": true, "telegram": "auto", "telegram_via": "default", "daily": "08:00"},
 "alert_all_above": 80,
 "schedules": {"anthropic": [{"label": "dave@example.com", "id": "a3b2c3", "days": [0, 1, 2, 3, 4], "from": "09:00", "to": "17:00"}]}}
```

## How balance works

Each run, for one provider:

1. **Timed parks**: unparks accounts whose `--until` time has passed (schedule windows that ended included).
2. **Schedules**: parks accounts whose schedule window has started, until the window ends.
3. **Recovery**: retries the token refresh for accounts in a refresh cooldown.
4. **Usage** (adapter needed): reads every account's usage, refreshing expired access tokens first.
5. **Bench and release**: accounts at or above the threshold are benched until their window resets; benched accounts that dropped below it are released. Benches are marked `[account-pool]`, and limits set by the provider itself are never touched.
6. **Order**: least used first, then benched accounts, then accounts whose usage could not be read, then `DEAD` accounts.
7. **History**: one snapshot per run for `report` and for the `last known` fallback. Values taken from that fallback are never written back.
8. **Alerts** for new problems, and the daily summary when it is due.

Safety rules:

- If **every** account is at or above the threshold, only accounts at 100% are benched, so the pool is never emptied for being nearly full.
- If no usage can be read at all, the order is left unchanged. Recovery, timed unparks, schedules, alerts and the daily summary still run.
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

The timer uses no AI tokens; it only calls the usage endpoints (and, for alerts and the daily summary, your notification channels).

## Providers

| Feature | Providers |
|---|---|
| `list`, `check`, `add`/`remove`, `park`/`unpark` (also `--until`), `schedule`, `who`, tokens and API price, `doctor`, sign-in alerts, daily summary, refresh-cooldown recovery | **Every provider in the credential pool** (OAuth and API-key entries) |
| `relogin` | Every provider with OAuth sign-in. Email verification needs an identity adapter. |
| `usage`, `report`, usage-based `balance`, "all accounts high" alert, real-email lookup | **Providers with an adapter.** Built in: **`anthropic`** (Claude Pro / Max / Team, 5-hour window) and **`openai-codex`** (ChatGPT Plus / Pro / Team, 5-hour **and** weekly window). |

Without an adapter, `usage` and `report` say so plainly, and `balance` still unparks timed parks, retries refresh cooldowns and sends sign-in alerts, but leaves the order unchanged.

**Codex.** The stricter of the 5-hour and weekly limits drives `balance`, and `usage` shows both (`5h 12% · week 78%`). A Codex account that is also signed in to Codex CLI or VS Code shares its quota with them. Hermes keeps its own Codex sign-in and never reuses `~/.codex/auth.json`.

**The plugin only manages accounts inside a provider.** Whether a profile uses a provider at all (main model, fallback order) stays a normal Hermes setting, and the plugin never changes it. A provider with no accounts yet is idle: `hermes account openai-codex doctor` says "not in use".

Adding an adapter for another provider is a single class; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Files and security

| Piece | Role |
|---|---|
| `plugins/account-pool/` | The `hermes account` command (`__init__.py`) and the provider adapters (`providers.py`). The command registers in the default profile only. |
| `plugins/account-pool/desktop/` | The Accounts page for Hermes Desktop (`plugin.js`). Hermes Desktop copies it to `$HERMES_HOME/desktop-plugins/account-pool/`. |
| `plugins/account-pool/dashboard/` | The page's backend (`plugin_api.py`) and its manifest. `dist/index.js` only tells the browser dashboard that the page lives in Hermes Desktop. |
| `plugins/account-pool-tracker/` | A `post_api_request` hook that records `{profile, session, platform, model, account label}` and adds each call's token counts to its account, profile and model. No commands, no tools, no credentials; it swallows every error so it can never break a bot. |
| `systemd/` | The service and timer templates used by `install.sh`. |

Data files, all mode `600`, in `$HERMES_HOME`:

| File | Content |
|---|---|
| `account-pool-parked.json` | Parked accounts. **Contains OAuth tokens.** |
| `account-pool-sessions.json` | Sessions and their account, last 24 hours (no tokens) |
| `account-pool-tokens.json` | Token counts per account, profile and model in 15-minute buckets, last 8 days. Numbers only. |
| `account-pool-history.jsonl` | Usage snapshots, one per timer run. Trimmed to the last 14 days once the file passes 3 MB. |
| `account-pool-alerts.json` | Alerts already sent, so each incident is reported once |
| `account-pool-state.json` | When the daily summary was last sent, and which schedule windows were already applied |
| `account-pool.json` | Settings: alert channels, daily summary, park schedules |

How tokens are handled:

- Tokens are never printed or logged. They only go into request headers to the provider's own endpoints.
- The plugin talks to the provider's API (usage, profile, token refresh, sign-in) and, for alerts and the daily summary, to Telegram through Hermes' own `hermes send`. Nothing else. API prices come from files Hermes already has.
- The Accounts page gets no tokens: its backend returns labels, ids, states and numbers only.
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
| A schedule did not park its account | The timer is off, it is the last working account, or you unparked it by hand inside the window | `hermes account <provider> schedule` shows the state of each schedule |
| No daily summary | The timer is off, no alert channel is on, or it was turned on after its time today | `notify` shows the time and the last day it was sent; `notify summary` tests delivery |
| `report`: `API $` shows `-` or ends in `+` | The model has no price in Hermes' price list, or the tokens were counted before tracker 1.3.0 | Nothing to fix; those tokens are left out of the price |
| `doctor`: strategy is not fill_first | A profile uses `round_robin` or another strategy | `hermes -p <profile> config set credential_pool_strategies.<provider> fill_first` |
| `doctor`: profiles with their OWN pool | Someone ran `hermes -p <profile> auth add` | Remove those entries in that profile (`hermes -p <profile> auth remove ...`) and add the accounts from the default profile |
| `doctor`: last run failed | The timer's last `balance` failed | `journalctl --user -u hermes-account-balance.service -n 20` |
| `hermes account`: unknown command | Run with `-p <profile>`; the plugin is in the default profile only | Run it without `-p` |
| Accounts page: `The account-pool backend did not answer` | Hermes Desktop runs a profile that does not list `account-pool` (a profile created after the install, or an install older than 3.5.1), or was not restarted after the install | `./install.sh` again, then restart Hermes Desktop. `doctor` names the profiles that miss it |
| No Accounts entry in the sidebar | The Desktop half of the plugin is off | Capabilities > Plugins, account-pool, switch on Desktop. After an update: Ctrl+K, `Reload desktop plugins` |
| Live usage button greyed out | Live usage ran less than 2 minutes ago | Wait for the countdown on the button |
| Sign-in in the page: `This code belongs to another sign-in` | The code came from another sign-in link, or was copied without the part after `#` | Open the link from this window again and copy the whole code |

## FAQ

**My quota in claude.ai (or another usage tool) is fine. Why does `usage` say rate-limited?**
Two different limits. Your model quota is what the bots spend. The usage endpoint that tools read to *display* that quota has its own request limit. When it is hit, only the display is affected: bots keep running, and the plugin shows the last known value.

**Does the plugin use AI tokens?**
No. It reads usage and reorders the pool. No model is called.

**Does `balance` move running sessions to a less used account?**
No. A running session keeps its account until it hits a limit; moving it would discard the prompt cache. New sessions take the least used account.

**Why are the accounts in use in the middle of the list, and #1 idle?**
That is balance working. A session started on the account that was #1 at the time. Its usage grew, so the next runs moved fresher accounts above it. #1 is where the next new session starts. See [Running sessions keep their account](#concepts).

**Is there a round-robin mode?**
Hermes has one (`round_robin`), next to `fill_first`, `least_used` and `random`; the plugin has no mode of its own. With this plugin, keep `fill_first`: balance then rotates by quota left instead of by turn. The table under [Concepts](#concepts) compares the four.

**Does the plugin change my fallback provider or models?**
No. Fallback, models and which provider a profile uses stay in your Hermes configuration. The only setting the project writes is `credential_pool_strategies`, and only when you pass `install.sh --set-strategy`.

**Can I use the same account in claude.ai, Claude Code or Codex CLI at the same time?**
Yes, with a separate sign-in there. The quota is shared, so that use shows up in `usage`. Never copy Hermes' tokens to another app or machine.

**What happens if the provider changes the usage endpoint?**
`usage`, `report` and usage-based ordering stop, `doctor` reports FAIL, and Hermes' built-in rotation keeps working as before.

**Can a worker bot run `hermes account`?**
No. The command is installed in the default profile only, on purpose. Bots run the tracker, which only records which account they use and how many tokens they spent on it.

**Why does an account show many tokens but a low percentage, or the other way round?**
The percentage is the provider's, for everything on the account, weighted by token type. Most of what Hermes sends is cache reads, which count for little. Use against Claude Code or claude.ai raises the percentage without adding Hermes tokens.

**Is `API $` what I pay?**
No. A subscription (Claude Pro, Max or Team, ChatGPT Plus, Pro or Team) costs the same however much you use it. `API $` prices the same tokens as if they had gone through the provider's API, so you can see what the subscription is worth and which bot costs the most.

**How many accounts do I need?**
At least two. `report` tells you when the whole pool was nearly full at the same time, which is the signal to add one.

## Limitations

- Usage comes from **undocumented endpoints**: `https://api.anthropic.com/api/oauth/usage` and `https://chatgpt.com/backend-api/wham/usage` (the one behind Codex CLI's `/status`). They can change or rate-limit without notice. The plugin sends the same client headers as Hermes' own usage fetcher.
- Anthropic weekly quotas are not exposed for Team accounts, so `balance` uses the 5-hour window for `anthropic`.
- Adapters exist for `anthropic` and `openai-codex`. The generic commands were tested for other providers with API-key entries only. The Codex adapter was verified read-only against a real ChatGPT Team account; `add` with a real Codex sign-in has not been run yet.
- Token counts start when tracker 1.1.0 first runs and cover Hermes on this computer only. They are kept for 8 days, in 15-minute buckets, so a period starts at the nearest quarter hour. The split by profile and model starts with tracker 1.3.0; bots pick up a new tracker when their gateway or session restarts.
- `API $` uses list prices for the standard context length; long-context surcharges and batch discounts are not applied.
- `who` finds the agent object by scanning running thread frames. A future Hermes refactor may leave `who` empty, but it can never break the bots.
- `add` and `relogin` with OAuth need an interactive terminal or the Accounts page to paste the code. The page's Codex sign-in was tested up to the device code; a full Codex sign-in has not been run yet.
- The Accounts page follows the Hermes Desktop plugin SDK as of Hermes Agent 0.21.5. A future SDK change can break the page; the command is not affected.
- Linux with systemd only, for the timer. The commands themselves work wherever Hermes runs.

## Contributing, changelog, license

- Adapters for more providers are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers the adapter interface, the rules for handling tokens, the Hermes Desktop page, and how to test in a sandbox without touching your real pool.
- [CHANGELOG.md](CHANGELOG.md) lists every release.
- [`docs/hermes-account-pool.pdf`](docs/hermes-account-pool.pdf) is the full guide in Indonesian. `docs/make_doc.py` regenerates it (reportlab, DejaVu fonts).
- License: MIT, see [LICENSE](LICENSE).
