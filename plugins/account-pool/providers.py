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
    wake(entry, model)     -> send one tiny request through the account so its
                              short (5-hour) window starts now; returns the model
                              used, raises with a readable message. Needs
                              `last_window`: usage() sets it to (percent, reset,
                              window seconds) of the short window, so the core can
                              tell a window that is not running
    signin_methods         -> how the Accounts page can sign an account in, the
                              first one is the default: "code" (paste the code
                              shown after authorizing), "browser" (the provider
                              sends the browser back to this computer) or
                              "device" (enter a code on the provider's page).
                              The sign-in itself is Hermes' own `hermes auth add`
                              (see signin.py); adapters never handle a login

`entry` is a Hermes PooledCredential. Adapters read its access token to call the
provider's API and never store or refresh it: Hermes refreshes expired tokens
(`CredentialPool.try_refresh_matching`). Every method may return None ("not
available"); the core then skips that feature for the account instead of failing.

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
    signin_methods = ()           # page sign-in methods (`hermes auth add`), the first is the default
    short_window_seconds = None   # length of the window `wake` starts (5 h)
    wake_model = ""               # model `wake` uses when none is set
    last_window = None            # (percent, reset, seconds) of the short window, set by usage()

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

    def wake(self, entry, model=None):
        """Start the account's short window with one tiny request. Returns the model used."""
        return None

    def models(self, entry):
        """(model ids this account can send a wake to, "live" | "fallback"), or None when the
        provider's list cannot be read. "fallback": Hermes' built-in list, not the account's own."""
        return None

    def default_model(self, ids=()) -> str:
        """The model a wake goes to when none is set; `ids` is the account's model list."""
        return self.wake_model

    @property
    def has_usage(self) -> bool:
        return type(self).usage is not Adapter.usage

    @property
    def has_wake(self) -> bool:
        return type(self).wake is not Adapter.wake

    @property
    def has_models(self) -> bool:
        return type(self).models is not Adapter.models

    @property
    def has_web_signin(self) -> bool:
        return bool(self.signin_methods)

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
    short_window_seconds = 5 * 3600
    wake_model = "claude-haiku-4-5"
    base = "https://api.anthropic.com"
    signin_methods = ("code",)

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
        self.last_window = None
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
        self.last_window = (float(util), reset, self.short_window_seconds)    # no window running: reset is None
        return float(util), reset

    def wake(self, entry, model=None):
        # Through Hermes' own Anthropic client: the same headers and Claude Code identity as a Hermes session.
        from agent.anthropic_adapter import build_anthropic_client
        try:
            from agent.anthropic_adapter import _CLAUDE_CODE_SYSTEM_PREFIX as prefix
        except ImportError:
            prefix = "You are Claude Code, Anthropic's official CLI for Claude."
        model = model or self.wake_model
        client = build_anthropic_client(getattr(entry, "access_token", "") or "", timeout=60)
        try:
            client.messages.create(model=model, max_tokens=1, system=[{"type": "text", "text": prefix}],
                                   messages=[{"role": "user", "content": "hi"}])
        except Exception as x:
            raise ValueError(self._wake_error(x, model)) from None
        return model

    def models(self, entry):
        # Hermes' own /v1/models fetcher: the OAuth headers and betas of a Hermes session, every page.
        from hermes_cli.models import _fetch_anthropic_models
        ids = _fetch_anthropic_models(timeout=10, api_key=getattr(entry, "access_token", "") or "")
        return (list(ids), "live") if ids else None

    @staticmethod
    def _wake_error(x, model) -> str:
        code = getattr(x, "status_code", None)
        body = getattr(x, "body", None)
        msg = ((body.get("error") or {}).get("message") if isinstance(body, dict) else None) or str(x)
        if code == 429:
            return "rate-limited: the account is at a limit, so its window is running already"
        if code == 401:
            return "sign-in rejected (401): sign in again"
        if code in (400, 404) and "model" in msg.lower():
            return f"model {model} not accepted ({msg[:120]}): set another with wake model=<id>"
        return f"HTTP {code}: {msg[:160]}" if code else f"{type(x).__name__}: {msg[:160]}"


# ── openai-codex (ChatGPT Plus / Pro / Team sign-in) ─────────────────────────

class OpenAICodex(Adapter):
    name = "openai-codex"
    window = "5-hour + weekly"
    window_short = "codex"
    short_window_seconds = 5 * 3600
    url = "https://chatgpt.com/backend-api/wham/usage"
    responses_url = "https://chatgpt.com/backend-api/codex/responses"

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
        self.last_window = None
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
            if key == "primary_window":
                # An idle window reads as a full one that resets `secs` from now, moving with every read.
                self.last_window = (float(w["used_percent"]), float(reset) if reset else None,
                                    float(secs or self.short_window_seconds))
        if not windows:
            self.last_error = "no limit data in the answer"
            return None
        short, pct, reset = max(windows, key=lambda x: x[1])
        if rl.get("limit_reached") or rl.get("allowed") is False:
            pct = 100.0
        detail = " · ".join(f"{n} {p:.0f}%" for n, p, _ in windows)
        return pct, reset, detail

    def _model_ids(self, entry):
        """The account's model list as Hermes reads it, and whether it came live.
        Left out: "-900k" (the same model with a longer context) and "spark" (its own usage limit,
        so a request to it does not start the 5-hour window)."""
        from hermes_cli.codex_models import get_codex_model_ids
        got = get_codex_model_ids(access_token=getattr(entry, "access_token", "") or "",
                                  base_url=getattr(entry, "base_url", None) or None)
        live = type(got).__name__ != "CuratedFallbackModels"     # Hermes' offline list when the API failed
        return [str(m) for m in got if not str(m).endswith("-900k") and "spark" not in str(m)], live

    def models(self, entry):
        ids, live = self._model_ids(entry)
        return (ids, "live" if live else "fallback") if ids else None

    def default_model(self, ids=()) -> str:
        """The smallest model in the list."""
        ids = list(ids or ())
        for part in ("mini", "nano", "luna"):
            hit = next((m for m in ids if part in m), None)
            if hit:
                return hit
        return ids[-1] if ids else "gpt-5.4-mini"

    def _pick_model(self, entry) -> str:
        """The smallest model this account offers (its live model list, as Hermes reads it)."""
        try:
            ids = self._model_ids(entry)[0]
        except Exception:
            ids = []
        return self.default_model(ids)

    def wake(self, entry, model=None):
        model = model or self._pick_model(entry)
        body = {"model": model, "instructions": "Answer with one word.", "store": False, "stream": True,
                "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
                "reasoning": {"effort": "low"}}
        headers = dict(self._headers(entry), **{"Content-Type": "application/json", "Accept": "text/event-stream"})
        for attempt in (1, 2):
            req = urllib.request.Request(self.responses_url, data=json.dumps(body).encode(), headers=headers,
                                         method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        kind = ev.get("type", "")
                        if kind == "response.completed":
                            return model
                        if kind in ("response.failed", "error", "response.incomplete"):
                            err = (ev.get("response") or {}).get("error") or ev.get("error") or {}
                            raise ValueError(f"the request failed: {(err.get('message') or kind)[:160]}")
                raise ValueError("the answer ended before the request completed")
            except urllib.error.HTTPError as x:
                try:
                    detail = json.loads(x.read() or b"{}")
                except Exception:
                    detail = {}
                msg = str(detail.get("detail") or (detail.get("error") or {}).get("message") or "")
                if x.code == 400 and attempt == 1 and "reasoning" in msg.lower():
                    body.pop("reasoning")                  # a model without reasoning effort: ask again without
                    continue
                if x.code == 429:
                    raise ValueError("rate-limited: the account is at a limit, so its window is running already") from None
                if x.code == 401:
                    raise ValueError("sign-in rejected (401): sign in again") from None
                if x.code in (400, 404) and "model" in msg.lower():
                    raise ValueError(f"model {model} not accepted ({msg[:120]}): set another with wake model=<id>") from None
                raise ValueError(f"HTTP {x.code}: {msg[:160] or 'no detail'}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as x:
                raise ValueError(f"unreachable ({type(x).__name__})") from None
        raise ValueError("the request was refused twice")

    # Sign-in methods of `hermes auth add openai-codex`: "browser" (`--browser`: OpenAI sends the
    # browser back to http://localhost:1455/auth/callback; works for ChatGPT workspaces that turned
    # device codes off) and "device" (a code entered on OpenAI's page).
    signin_methods = ("browser", "device")


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Anthropic(), OpenAICodex())}


def get(provider: str) -> Adapter:
    """Adapter for a provider; a no-op Adapter when none is registered."""
    return ADAPTERS.get(provider) or Adapter()


def with_usage() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.has_usage]


def with_wake() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.has_wake]
