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
    signin_start()         -> start a sign-in the desktop page can finish without
    signin_step(state, code)  a terminal: "code" (paste the code shown after
                              authorizing) or "device" (enter a code on the
                              provider's page, then the page waits). Returns the
                              login result Hermes' own `auth add` stores

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
    window_seconds = None         # length of the window `reset` ends, when it is fixed (tokens per window)
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

    def signin_start(self):
        """{"kind": "code" | "device", "url", "user_code"?, "state": private dict kept by the server}."""
        return None

    def signin_step(self, state: dict, code: str = ""):
        """Login result (as `hermes auth add` gets it), or None while a device sign-in is pending.

        Raises ValueError with a message for the user when the sign-in failed.
        """
        return None

    @property
    def has_usage(self) -> bool:
        return type(self).usage is not Adapter.usage

    @property
    def has_web_signin(self) -> bool:
        return type(self).signin_start is not Adapter.signin_start

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
    window_seconds = 5 * 3600
    base = "https://api.anthropic.com"

    def _get(self, entry, path: str) -> dict:
        # Same headers as Hermes' own usage fetcher (agent/account_usage.py). Without a client
        # User-Agent the request goes out as "Python-urllib/3.x", which Anthropic rate-limits
        # (HTTP 429) far sooner than Claude Code clients: same token, same second, 429 vs 200.
        req = urllib.request.Request(self.base + path, headers={
            "Authorization": f"Bearer {getattr(entry, 'access_token', '') or ''}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/2.1.0",
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

    # Same PKCE flow as Hermes' run_hermes_oauth_login_pure(), split in two steps so a page can
    # show the link and take the pasted code (the CLI version reads it with input()).
    def signin_start(self):
        import secrets
        from urllib.parse import urlencode
        from agent import anthropic_credentials as ac
        verifier, challenge = ac._generate_pkce()
        state = secrets.token_urlsafe(32)
        params = {"code": "true", "client_id": ac._OAUTH_CLIENT_ID, "response_type": "code",
                  "redirect_uri": ac._OAUTH_REDIRECT_URI, "scope": ac._OAUTH_SCOPES,
                  "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
        return {"kind": "code", "url": "https://claude.ai/oauth/authorize?" + urlencode(params),
                "state": {"verifier": verifier, "state": state}}

    def signin_step(self, state: dict, code: str = ""):
        from agent import anthropic_credentials as ac
        code = (code or "").strip()
        if not code:
            raise ValueError("Paste the code shown after you authorize.")
        part, _, got = code.partition("#")
        if got != state["state"]:
            raise ValueError("This code belongs to another sign-in. Open the link from this window and copy the "
                             "whole code (it contains a #).")
        body = json.dumps({"grant_type": "authorization_code", "client_id": ac._OAUTH_CLIENT_ID, "code": part,
                           "state": got, "redirect_uri": ac._OAUTH_REDIRECT_URI,
                           "code_verifier": state["verifier"]}).encode()
        try:
            result = ac._post_oauth_token(body, content_type="application/json", timeout=15, what="exchange")
        except Exception as x:
            raise ValueError(f"Token exchange failed: {str(x)[:200] or type(x).__name__}. A code works once and "
                             f"only for a few minutes: start again.") from None
        if not result.get("access_token"):
            raise ValueError("The token answer had no access token.")
        return ac._oauth_token_state(result)


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

    # Same device-code flow as Hermes' _codex_device_code_login(), but each signin_step() checks
    # once instead of blocking, so the page polls and the user can cancel at any time.
    issuer = "https://auth.openai.com"

    def signin_start(self):
        from hermes_cli import auth_codex as ac
        d = ac._codex_request_device_code(self.issuer, ac.CODEX_OAUTH_CLIENT_ID)
        return {"kind": "device", "url": f"{self.issuer}/codex/device", "user_code": d["user_code"],
                "state": {"device_auth_id": d["device_auth_id"], "user_code": d["user_code"],
                          "interval": max(3.0, float(d.get("interval") or 5)), "last": 0.0}}

    def signin_step(self, state: dict, code: str = ""):
        import httpx
        from hermes_cli import auth_codex as ac
        from hermes_cli.auth import _utc_now_z
        if time.time() - state["last"] < state["interval"]:
            return None
        state["last"] = time.time()
        try:
            with ac._codex_http_client(timeout=httpx.Timeout(15.0)) as client:
                r = client.post(f"{self.issuer}/api/accounts/deviceauth/token",
                                json={"device_auth_id": state["device_auth_id"], "user_code": state["user_code"]},
                                headers={"Content-Type": "application/json"})
        except Exception as x:
            raise ValueError(f"Could not reach the sign-in service ({type(x).__name__}).") from None
        if r.status_code in (403, 404):            # not finished yet
            return None
        if r.status_code != 200:
            raise ValueError(f"The sign-in check answered HTTP {r.status_code}. Start again.")
        try:
            tokens = ac._codex_exchange_authorization_code(self.issuer, ac.CODEX_OAUTH_CLIENT_ID, r.json())
        except Exception as x:
            raise ValueError(f"Token exchange failed: {x}") from None
        return {"tokens": {"access_token": tokens.get("access_token", ""),
                           "refresh_token": tokens.get("refresh_token", "")},
                "base_url": ac._codex_base_url(), "last_refresh": _utc_now_z(), "auth_mode": "chatgpt",
                "source": "device-code"}


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Anthropic(), OpenAICodex())}


def get(provider: str) -> Adapter:
    """Adapter for a provider; a no-op Adapter when none is registered."""
    return ADAPTERS.get(provider) or Adapter()


def with_usage() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.has_usage]
