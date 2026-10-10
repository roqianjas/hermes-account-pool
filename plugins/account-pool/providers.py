"""Provider adapters for account-pool.

The core plugin (list, check, park, unpark, relogin, who, doctor, timed parks,
refresh-cooldown recovery, sign-in alerts) works for every provider in the
Hermes credential pool. Anything that needs a provider's own API lives here:

    identity(entry)        -> real account email, for `check` and `relogin`
    usage(entry)           -> (percent_used, resets_at_epoch) for `usage`,
                              `balance`, `report` and the "all accounts high" alert
    refresh_parked(record) -> new token fields for a PARKED OAuth account whose
                              access token expired (pool accounts are refreshed
                              by Hermes itself)

`entry` is a Hermes PooledCredential, or any object with `access_token`,
`auth_type` and `expires_at_ms`. Every method may return None ("not available");
the core then skips that feature for the account instead of failing.

Adding a provider: subclass Adapter, set `name` to the Hermes provider id (as in
`hermes auth list`), implement what the provider's API allows, and add an
instance to ADAPTERS. See CONTRIBUTING.md.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime


class Adapter:
    name = ""
    window = "usage window"       # shown in output, e.g. "5-hour"
    window_short = "window"       # used in bench reasons, e.g. "5h"
    oauth_only = True             # only OAuth entries carry account-level data

    def identity(self, entry):
        return None

    def usage(self, entry):
        return None

    def refresh_parked(self, record: dict):
        return None

    @property
    def has_usage(self) -> bool:
        return type(self).usage is not Adapter.usage

    @property
    def has_identity(self) -> bool:
        return type(self).identity is not Adapter.identity


def token_expired(entry) -> bool:
    return (getattr(entry, "expires_at_ms", None) or 0) / 1000 < time.time() + 60


# ── anthropic (Claude Pro / Max / Team OAuth) ───────────────────────────────

class Anthropic(Adapter):
    name = "anthropic"
    window = "5-hour"
    window_short = "5h"
    base = "https://api.anthropic.com"

    def _get(self, entry, path: str) -> dict:
        req = urllib.request.Request(self.base + path, headers={
            "Authorization": f"Bearer {getattr(entry, 'access_token', '') or ''}",
            "anthropic-beta": "oauth-2025-04-20",
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def identity(self, entry):
        try:
            acc = self._get(entry, "/api/oauth/profile").get("account") or {}
            return acc.get("email") or acc.get("email_address") or "?"
        except urllib.error.HTTPError as x:
            if x.code == 401 and token_expired(entry):
                return "(access token expired: normal, refreshed automatically on next use)"
            return f"(HTTP {x.code})"
        except Exception as x:
            return f"(lookup failed: {type(x).__name__})"

    def usage(self, entry):
        # Undocumented endpoint used by Claude Code's /usage. None on any change.
        try:
            five = self._get(entry, "/api/oauth/usage").get("five_hour") or {}
        except Exception:
            return None
        util = five.get("utilization")
        if util is None:
            return None
        reset = five.get("resets_at")
        try:
            reset = datetime.fromisoformat(reset).timestamp() if reset else None
        except Exception:
            reset = None
        return float(util), reset

    def refresh_parked(self, record: dict):
        from agent.anthropic_credentials import refresh_anthropic_oauth_pure
        new = refresh_anthropic_oauth_pure(record.get("refresh_token") or "",
                                           use_json=str(record.get("source", "")).endswith("hermes_pkce"))
        return {"access_token": new["access_token"], "refresh_token": new["refresh_token"],
                "expires_at_ms": new["expires_at_ms"]}


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Anthropic(),)}


def get(provider: str) -> Adapter:
    """Adapter for a provider; a no-op Adapter when none is registered."""
    return ADAPTERS.get(provider) or Adapter()


def with_usage() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.has_usage]
