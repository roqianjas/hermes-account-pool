# Contributing

Bug reports, fixes and adapters for more providers are welcome. This page covers the repository layout, the adapter interface, the rules for handling tokens, how to test without touching your real pool, and what a pull request needs.

## Repository layout

| Path | Content |
|---|---|
| `plugins/account-pool/__init__.py` | The `hermes account` command: argument parsing, every action, balance, alerts, history |
| `plugins/account-pool/providers.py` | Provider adapters: usage, identity, parked-token refresh |
| `plugins/account-pool/plugin.yaml` | Plugin metadata and version |
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

A quick static check before committing:

```bash
~/.hermes/hermes-agent/venv/bin/python -m py_compile plugins/account-pool/*.py plugins/account-pool-tracker/*.py
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
- [ ] No real emails, tokens, hostnames or home paths in code, docs or the PDF (`git grep -nI '@' -- ':!*.pdf'` is a good start).
- [ ] No state files: `.gitignore` excludes `*.json`, `*.jsonl` and `.env`; keep it that way.
