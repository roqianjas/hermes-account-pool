# Changelog

All releases of the `account-pool` plugin. The session tracker `account-pool-tracker` is at 1.0.0 and has not changed.

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
