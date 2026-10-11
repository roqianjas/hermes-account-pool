# Changelog

All releases of the `account-pool` plugin and its session tracker `account-pool-tracker` (now 1.3.0).

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
