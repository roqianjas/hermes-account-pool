# Contributing

## Adding a provider adapter

Built in: `anthropic` and `openai-codex`. The Codex adapter is a good template for providers with several limits: it reports the most constraining window and puts the breakdown in `detail`.

The core plugin already works for every provider in the Hermes credential pool. An adapter adds the parts that need the provider's own API. Everything is in [`plugins/account-pool/providers.py`](plugins/account-pool/providers.py).

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


ADAPTERS = {a.name: a for a in (Anthropic(), MyProvider())}
```

Implement only what the provider allows. Methods you leave out stay off: `has_usage` and `has_identity` are detected automatically.

| You implement | Unlocks |
|---|---|
| `usage` | `usage`, `report`, usage-based `balance`, the "every account above N%" alert |
| `identity` | real-email column in `check`, and verification in `relogin` |
| `refresh_parked` | live usage for parked OAuth accounts whose token expired |

## Rules

1. **Never print or log tokens.** `entry.access_token` only goes into the request header.
2. **Return `None` on any failure** (network error, unexpected JSON, 4xx). The core then skips the feature for that account instead of reordering the pool on bad data.
3. **Refresh tokens may be single-use.** In `refresh_parked`, return the new pair. The core writes it back under a file lock right away; do not cache tokens anywhere else.
4. **Use the standard library only** (`urllib`, `json`). Plugins run inside the Hermes venv.
5. **Undocumented endpoints are allowed, but say so** in a comment. `doctor` reports FAIL when `usage` stops answering.

## Testing without touching your real pool

Create the sandbox **outside `~/.hermes`**. Hermes treats any `HERMES_HOME` under `~/.hermes` as part of your real install. When the sandbox has no accounts for a provider, it then falls back to *reading* `~/.hermes/auth.json`, and a `usage` or `balance` run could spend a real single-use refresh token and sign that account out. A sandbox elsewhere is a separate data root.

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

Usage needs a real account, so test `usage` and `balance --dry-run` with one, and say in the pull request which account type you tested (for example Pro, Team, or API key).
