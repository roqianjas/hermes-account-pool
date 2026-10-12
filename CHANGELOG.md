# Changelog

All releases of the `account-pool` plugin and its session tracker `account-pool-tracker` (now 1.5.0).

## 3.11.0

Wake starts an idle account's 5-hour window now, and email masking hides the account emails for screenshots.

- **`hermes account <provider> wake`.** A 5-hour window starts with the account's first request, so an account that waits idle resets 5 hours after the work arrives. `wake` sends that first request now: one request with a one-word answer through each account in rotation whose window is not running (Anthropic: `claude-haiku-4-5`, one output token, through Hermes' own client; Codex: the smallest model the account offers, low reasoning). Running windows, benched, rate-limited, dead, API-key and parked accounts are left alone. `wake <target>[,<target>...]` wakes named accounts, `--dry-run` shows the plan, `wake status` shows every window without a request, `wake model=<id>` picks the model.
- **Automatic wake** (`wake auto-on`, off by default): the balance timer wakes an account in rotation as soon as its window is not running, at most about 5 tiny requests per account per day, and not twice within an hour for the same account. `doctor` warns when it is on without the timer or when wakes failed.
- **Codex windows.** An untouched Codex window reads as 0% with a full 5 hours left that moves with every reading; the plugin counts that as not running. The history keeps the 5-hour window next to the headline value when the weekly one is fuller (`win`), so the page can tell.
- **`hermes account <provider> privacy on|off`** masks emails (`alice@example.com` → `al•••e@e•••.com`) in everything the command prints, with columns kept aligned, in desktop and Telegram alerts and the daily summary, and on the whole Accounts page. Files keep the real emails; targets still take the full email.
- **Accounts page.** The eye button in the header switches masking. **Wake** opens a dialog with each account's window and last wake: idle ones ticked, **Wake N accounts**, **Keep windows running** and the model. **Resets** shows `not started` for an account without a running window.
- Activity log: wakes and the wake and masking settings. `account-pool-state.json` keeps each account's last wake.
- Docs: README and PDF (wake, privacy, the 5-hour window, the page, the settings file, balance, the timer, the disclosure with the new requests, troubleshooting, FAQ, limitations), two new screenshots, and the adapter's `wake` in CONTRIBUTING. Tests: `tests/wake_privacy_sandbox.py` (64 checks), the page tests for both features.

## 3.10.4

- The timer unit and the commands the plugin starts (`hermes auth add`, `hermes send`, `hermes config set`, ...) use the `hermes` command you installed (`~/.local/bin/hermes`, or any other outside the Hermes home). While Hermes runs, its internal launcher inside `~/.hermes` comes first on `PATH`, so `setup --timer` wrote that path into the unit; Hermes' installer keeps `~/.local/bin/hermes` up to date across updates, not units that point inside its own folder.

## 3.10.3

The balance timer covers every provider with accounts, so a Codex account (or any other provider) added later is balanced without a second `setup`.

- **`hermes account all balance`** balances every provider with accounts (in rotation or parked), one after the other. A provider that fails does not stop the others; the exit code says it failed. `all` works with `balance` only.
- **`setup --timer` installs the timer with `all balance`.** A unit from 3.10.2 or older (one `ExecStart` per provider) stays as it is until `setup --timer` runs for a provider it lacks, which switches it to `all`, keeping hand-added options (`--threshold 85`) and the interval. `doctor` names the fix for such a unit. `setup --undo` for one provider turns `all` into one line per remaining provider.
- **Daily summary** only for a provider with something to report (requests counted, usage above 0%, or an account that needs a new sign-in). With every provider balanced, an idle one would otherwise send an empty summary every day.
- `install.sh --help` printed the `set -euo pipefail` line after the options.
- Docs: README and PDF (setup, the timer, balance, Codex, daily summary, troubleshooting, command reference). Tests: `setup_sandbox.py` (the `all` unit, a new provider picked up without setup, the switch from an older unit, undo for one provider) and `codex_sandbox.py` (`all balance` over two providers, one provider failing, the daily summary skipped for an idle provider).

## 3.10.2

Codex accounts from ChatGPT Business and Enterprise workspaces can be added, and every Codex feature has tests.

- **Codex sign-in through the browser.** Those workspaces turn device-code sign-in off, so `add` stopped at OpenAI's *"Please contact your workspace admin to enable device code authentication"*. `hermes account openai-codex add` and `relogin` now sign in through the browser by default (authorization code + PKCE, back to `http://localhost:1455/auth/callback`, as Codex CLI does), with Hermes' own `hermes auth add openai-codex --browser --no-browser`. `--device` keeps the device code. Hermes before 0.21.6 has no browser sign-in; there the device code stays the default.
- **Accounts page.** **Add account** and **Sign in again** for Codex ask **Browser on this computer** (default) or **Device code**. The browser sign-in finishes by itself when the browser returns to `localhost:1455`; with the browser on another computer, paste the address it ended on. The page's backend listens on `127.0.0.1:1455` only while that sign-in waits, answers only its own `state`, and stops on finish, cancel or after 15 minutes. One browser sign-in waits at a time; a busy port falls back to the pasted address.
- A sign-in that cannot be finished any more (refused on OpenAI's page, a spent device code, an expired flow) takes the dialog back to its first step with the email kept, instead of polling on.
- Two polls, or a poll and a pasted address, can no longer finish the same sign-in twice.
- The Codex sign-in dialog no longer shows Anthropic's "paste the code" steps before it starts.
- `add` and `relogin` without a terminal say what is missing per method (`the sign-in link is shown there` for Codex).
- `doctor` could say `usage history last written -0 min ago` right after a run.
- Docs: a Codex section (browser sign-in, device code and the workspace setting, Codex CLI and VS Code untouched, where Codex quota goes), the local listener in the security disclosure, five Codex rows in Troubleshooting, the adapter's sign-in interface in CONTRIBUTING, and a screenshot of the Codex dialog.
- Tests: `tests/codex_sandbox.py` (identity, check, usage parsing and headers, park/unpark keeping the whole login, parked-token refresh and a dead refresh, balance, doctor, no token outside `auth.json` and the parked file); `api_sandbox.py` covers the page's Codex browser and device-code sign-ins end to end against a local callback; `setup_sandbox.py` the terminal's Codex sign-in; `tests/ui/run.mjs` the Codex dialog (92 checks). The forecast check in `run.mjs` no longer fails a day after the fixtures were made.

## 3.10.1

Installed from this repository, not from the Hermes plugin catalog. No change in behaviour.

- The plugin keeps handling logins itself (parking, live usage and email checks, sign-in on the Accounts page), so it does not meet the catalog's rule that credentials come through Hermes (rule 11). The README explains why, in "Why it is not in the Hermes plugin catalog", and the catalog install instructions are gone.
- Install: `./install.sh` from a git checkout, or `hermes plugins install roqianjas/hermes-account-pool#plugins/account-pool --enable`. Hermes' install scan reports 12 expected findings for `account-pool` (11 `subprocess` calls and one read of `/proc/self/cgroup`) and asks `Install anyway?` in a terminal (without a terminal it stops unless `--force` is given); the README lists each one. `hermes plugins update` installs later versions without asking again.
- The command help and the code say "`hermes plugins install`" where they said "catalog install".

## 3.10.0

Ready for the Hermes plugin catalog: install with `hermes plugins install`, then one command for the rest.

- New `hermes account <provider> setup [--timer] [--strategy] [--undo] [--yes]`. A plugin install puts a plugin into one profile; `setup` does the rest: lists `account-pool` in every profile (for the Accounts page), links the session tracker from the default profile into every other profile and enables it there, with `--timer` writes and starts the 5-minute balance timer, with `--strategy` sets `fill_first` everywhere. It shows what it found and every change, asks once, and logs each change in the activity log (`setup`). `--undo` takes the profile and timer parts back and names parked accounts that would stay out of rotation. A second run says `Nothing to change`.
- The systemd units are written by `setup` instead of `install.sh` templates, so a catalog install can have the timer too. `setup --timer` for a second provider adds its own `ExecStart` line; lines edited by hand (`--threshold 85`) and a changed interval are kept; a custom `HERMES_HOME` goes into the service. The `systemd/` folder is gone.
- `install.sh` copies the plugins and runs `setup --yes --timer` (with `--strategy` for `--set-strategy`, once per `--provider`), so a git install and a catalog install end up the same. `uninstall.sh` honours `XDG_CONFIG_HOME`.
- Without a terminal (cron, an agent's shell), `add` and `relogin` stop at once with the command to run in a terminal or the page button to use, even with `--yes`; before, they could wait forever for a sign-in code. Every `[y/N]` question answers no without a terminal (`no terminal to answer, so no`) and exits 1; `--yes` still skips it where it did. Deliberate output change.
- `doctor` and the Accounts page suggest `setup` where they suggested `./install.sh`.
- Accounts page: a park schedule more than a day away showed its day twice (`next Mon Mon 09:00`).
- `requires_hermes: ">=0.21.5"` in both manifests.
- Docs: screenshots of the Accounts page (`docs/screenshots/`, from the test fixtures), install from the catalog, `setup`, a security and privacy disclosure (what is written, which hosts, which commands, which Hermes internals), and a README for the tracker with its known issue: under `plugins.isolation: host` it records nothing.
- Tests: `tests/setup_sandbox.py` covers `setup`, `--undo`, the timer units and the refusals without a terminal. `tests/ui/fixture_api.py` and `tests/ui/screenshots.mjs` take the screenshots from a separate Hermes Desktop.

## 3.9.1

Fixes after the first hours of real use of 3.9.0.

- Bot alert: a bot near the floor went over and under it from one timer run to the next and got a new message each time (two in ten minutes). Now one message per bot per 6 hours (`alert_bot.cooldown_h`); the page banner still shows whenever the bot is over.
- Bot alert: profiles without 3 active hours of history had no usual hour, so the floor alone decided and normal heavy work (an orchestrator on a busy Kanban board) alerted. Until a profile has a usual hour, the floor counts double. Buckets after the time being checked are ignored.
- Forecast: reads only the end of the usage history instead of parsing all of it on every page refresh, so the page stays fast once the history grows toward its 3 MB limit.
- `sessions` for a provider without accounts says so, like `usage` and `report`, instead of an empty list.

## 3.9.0

- Bot alert. The balance timer alerts once when a profile's last hour reaches $15 at API prices or 300 requests and 3 times its usual hour (the mean of its active hours in the 7 days before): a loop or a runaway task. The alert names the busiest session and the command to look further. `notify bots=<USD>`, `bots-on`, `bots-off`; `alert_bot` in the settings file; a switch and the amount in the Alerts tab. The page shows it as a banner with **See sessions**. On by default.
- Activity log. Balance changes (bench, release, timed and scheduled parks, recoveries, alerts sent), `park`, `unpark`, `remove`, `add`, `relogin`, `schedule`, `unschedule`, `strategy` and alert settings are written to `account-pool-activity.jsonl` (mode 600, 30 days) with who made them: `timer`, `cli` or `page`. New command `hermes account <provider> log [--hours N]` and a new **Activity** tab. The new order after each balance is not logged.
- Forecast. `usage`, `report`, the daily summary and a new card on the Accounts page say when every account will be at 90% or more at the last hour's pace, and when the first one comes back, from the timer's history with no request to the provider.
- Tokens per session. Session tracker 1.5.0 also counts tokens per profile, session and model, and keeps a session's Kanban task. New command `hermes account <provider> sessions [--hours N]` and a **By session** table in the Report tab list the sessions with the most tokens, with their title and source from Hermes' own session list (`state.db`, read-only) and their API price. The daily summary names the top session.
- `--hours` now applies to `report`, `sessions` and `log`; the error for other actions lists all three. Deliberate output change.
- Tests: `tests/insights_sandbox.py` covers all four; the UI test covers the forecast card, the sessions table, the Activity tab, the bot alert banner and its settings.

## 3.8.1

- Session tracker 1.4.0 writes its version, its process id and the Kanban task (when there is one) into each session record.
- `doctor` names every running process that still counts with an older tracker after an update: the gateway, Hermes Desktop or a long session, each with its fix (`hermes gateway restart`, restart Hermes Desktop, or wait for the session to end). It also warns about tokens without a bot name in the last half hour, the sign of a tracker 1.2.0 or older. The Accounts page shows the same as an info banner.
- `report`: tokens without a bot name are labelled `(older tracker, no name)` instead of `(before tracker 1.3.0)`, because a process that kept the old tracker also writes them. The page says `no name (older tracker)`. Deliberate output change.
- Tests: `tests/insights_sandbox.py` covers the tracker check; the UI test covers the banner.

## 3.8.0

- Rotation strategy from the plugin. `hermes account <provider> strategy` lists Hermes' `credential_pool_strategies.<provider>` per profile and what each strategy does; `strategy <name>` sets it in every profile, `--only <profile>,...` in some. Values other than `fill_first` ask for confirmation (`--yes`). The value is written with Hermes' own `hermes config set` and read back; profiles that already have it are not touched. New sessions use it at once.
- Accounts page: `rotation: …` in the header opens a dialog with one picker per profile and an **Every profile** row; the banner for profiles off `fill_first` gets a **Use fill_first** button instead of a command to copy.
- `doctor`: a strategy value Hermes does not know is now a WARN, not a FAIL, because Hermes uses `fill_first` for it. The FAIL for another strategy now gives `hermes account <provider> strategy fill_first` as the fix. These are deliberate output changes.
- Accounts page: the tokens card puts the requests on their own line, so the API price is no longer cut off in narrow windows.
- Tests: `tests/api_sandbox.py` sets strategies through the page backend in a sandbox and checks that the real Hermes configs are untouched; `tests/ui/run.mjs` covers the dialog and the banner button.

## 3.7.0

- Tokens per bot and per model. The session tracker (1.3.0) adds each call's tokens to its account, profile and model. `report` and the Report tab list tokens by profile (bot) and by model. Tokens counted by tracker 1.1.0 or 1.2.0 have no profile or model; they show as `(before tracker 1.3.0)` / `not split yet` and leave the report within 8 days. The token file moves to version 2; a 1.1.0 or 1.2.0 tracker still running in a bot until its restart keeps writing the old layout, which is folded in on the next write.
- API price. `report` gains an `API $` column and price lines per bot and model; the Accounts page shows the price in the tokens card and tooltips, the Report tab in a card and its tables. Each model's input, output, cache read and cache write tokens are priced at the provider's API list price, from Hermes' bundled price list or its models.dev cache, with no request. Tokens with no known price are counted as unpriced (`+`), not guessed.
- Daily summary. `notify daily=08:00` sends tokens, API price, bots, load per account, busiest hour and the state of the pool once a day, on the first timer run after that time, to the alert channels. `notify summary` sends it now; `notify daily-off` stops it. The Alerts tab has a switch, the time and **Send the summary now**.
- Load by hour. `report --chart` draws the last 7 days, one row per day and one column per hour, for quota used and for tokens. The Report tab shows the same as a chart; hover a cell for its numbers.
- Park schedules. `schedule <target> --every "mon-fri 09:00-17:00"` parks an account on set days and hours every week; `schedule` lists them, `unschedule <target>` removes one. The timer parks the account when a window starts, until its end, once per window: unparking by hand inside a window is respected. The last working account is never parked. The Accounts page has **Park on a schedule** on every row, a calendar chip on scheduled accounts and a table of schedules. `list` and `doctor` show them.
- New file `account-pool-state.json` (when the daily summary was last sent, which schedule windows were applied). `uninstall.sh` lists it with the other files it keeps.
- CLI output changes, on purpose: `report` has the `API $` column, an `API $` note, the `By profile (bot)` and `By model` blocks and a closing `--chart` hint; `notify` status has a `daily summary` line; `list` adds `(schedule)` and a schedules block when there are schedules; `doctor` adds a daily-summary line and a schedules line only when those are in use. The help lists `schedule`, `unschedule` and `report --chart`.
- Tests: `tests/features_sandbox.py` (tracker upgrade, grouping, prices, chart, daily summary, schedules, page actions); `tests/ui/run.mjs` covers the new tables, chart, schedule dialog and daily summary.

## 3.6.1

- Accounts page: the header shows Hermes' rotation strategy (`credential_pool_strategies`), with what each strategy does on hover. A banner names any profile that does not use `fill_first` and gives the command that fixes it.
- The line over the rotation table says where new sessions start and that running sessions keep their account until it hits a limit (hover for why).
- `Used by`: hovering a profile shows since when each session is on that account. The session tracker (1.2.0) records `account_since`; for sessions recorded earlier the page uses the session's start when it never moved.
- Fix: tooltips with several lines (token split, sessions, account problems) ran into one line, because the desktop's tooltip collapses line breaks.
- README and PDF: the four Hermes strategies compared, and why accounts in use sit in the middle of the list.
- Tests: rotation strategy per profile and the unchanged `doctor` line (`tests/api_sandbox.py`); `account_since` (`tests/tokens_sandbox.py`); header, banner and tooltip style (`tests/ui/run.mjs`).

## 3.6.0

- New: **token counts per account.** The session tracker (1.1.0) adds the input, output, cache-read and cache-write tokens of every API call to the account that made it, in `account-pool-tokens.json` (15-minute buckets, 8 days, numbers only). Calls that went to a fallback provider are not counted.
- `report` has a `tokens` column and a line that splits the total into input, output, cache read, cache write and requests.
- Accounts page: a `Tokens, last 24 h` card, a `Tokens, 24 h` column (hover for the split and the current 5-hour window), and tokens in the Report tab.
- Fix: the Telegram profile picker on the Alerts tab opened a white list that ignored the Hermes theme. It is the desktop's own Select now; with an older Hermes Desktop, the native list gets theme colors.
- Test: `tests/tokens_sandbox.py` (tracker hook, `report`, page backend).

## 3.5.1

- Fix: the Accounts page showed `The account-pool backend did not answer` whenever Hermes Desktop ran a profile other than default. Desktop runs its backend under the profile you last used, and that backend loads a plugin's page routes only when the plugin is in that profile's `plugins.enabled`.
- `install.sh` adds `account-pool` to `plugins.enabled` of every profile (no symlink, so the agent in a profile does not load it). `uninstall.sh` takes it out again.
- `register()` registers nothing when it runs in a profile, so the command stays in the default profile.
- `doctor`: new check `Accounts page backend enabled in every profile`, shown when Hermes Desktop has the page.
- The page's error text says what to do: run `install.sh` again and restart Hermes Desktop.
- Test: `tests/profile_backend.py` (backend under a profile, before and after the fix).

## 3.5.0

- New: an **Accounts page in Hermes Desktop**, with its own sidebar entry. It lists the accounts in rotation and the parked ones with their 5-hour usage, a trend line for the last 5 hours, the reset time and the profiles using them. Buttons: Live usage, Balance now, Add account, Sign in again, Park (now, for 1 or 2 hours, or until a time), Unpark, Remove. Tabs for Report, Health (doctor, check, timer) and Alerts (switch channels, send a test). The page ships switched off: turn on the Desktop half of account-pool in Capabilities > Plugins.
- A status-bar chip (`8/8 · 12%`: usable accounts, and the usage of the account the next session starts on) and a command-palette entry open the page.
- Add and sign-in-again work from the page. Anthropic: copy the link, authorize, paste the code. Codex: enter the device code; the page finishes by itself. The same checks as `add` and `relogin` decide whether the sign-in is kept.
- The page reads usage from the timer's history, so opening it costs no provider request. Live usage is limited to once every 2 minutes, Balance now and Check accounts to once a minute.
- The page's backend (`dashboard/plugin_api.py`) never returns tokens, and always works on the shared pool in the default Hermes home, whichever profile the window shows.
- `remove` calls Hermes' `auth remove` in-process instead of starting a second `hermes`.
- `uninstall.sh` also removes Hermes Desktop's copy of the page.
- Tests: `tests/api_sandbox.py` (backend, in a sandbox, fake accounts and a fake sign-in) and `tests/ui/run.mjs` (the page in jsdom).
- `doctor` says `last run running now` while the timer's balance is running. It said `never`.
- Internal: command output goes through a per-thread writer, and `report`, `who` and `relogin` have data functions that the page shares with the command. Apart from the `doctor` line above, the command output is unchanged.

## 3.4.3

- Documentation rewritten: README with quick start, concepts, a full command reference with example output, alerts, the timer, files and security, troubleshooting and FAQ. The Indonesian PDF guide follows the same structure and now covers install, update and uninstall.
- `plugin.yaml` description lists both built-in adapters.
- No code changes.

## 3.4.2

- The `last known` usage fallback looks back through recent snapshots. Before, it only read the newest snapshot, so it lasted one timer run instead of 15 minutes.

## 3.4.1

- Usage requests send the same headers as Hermes' own usage fetcher, including a Claude Code `User-Agent`. With Python's default `User-Agent`, Anthropic's usage endpoint answered 429 much sooner (same token, same second: 429 versus 200).

## 3.4.0

- `park --until` rejects impossible times (`25:99`, `7:60`) and past dates instead of failing with a traceback.
- `--threshold` must be 1 to 100; `--hours` and `--minutes` must be greater than 0.
- Unknown provider names are reported instead of showing an empty pool.
- `park` on an account that is already parked says so.
- `add --key` asks for the key itself, without echo, and hands it to Hermes in-process: clean Ctrl+C and Ctrl+D, and the key never appears on a command line.
- `usage` shows why a value is `n/a` (rate-limited, expired, HTTP code). On a temporary endpoint error it shows and uses the last value the timer recorded (at most 15 minutes old, window not reset), which is never written back to the history.
- `doctor` warns when the balance timer does not run the provider.
- `report` for a provider without accounts says so.
- `who` column alignment, singular and plural wording, an unused import.

## 3.3.3

- Ctrl+C during the sign-in of `add` or `relogin` stops cleanly, removes a half-saved entry and exits with code 130, instead of printing a traceback.

## 3.3.2

- `add` and `relogin` explain how to sign in as the right account: that account's own browser profile or a private window, check `Logged in as`, and that "Sign in again to continue" is normal.

## 3.3.1

- README and PDF document `add` and `remove`.

## 3.3.0

- `openai-codex` adapter: 5-hour and weekly usage (the stricter one drives `balance`), real email from the token, refresh of parked tokens.
- Providers without accounts are idle: `usage`, `check`, `balance` and `report` say how to add one, and `doctor` says "not in use".

## 3.2.0

- `add`: signs in a new account, verifies the real email, discards wrong-account and duplicate sign-ins, and balances right away. `--key` for API-key accounts.
- `remove`: asks for confirmation, refuses the last working account, also deletes parked accounts.
- CONTRIBUTING: test sandboxes must live outside `~/.hermes`.

## 3.1.0

- Provider adapters in `providers.py`. The generic commands work for every provider in the credential pool; usage, report, usage-based balance and email checks come from adapters (`anthropic` built in).

## 3.0.0

- First public release: `list`, `check`, `usage`, `who`, `report`, `park`/`unpark` with `--until`, `relogin`, `balance`, `doctor`, desktop and Telegram alerts, refresh-cooldown recovery, the session tracker and the 5-minute systemd timer.
