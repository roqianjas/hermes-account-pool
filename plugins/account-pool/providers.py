"""Provider adapters for account-pool.

The core plugin (list, check, park, unpark, relogin, who, doctor, timed parks,
refresh-cooldown recovery, sign-in alerts) works for every provider in the
Hermes credential pool. Anything that needs a provider's own API lives here:

    identity(entry)        -> real account email, for `check` and `relogin`
    usage(entry)           -> (percent_used, resets_at_epoch[, detail]) for
                              `usage`, `balance`, `report` and the "all accounts
                              high" alert. With several limits (e.g. 5-hour and
                              weekly) return the most constraining one and put the
                              breakdown in `detail`, a short text shown by `usage`
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

import base64
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
    last_error = ""               # why the last usage() returned None (shown next to "n/a")

    def identity(self, entry):
        return None

    def explain(self, err, entry) -> str:
        """Short reason text for a failed usage request."""
        code = getattr(err, "code", None)
        if code == 429:
            return "usage endpoint rate-limited, retry in a few minutes"
        if code == 401:
            return ("access token expired, refreshed on next use" if token_expired(entry)
                    else "sign-in rejected (401)")
        if code:
            return f"usage endpoint HTTP {code}"
        return f"usage endpoint unreachable ({type(err).__name__})"

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


def jwt_claims(token) -> dict:
    """Unverified JWT payload (only used to read exp/email, never to trust a token)."""
    try:
        part = str(token).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def token_expired(entry) -> bool:
    """True when the access token expires within a minute.

    Uses expires_at_ms when the pool stores it (anthropic), otherwise the JWT
    `exp` claim (openai-codex). Unknown expiry counts as expired, which only
    means "refresh before use".
    """
    ms = getattr(entry, "expires_at_ms", None)
    if not ms:
        exp = jwt_claims(getattr(entry, "access_token", "") or "").get("exp")
        ms = exp * 1000 if isinstance(exp, (int, float)) else 0
    return ms / 1000 < time.time() + 60


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
        self.last_error = ""
        try:
            five = self._get(entry, "/api/oauth/usage").get("five_hour") or {}
        except Exception as x:
            self.last_error = self.explain(x, entry)
            return None
        util = five.get("utilization")
        if util is None:
            self.last_error = "no 5-hour data in the answer"
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


# ── openai-codex (ChatGPT Plus / Pro / Team sign-in) ─────────────────────────

class OpenAICodex(Adapter):
    name = "openai-codex"
    window = "5-hour + weekly"
    window_short = "codex"
    url = "https://chatgpt.com/backend-api/wham/usage"

    def _headers(self, entry) -> dict:
        token = getattr(entry, "access_token", "") or ""
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
                   "User-Agent": "codex_cli_rs/0.0.0 (Hermes Agent)", "originator": "codex_cli_rs"}
        try:
            from agent.codex_headers import codex_account_headers   # ChatGPT-Account-ID, residency
            headers.update(codex_account_headers(token))
        except Exception:
            acct = (jwt_claims(token).get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
            if acct:
                headers["ChatGPT-Account-ID"] = acct
        return headers

    def identity(self, entry):
        claims = jwt_claims(getattr(entry, "access_token", "") or "")
        email = (claims.get("https://api.openai.com/profile") or {}).get("email")
        return email or "(no email in token)"

    def usage(self, entry):
        # Undocumented endpoint used by Codex CLI's /status. None on any change.
        self.last_error = ""
        try:
            req = urllib.request.Request(self.url, headers=self._headers(entry))
            with urllib.request.urlopen(req, timeout=20) as r:
                rl = (json.loads(r.read()) or {}).get("rate_limit") or {}
        except Exception as x:
            self.last_error = self.explain(x, entry)
            return None
        windows = []
        for key, short in (("primary_window", "5h"), ("secondary_window", "week")):
            w = rl.get(key) or {}
            if w.get("used_percent") is None:
                continue
            secs = w.get("limit_window_seconds") or 0
            if secs and key == "primary_window" and secs != 18000:
                short = f"{secs // 3600}h"
            reset = w.get("reset_at")
            if reset is None and w.get("reset_after_seconds") is not None:
                reset = time.time() + float(w["reset_after_seconds"])
            windows.append((short, float(w["used_percent"]), float(reset) if reset else None))
        if not windows:
            self.last_error = "no limit data in the answer"
            return None
        short, pct, reset = max(windows, key=lambda x: x[1])
        if rl.get("limit_reached") or rl.get("allowed") is False:
            pct = 100.0
        detail = " · ".join(f"{n} {p:.0f}%" for n, p, _ in windows)
        return pct, reset, detail

    def refresh_parked(self, record: dict):
        from hermes_cli.auth_codex import refresh_codex_oauth_pure
        new = refresh_codex_oauth_pure(record.get("access_token") or "", record.get("refresh_token") or "")
        out = {"access_token": new["access_token"], "refresh_token": new["refresh_token"]}
        if new.get("last_refresh"):
            out["last_refresh"] = new["last_refresh"]
        return out


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Anthropic(), OpenAICodex())}


def get(provider: str) -> Adapter:
    """Adapter for a provider; a no-op Adapter when none is registered."""
    return ADAPTERS.get(provider) or Adapter()


def with_usage() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.has_usage]
