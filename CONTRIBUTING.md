# Contributing

Bug reports, fixes and adapters for more providers are welcome. This page covers the repository layout, the adapter interface, the rules for handling tokens, the Hermes Desktop page, how to test without touching your real pool, and what a pull request needs.

## Repository layout

| Path | Content |
|---|---|
| `plugins/account-pool/__init__.py` | The `hermes account` command: argument parsing, every action, balance, alerts, history |
| `plugins/account-pool/providers.py` | Provider adapters: usage, identity, parked-token refresh |
| `plugins/account-pool/plugin.yaml` | Plugin metadata and version |
| `plugins/account-pool/desktop/plugin.js` | The Accounts page in Hermes Desktop (one ES module, no build step) |
| `plugins/account-pool/dashboard/plugin_api.py` | The page's backend: FastAPI routes under `/api/plugins/account-pool/` |
| `plugins/account-pool/dashboard/manifest.json` | Tells Hermes to mount `plugin_api.py`; `dist/index.js` is a stub for the browser dashboard |
| `tests/api_sandbox.py`, `tests/profile_backend.py`, `tests/tokens_sandbox.py`, `tests/ui/` | Backend tests in a sandbox (actions and sign-in; backend launched under a profile; token counting), and the page in jsdom |
| `plugins/account-pool-tracker/` | The `post_api_request` hook behind `who` |
| `systemd/` | Service and timer templates, filled in by `install.sh` |
| `install.sh`, `uninstall.sh` | Install and remove everything |
| `docs/make_doc.py` | Generates `docs/hermes-account-pool.pdf` (Indonesian guide) |

## Adding a provider adapter

The core plugin already works for every provider in the Hermes credential pool. An adapter adds the parts that need the provider's own API. Built in: `anthropic` and `openai-codex`. The Codex adapter is a good template for providers with several limits: it reports the most constraining window and puts the breakdown in `detail`.

```python
class MyProvider(Adapter):
    name = "my-provider"        # Hermes provider id, as shown by `hermes auth list`
    window = "daily"            # shown in output: "[my-provider] daily usage"
    window_short = "1d"         # used in the bench reason
    oauth_only = True           # False if API-key entries can read usage too

    def usage(self, entry):
        """Return (percent_used, resets_at_epoch[, detail]), or None.
        Several limits: return the most constraining one, e.g. (78.0, reset, "5h 0% · week 78%")."""

    def identity(self, entry):
        """Return the real account email/name, or None."""

    def refresh_parked(self, record):
        """Refresh a PARKED OAuth account's expired access token.
        Return {"access_token", "refresh_token", "expires_at_ms"}, or None."""


ADAPTERS = {a.name: a for a in (Anthropic(), OpenAICodex(), MyProvider())}
```

Implement only what the provider allows. Methods you leave out stay off: `has_usage` and `has_identity` are detected automatically.

| You implement | Unlocks |
|---|---|
| `usage` | `usage`, `report`, usage-based `balance`, the "every account above N%" alert |
| `identity` | real-email column in `check`, verification in `add` and `relogin` |
| `refresh_parked` | live usage for parked OAuth accounts whose token expired |

When a request fails, set `self.last_error = self.explain(err, entry)` before returning `None`, and reset it to `""` at the start of `usage`. `explain()` turns the exception into the reason `usage` prints (`usage endpoint rate-limited, ...`, `sign-in rejected (401)`, `usage endpoint HTTP 500`, `usage endpoint unreachable (...)`). Rate-limited, unreachable and HTTP 5xx reasons count as temporary: the core then falls back to the last value the timer recorded.

## Rules

1. **Never print or log tokens.** `entry.access_token` only goes into the request header.
2. **Return `None` on any failure** (network error, unexpected JSON, 4xx). The core then skips the feature for that account instead of reordering the pool on bad data.
3. **Refresh tokens may be single-use.** In `refresh_parked`, return the new pair. The core writes it back under a file lock right away; do not cache tokens anywhere else.
4. **Send a real client `User-Agent`.** Python's default (`Python-urllib/3.x`) can be rate-limited much sooner than the provider's own clients. On Anthropic's usage endpoint the same token got HTTP 429 with the default and 200 with `claude-code/2.1.0` in the same second. Copy the headers Hermes itself uses for that endpoint when there is one (see `agent/account_usage.py` in Hermes).
5. **Use the standard library only** (`urllib`, `json`). Plugins run inside the Hermes venv; do not add dependencies.
6. **Undocumented endpoints are allowed, but say so** in a comment. `doctor` reports FAIL when `usage` stops answering.
7. **Keep requests few.** `balance` runs every 5 minutes for every account. Do not add extra calls per run, and never loop over the usage endpoint while testing: it rate-limits.

## The Hermes Desktop page

The page and the command share one code base. `plugin_api.py` loads `__init__.py` and calls the same functions: the `_cmd_*` handlers for actions (their output is captured per thread with `_capture()`, so the page shows exactly what the command prints), and data functions such as `_report_data`, `_who_data` and `_relogin_target` for the views. When you add a command or change its output, keep the page in step.

Rules for the page:

1. **No tokens in responses.** Return labels, ids, states and numbers. A sign-in's secret state stays in the backend's `_FLOWS`.
2. **No provider request on a GET.** Views read files only (pool, parked file, history, sessions). Buttons that call the provider go through a POST and a rate limit: `LIVE_MIN_GAP` for live usage, `NET_MIN_GAP` for balance and check.
3. **One action at a time.** POST routes that change the pool run inside `_exclusive()`, which also points `HERMES_HOME` at the default root, so every profile sees the shared pool.
4. **The command stays in the default profile.** `install.sh` lists `account-pool` in every profile's `plugins.enabled`, because Hermes Desktop mounts the page's routes only for plugins enabled in the profile it runs. `register()` returns early in a profile (`_in_profile()`); keep anything you add to `register()` behind that check.
5. **Plain ESM in `plugin.js`.** Import only from `@hermes/plugin-sdk`, `react` and `react/jsx-runtime`, write elements with `createElement`, and style with the desktop's `--ui-*` variables so themes keep working. An identifier that is not imported is a runtime `ReferenceError`; `tests/ui/run.mjs` catches it.
6. **Use the SDK's controls.** `Select`, `Switch`, `Input`, `Button` and `SegmentedControl` follow the theme. A native `<select>` opens a list that Chromium draws in system colors, white on a dark theme. Reach SDK exports that older Hermes versions lack through `import * as sdk`, with a fallback, so a missing export cannot stop the page from loading.

To try a change in Hermes Desktop, copy the plugin to `~/.hermes/plugins/account-pool/`. Changes to `plugin.js` load with Ctrl+K, `Reload desktop plugins`; changes to `plugin_api.py` or `__init__.py` need a Hermes Desktop restart.

## Testing without touching your real pool

Create the sandbox **outside `~/.hermes`**. Hermes treats any `HERMES_HOME` under `~/.hermes` as part of your real install. When the sandbox has no accounts for a provider, it then falls back to *reading* `~/.hermes/auth.json`, and a `usage` or `balance` run could spend a real single-use refresh token and sign that account out. A sandbox elsewhere is a separate data root. Do not isolate by changing `HOME` either: Hermes then installs a fresh runtime of several hundred MB.

```bash
SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
mkdir -p "$SB/plugins"
cp ~/.hermes/config.yaml "$SB/"
cp -a plugins/account-pool "$SB/plugins/"
export HERMES_HOME=$SB          # first command prepares a runtime inside $SB (about a minute)
hermes plugins enable account-pool
hermes account anthropic list   # must show 0 accounts: proof the sandbox is isolated
hermes auth add my-provider --type api-key --api-key FAKE-1 --label key-one
hermes auth add my-provider --type api-key --api-key FAKE-2 --label key-two
hermes account my-provider list
hermes account my-provider park key-one --until +1m
hermes account my-provider balance --dry-run
hermes account my-provider doctor
unset HERMES_HOME; rm -rf "$SB"
```

Usage needs a real account, so test `usage` and `balance --dry-run` with one, a few times at most, and say in the pull request which account type you tested (for example Pro, Team, or API key).

The page has these tests, none needing a real account:

```bash
# backend: fake API-key accounts and a fake sign-in, in a sandbox
SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/api_sandbox.py
rm -rf "$SB"

# backend launched under a profile, as Hermes Desktop does (own sandbox)
SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/profile_backend.py
rm -rf "$SB"

# token counting: tracker hook, report, page backend (own sandbox)
SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/tokens_sandbox.py
rm -rf "$SB"

# the page in jsdom, every tab, dialog and button, answered from tests/ui/fixtures.json
node tests/ui/run.mjs
```

`tests/ui/run.mjs` borrows React, jsdom and Testing Library from the `node_modules` of your Hermes Agent checkout (`~/.hermes/hermes-agent`, or set `HERMES_AGENT_DIR`). All of them print one line per check and exit 1 on a failure.

Testing `install.sh` or `uninstall.sh` in a sandbox needs care: `HERMES_HOME` isolates the plugins and configs, but the timer's systemd units live in your real `~/.config/systemd/user`. Run `install.sh --no-timer`, and run `uninstall.sh` only as a copy without its `systemctl` and `~/.config/systemd` lines, or it disables your real timer.

A quick static check before committing:

```bash
~/.hermes/hermes-agent/venv/bin/python -m py_compile plugins/account-pool/*.py plugins/account-pool/dashboard/*.py plugins/account-pool-tracker/*.py
node --input-type=module --check < plugins/account-pool/desktop/plugin.js
python3 -m pyflakes plugins/        # if pyflakes is installed
```

## Documentation

- `README.md` is the English reference. Update it for every user-visible change.
- `docs/hermes-account-pool.pdf` is the Indonesian guide. Edit `docs/make_doc.py`, then regenerate it (needs `reportlab` and the DejaVu fonts, `fonts-dejavu-core` on Debian and Ubuntu):

  ```bash
  python3 docs/make_doc.py      # writes docs/hermes-account-pool.pdf
  ```

- Example output in the docs is based on real runs, with accounts renamed to `alice@example.com`, `bob@example.com` and so on.

## Pull request checklist

- [ ] Version bumped in `plugins/account-pool/plugin.yaml` and in `docs/make_doc.py`, with an entry in `CHANGELOG.md`.
- [ ] README and the PDF updated for user-visible changes.
- [ ] Tested in a sandbox outside `~/.hermes`; real-account tests named in the description.
- [ ] For changes to the page or its backend: `tests/api_sandbox.py` and `tests/ui/run.mjs` pass, and the page was checked in Hermes Desktop.
- [ ] No real emails, tokens, hostnames or home paths in code, docs or the PDF (`git grep -nI '@' -- ':!*.pdf'` is a good start).
- [ ] No state files: `.gitignore` excludes `*.json`, `*.jsonl` and `.env` (except the page's `manifest.json` and the UI test fixtures); keep it that way.
