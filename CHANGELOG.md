# Changelog

All releases of the `account-pool` plugin. The session tracker `account-pool-tracker` is at 1.0.0 and has not changed.

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
