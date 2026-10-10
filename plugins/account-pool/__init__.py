"""`hermes account` — manage accounts in the Hermes credential pool.

Every command follows one pattern:

    hermes account <provider> <action> [target] [options]

    hermes account <provider> list             accounts in rotation + parked accounts
    hermes account <provider> check            health: dead, rate-limited, wrong label, duplicate
    hermes account <provider> usage            live usage per account (providers with a usage adapter)
    hermes account <provider> park <target>    take an account out of rotation, keep its login
    hermes account <provider> unpark <target>  put a parked account back into rotation
    hermes account <provider> balance          order accounts by live usage, bench nearly-full ones
    hermes account <provider> who|report|relogin|doctor|notify   (see `hermes account help`)
    hermes account help | hermes account <provider> help

`balance` is meant to run on a timer with `credential_pool_strategies.<provider>:
fill_first`: new sessions then always start on the least-used account, and an
account above the threshold is benched until its usage window resets.

Provider-specific code (usage, real identity, parked-token refresh) lives in
providers.py as adapters; everything else works for every pool provider.

Pool changes go through the credential pool API (remove_index, add_entry,
move_entry, mark_exhausted_and_rotate, reset_status), so locking and the
auth.json format stay owned by Hermes. Parked accounts are stored in
$HERMES_HOME/account-pool-parked.json (mode 600).
"""
from __future__ import annotations

import builtins
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

MARK = "[account-pool]"

_OUT = threading.local()


def _p(*args, sep: str = " ", end: str = "\n") -> None:
    """print() that the desktop backend can capture per thread (redirect_stdout is process-wide)."""
    stream = getattr(_OUT, "buf", None)
    if stream is None:
        builtins.print(*args, sep=sep, end=end)
    else:
        stream.write(sep.join(str(a) for a in args) + end)


@contextmanager
def _capture():
    """Collect everything _p() writes in this thread; yields the buffer."""
    prev = getattr(_OUT, "buf", None)
    _OUT.buf = io.StringIO()
    try:
        yield _OUT.buf
    finally:
        _OUT.buf = prev


def _load_providers():
    import importlib.util
    import sys
    name = "account_pool_providers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("providers.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


providers = _load_providers()


# ── storage ──────────────────────────────────────────────────────────────────

def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _parked_path() -> Path:
    return _home() / "account-pool-parked.json"


def _norm(provider: str) -> str:
    try:
        from hermes_cli.auth_commands import _normalize_provider
        return _normalize_provider(provider)
    except Exception:
        return (provider or "").strip().lower()


def _read_parked() -> list[dict]:
    path = _parked_path()
    legacy = _home() / "akun-claude-parked.json"          # from the earlier plugin
    if not path.exists() and legacy.exists():
        path = legacy
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text()).get("parked", [])
    except Exception:
        raise SystemExit(f"Parked-accounts file is corrupt: {path}")
    for it in items:
        it.setdefault("_provider", "anthropic")
    return items


def _write_parked(items: list[dict]) -> None:
    path = _parked_path()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"version": 3, "parked": items}, fh, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _pool(provider: str):
    from agent.credential_pool import load_pool
    return load_pool(provider)


def _entries(provider: str):
    return sorted(_pool(provider).entries(), key=lambda e: e.priority)


def _hhmm(ts) -> str:
    if not ts:
        return "?"
    if abs(ts - time.time()) > 20 * 3600:        # weekly windows: show the day
        return time.strftime("%a %H:%M", time.localtime(ts))
    return time.strftime("%H:%M", time.localtime(ts))


def _root() -> Path:
    """Global Hermes home (shared by every profile)."""
    home = _home()
    return home.parent.parent if home.parent.name == "profiles" else home


def _hermes_bin() -> str:
    return shutil.which("hermes") or str(Path.home() / ".local/bin/hermes")


def _hermes_env() -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(_root())
    return env


def _atomic_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


# ── settings, history, notifications ────────────────────────────────────────

CONFIG_DEFAULTS = {"notify": {"desktop": True, "telegram": "auto", "telegram_via": "default"},
                   "alert_all_above": 80}


def _config_path() -> Path:
    return _root() / "account-pool.json"


def _config() -> dict:
    cfg = json.loads(json.dumps(CONFIG_DEFAULTS))
    user = _load_json(_config_path(), {})
    cfg["notify"].update(user.get("notify") or {})
    for k, v in user.items():
        if k != "notify":
            cfg[k] = v
    return cfg


def _history_path() -> Path:
    return _root() / "account-pool-history.jsonl"


def _record_history(provider: str, known) -> None:
    path = _history_path()
    known = [(e, u) for e, u in known if e.label not in _CACHED]     # never re-record a cached value
    if not known:
        return
    line = json.dumps({"ts": round(time.time()), "provider": provider,
                       "usage": {e.label: u[0] for e, u in known},
                       "reset": {e.label: u[1] for e, u in known}})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(line + "\n")
    if path.stat().st_size > 3_000_000:              # keep ~14 days
        cutoff = time.time() - 14 * 86400
        keep = [l for l in path.read_text().splitlines() if _load_line_ts(l) >= cutoff]
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(keep) + "\n")
        os.replace(tmp, path)


def _load_line_ts(line: str) -> float:
    try:
        return float(json.loads(line).get("ts", 0))
    except Exception:
        return 0.0


def _read_history(provider: str, since: float) -> list[dict]:
    path = _history_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("provider") == provider and rec.get("ts", 0) >= since:
            out.append(rec)
    return out


def _telegram_target(cfg: dict):
    t = (cfg.get("notify") or {}).get("telegram")
    if not t:
        return None
    if t != "auto":
        return t
    env = _root() / ".env"
    try:
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_ALLOWED_USERS="):
                first = line.split("=", 1)[1].strip().strip("'\"").split(",")[0].strip()
                if first:
                    return f"telegram:{first}"
    except Exception:
        pass
    return None


def _notify(title: str, body: str) -> list[str]:
    """Send to every configured channel; return the channels that succeeded."""
    cfg = _config()
    sent = []
    if cfg["notify"].get("desktop") and shutil.which("notify-send"):
        try:
            r = subprocess.run(["notify-send", "-a", "Hermes", "-i", "dialog-warning", title, body],
                               capture_output=True, timeout=10)
            if r.returncode == 0:
                sent.append("desktop")
        except Exception:
            pass
    target = _telegram_target(cfg)
    if target:
        via = (cfg["notify"].get("telegram_via") or "default").strip()
        cmd = [_hermes_bin()]
        env = _hermes_env()
        if via != "default":                      # send with another profile's bot token
            cmd += ["-p", via]
            env.pop("HERMES_HOME", None)
        try:
            r = subprocess.run(cmd + ["send", "-q", "-t", target, "-s", title, body],
                               capture_output=True, timeout=90, env=env)
            if r.returncode == 0:
                sent.append("telegram")
        except Exception:
            pass
    return sent


def _alerts_path() -> Path:
    return _root() / "account-pool-alerts.json"


def _run_alerts(provider: str, pool, known) -> list[str]:
    """Notify once per new problem; clear the record when it is resolved."""
    cfg = _config()
    limit = float(cfg.get("alert_all_above", 80))
    current = {}
    for e in pool.entries():
        if getattr(e, "last_status", None) == "dead":
            current[f"{provider}:dead:{e.id}"] = (
                f"Hermes: {e.label} needs sign-in",
                f"{provider} rejected the login for {e.label}; it is out of rotation.\n"
                f"Fix: hermes account {provider} relogin {e.label}")
    if known and all(u[0] >= limit for _, u in known):
        lo_e, lo_u = min(known, key=lambda r: r[1][0])
        current[f"{provider}:all-high"] = (
            f"Hermes: every {provider} account is above {limit:.0f}%",
            f"Lowest: {lo_e.label} at {lo_u[0]:.0f}% (resets {_hhmm(lo_u[1])}). "
            f"When all are full, Hermes switches to its fallback model.")
    state = _load_json(_alerts_path(), {})
    mine = {k: v for k, v in state.items() if k.startswith(provider + ":")}
    other = {k: v for k, v in state.items() if not k.startswith(provider + ":")}
    actions = []
    for key, (title, body) in current.items():
        if key not in mine:
            sent = _notify(title, body)
            actions.append(f"alert: {title} -> {', '.join(sent) or 'no channel delivered'}")
    if f"{provider}:all-high" in mine and f"{provider}:all-high" not in current:
        lo_e, lo_u = min(known, key=lambda r: r[1][0]) if known else (None, None)
        body = f"{lo_e.label} is at {lo_u[0]:.0f}%." if lo_e else ""
        sent = _notify(f"Hermes: {provider} accounts available again", body)
        actions.append(f"alert cleared: all-high -> {', '.join(sent) or 'no channel delivered'}")
    now = time.time()
    other.update({k: mine.get(k, now) for k in current})
    _atomic_json(_alerts_path(), other)
    return actions


# ── provider adapters (providers.py) ─────────────────────────────────────────

_token_expired = providers.token_expired


def _oauth(entry) -> bool:
    return getattr(entry, "auth_type", "") == "oauth"


def _identity(provider, entry):
    ad = providers.get(provider)
    if not ad.has_identity or (ad.oauth_only and not _oauth(entry)):
        return None
    return ad.identity(entry)


def _usage_full(provider, entry):
    """(percent, reset_epoch, detail_text) or None."""
    ad = providers.get(provider)
    ad.last_error = ""
    if not ad.has_usage:
        return None
    if ad.oauth_only and not _oauth(entry):
        ad.last_error = "API key: no account usage"
        return None
    try:
        u = ad.usage(entry)
    except Exception as x:
        ad.last_error = f"adapter error: {type(x).__name__}"
        u = None
    if not u:
        transient = ad.last_error.startswith(("usage endpoint rate-limited", "usage endpoint unreachable",
                                              "usage endpoint HTTP 5"))
        label = getattr(entry, "label", None)
        return (_cached_usage(provider, label) if transient and label else None)
    _CACHED.discard(getattr(entry, "label", None))
    return float(u[0]), u[1], (u[2] if len(u) > 2 else "")


_CACHED: set = set()          # labels whose usage came from history this run (never re-recorded)
_SNAP: dict = {}


def _recent_snapshots(provider: str) -> list:
    """History records for the provider, newest first (reads only the end of the file)."""
    if provider not in _SNAP:
        recs = []
        try:
            with open(_history_path(), "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 262144))
                for line in reversed(fh.read().decode(errors="replace").splitlines()):
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("provider") == provider:
                        recs.append(r)
        except OSError:
            pass
        _SNAP[provider] = recs
    return _SNAP[provider]


def _cached_usage(provider: str, label: str, max_age: float = 900):
    """Last recorded usage for an account when the endpoint is temporarily unavailable.

    Takes the newest snapshot that contains the account (a run that used a cached value
    does not record it again), only if it is younger than 15 minutes and its window has
    not reset yet.
    """
    now = time.time()
    for rec in _recent_snapshots(provider):
        age = now - float(rec.get("ts", 0) or 0)
        if age > max_age:
            return None
        pct = (rec.get("usage") or {}).get(label)
        if pct is None:
            continue
        reset = (rec.get("reset") or {}).get(label)
        if reset and reset <= now:
            return None
        _CACHED.add(label)
        return float(pct), reset, f"last known, {max(1, round(age / 60))} min ago"
    return None


def _reset_run_state() -> None:
    """Forget per-run caches. A CLI run is one process; the desktop backend calls this per request."""
    _CACHED.clear()
    _SNAP.clear()


def _usage_reason(provider) -> str:
    return getattr(providers.get(provider), "last_error", "") or ""


def _usage(provider, entry):
    """(percent, reset_epoch) or None: the value balance, report and alerts use."""
    u = _usage_full(provider, entry)
    return (u[0], u[1]) if u else None


def _has_usage(provider) -> bool:
    return providers.get(provider).has_usage


def _window(provider) -> str:
    return providers.get(provider).window


def _no_usage_text(provider) -> str:
    avail = ", ".join(providers.with_usage()) or "none"
    return (f"No usage adapter for '{provider}' yet (available: {avail}). "
            f"Adapters live in {Path(__file__).with_name('providers.py')}.")


def _refresh_if_expired(provider: str, pool, entry):
    """Refresh an expired access token through the pool so usage can be read."""
    if not _oauth(entry) or not _token_expired(entry) or getattr(entry, "last_status", None) == "dead":
        return entry
    try:
        return pool.try_refresh_matching(credential_id=entry.id) or entry
    except Exception:
        return entry


def _require_usage(provider: str) -> None:
    if not _has_usage(provider):
        raise SystemExit(_no_usage_text(provider))


# ── status text ──────────────────────────────────────────────────────────────

def _is_cooling(entry) -> bool:
    """Exhausted without a provider limit code: a failed token refresh (network)."""
    return (getattr(entry, "last_status", None) == "exhausted"
            and MARK not in (getattr(entry, "last_error_message", None) or "")
            and getattr(entry, "last_error_code", None) not in (429, 402)
            and not getattr(entry, "last_error_reason", None))


def _entry_state(entry) -> str:
    """active, BENCHED (by balance), LIMITED (by the provider), COOLING (failed refresh) or DEAD."""
    status = getattr(entry, "last_status", None)
    if status == "dead":
        return "DEAD"
    if status == "exhausted":
        if MARK in (getattr(entry, "last_error_message", None) or ""):
            return "BENCHED"
        return "COOLING" if _is_cooling(entry) else "LIMITED"
    return "active"


def _problems(provider, entry, ident):
    out = []
    status = getattr(entry, "last_status", None)
    msg = getattr(entry, "last_error_message", None) or ""
    if status == "dead":
        out.append(f"DEAD: sign in again ({getattr(entry, 'last_error_reason', None) or '?'})")
    elif status == "exhausted":
        code = getattr(entry, "last_error_code", None)
        reset = getattr(entry, "last_error_reset_at", None)
        if MARK in msg:
            out.append(f"BENCHED by balance: {msg.replace(MARK, '').strip()}, back at {_hhmm(reset)}")
        elif code in (429, 402) or getattr(entry, "last_error_reason", None):
            out.append(f"RATE LIMITED (HTTP {code or '?'}), resets around {_hhmm(reset)}")
        else:
            out.append(f"COOLING DOWN since {_hhmm(getattr(entry, 'last_status_at', None))}: token refresh "
                       f"failed (usually a network drop), not a quota limit. The balance timer retries it "
                       f"automatically; now: hermes auth refresh {provider} {entry.id}")
    if ident and "@" in ident and ident.lower() != (entry.label or "").lower():
        out.append(f"WRONG LABEL: the real account is {ident}")
    return out


# ── actions ──────────────────────────────────────────────────────────────────

def _cmd_list(args) -> int:
    provider = _norm(args.provider)
    entries = _entries(provider)
    parked = [p for p in _read_parked() if p["_provider"] == provider]
    _p(f"[{provider}] in rotation ({len(entries)}):")
    for n, e in enumerate(entries, 1):
        _p(f"  #{n}  {e.label:34s} id={e.id}  status={getattr(e, 'last_status', None) or 'ok'}")
    _p(f"[{provider}] parked ({len(parked)}):" + ("" if parked else " -"))
    for p in parked:
        until = f"  until {p['_until_h']}" if p.get("_until") else ""
        _p(f"  -   {p.get('label', '?'):34s} id={p.get('id')}  since {p.get('_parked_at_h', '?')}{until}")
    return 0


def _cmd_check(args) -> int:
    provider = _norm(args.provider)
    if _no_accounts(provider):
        return 0
    entries = _entries(provider)
    parked = [p for p in _read_parked() if p["_provider"] == provider]
    note = "" if providers.get(provider).has_identity else "   (real-identity lookup not available for this provider)"
    _p(f"[{provider}] in rotation: {len(entries)}   parked: {len(parked)}{note}")
    rows = []
    for e in entries:
        ident = _identity(provider, e)
        rows.append([e, ident, _problems(provider, e, ident)])

    def key(r):
        return (r[1] if r[1] and "@" in r[1] else r[0].label or "").lower()

    dupes = {k for k, v in Counter(key(r) for r in rows).items() if k and v > 1}
    bad = 0
    for n, row in enumerate(rows, 1):
        e, ident, probs = row
        if key(row) in dupes:
            probs.append("DUPLICATE: the same account is registered more than once")
        bad += bool(probs)
        _p(f"  {'OK' if not probs else '!!'} #{n} id={e.id}  label={e.label}")
        if ident is not None:
            _p(f"        account : {ident}")
        for p in probs:
            _p(f"        issue   : {p}")
    for p in parked:
        _p(f"  -- parked  id={p.get('id')}  label={p.get('label')}  (since {p.get('_parked_at_h', '?')})")
    _p(f"  {bad} account(s) need attention." if bad else "  All accounts in rotation are healthy.")
    return 1 if bad else 0


def _refresh_parked(provider: str, item: dict) -> dict:
    """Refresh an expired access token of a PARKED OAuth account via its adapter.

    OAuth refresh tokens are often single-use (Anthropic's are), so the rotated pair is written back
    to the parked file under a lock straight after the POST. On invalid_grant the
    record is flagged so `usage` shows it as needing a new sign-in.
    """
    from types import SimpleNamespace
    ad = providers.get(provider)
    if type(ad).refresh_parked is providers.Adapter.refresh_parked:
        return item
    if item.get("auth_type") != "oauth" or item.get("_dead"):
        return item
    if not _token_expired(SimpleNamespace(expires_at_ms=item.get("expires_at_ms"), access_token=item.get("access_token"))):
        return item
    import fcntl
    lock_path = _parked_path().with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        items = _read_parked()                     # re-read: another run may have refreshed it
        cur = next((p for p in items if p["_provider"] == provider and p.get("id") == item.get("id")), None)
        if cur is None:
            return item
        if not _token_expired(SimpleNamespace(expires_at_ms=cur.get("expires_at_ms"), access_token=cur.get("access_token"))):
            return cur
        try:
            new = ad.refresh_parked(cur)
            if not new:
                return cur
            cur.update(new)
            cur.pop("_dead", None)
        except Exception as x:
            text = str(x)
            if "invalid_grant" in text or "400" in text:
                cur["_dead"] = text[:160]
            else:
                return cur                             # network etc.: leave untouched
        _write_parked(items)
        return cur


def _pool_providers() -> list:
    try:
        data = json.loads((_root() / "auth.json").read_text())
        names = {k for k, v in (data.get("credential_pool") or {}).items() if v}
    except Exception:
        names = set()
    names |= {p["_provider"] for p in _read_parked()}
    return sorted(names)


def _known_provider(provider: str) -> bool:
    if provider.startswith("custom") or provider in providers.ADAPTERS or provider in _pool_providers():
        return True
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
        if provider in PROVIDER_REGISTRY:
            return True
    except Exception:
        return True                       # cannot tell: do not block
    return provider in ("openrouter", "nous", "openai", "custom")


def _no_accounts(provider: str) -> bool:
    """True (after printing a hint) when the provider has no accounts at all, parked included."""
    if _entries(provider) or any(p["_provider"] == provider for p in _read_parked()):
        return False
    _p(f"[{provider}] No {provider} accounts yet. Add one: hermes account {provider} add <email>")
    return True


def _usage_rows(provider: str) -> list:
    """Live usage of every account, rotation first, then parked.

    Each row: label, id, state (see _entry_state, or PARKED), parked, usage = (percent, reset_epoch,
    detail) or None, and note = why usage is missing ("dead" for a parked account whose login died).
    """
    from types import SimpleNamespace
    pool = _pool(provider)
    rows = []
    for e in sorted(pool.entries(), key=lambda x: x.priority):
        e = _refresh_if_expired(provider, pool, e)
        state = _entry_state(e)
        u = _usage_full(provider, e) if state != "DEAD" else None
        rows.append({"label": e.label, "id": e.id, "state": state, "parked": False, "usage": u,
                     "note": "" if u or state == "DEAD" else _usage_reason(provider)})
    for item in [p for p in _read_parked() if p["_provider"] == provider]:
        item = _refresh_parked(provider, item)
        row = {"label": item.get("label", "?"), "id": item.get("id"), "state": "PARKED", "parked": True,
               "usage": None, "note": "dead"}
        if not item.get("_dead"):
            ent = SimpleNamespace(access_token=item.get("access_token"), auth_type=item.get("auth_type"))
            row["usage"] = _usage_full(provider, ent)
            row["note"] = "" if row["usage"] else _usage_reason(provider)
        rows.append(row)
    return rows


def _cmd_usage(args) -> int:
    provider = _norm(args.provider)
    _require_usage(provider)
    if _no_accounts(provider):
        return 0
    rows = []                                          # (label, state, usage)
    for r in _usage_rows(provider):
        state = "LIMITED" if r["state"] == "COOLING" else r["state"]
        rows.append((r["label"], state, r["usage"] or r["note"]))

    order = {"active": 0, "BENCHED": 1, "LIMITED": 1, "PARKED": 2, "DEAD": 3}
    rows.sort(key=lambda r: (order[r[1]], r[2][0] if isinstance(r[2], tuple) else 999))
    _p(f"[{provider}] {_window(provider)} usage")
    _p(f"  {'account':34s} {'state':8s} {'used':>5s}  {'':22s}  resets")
    last = None
    for label, state, u in rows:
        group = "parked" if state == "PARKED" else "rotation"
        if group != last:
            _p(f"  -- {'in rotation' if group == 'rotation' else 'parked (not used by Hermes)'} --")
            last = group
        if u == "dead" and state == "PARKED":
            _p(f"  {label:34s} {state:8s}   n/a  sign-in expired: hermes account {provider} remove {label}, then add {label}")
        elif u is None or isinstance(u, str):
            _p(f"  {label:34s} {state:8s}   n/a" + (f"  ({u})" if u else ""))
        else:
            util, reset, detail = u
            fill = int(min(util, 100) // 5)
            ch = "=" if state == "PARKED" else "#"
            bar = ch * fill + "." * (20 - fill)
            extra = f"   ({detail})" if detail else ""
            _p(f"  {label:34s} {state:8s} {util:4.0f}%  [{bar}]  {_hhmm(reset)}{extra}")
    return 0


def _parse_until(text: str) -> float:
    t = text.strip().lower()
    m = re.fullmatch(r"\+?(\d+)\s*(m|min|h|hr|d)", t)
    if m:
        return time.time() + int(m[1]) * {"m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400}[m[2]]
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        if int(m[1]) > 23 or int(m[2]) > 59:
            raise SystemExit(f"Cannot read --until '{text}'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'.")
        now = datetime.now()
        at = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        return at.timestamp()
    try:
        at = datetime.fromisoformat(text).timestamp()
    except Exception:
        raise SystemExit(f"Cannot read --until '{text}'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'.")
    if at <= time.time():
        raise SystemExit(f"--until '{text}' is in the past.")
    return at


def _timer_active() -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", "hermes-account-balance.timer"],
                              timeout=10).returncode == 0
    except Exception:
        return False


def _cmd_park(args) -> int:
    provider = _norm(args.provider)
    until = _parse_until(args.until) if args.until else None
    pool = _pool(provider)
    index, matched, error = pool.resolve_target(args.target)
    if matched is None or index is None:
        item = _find_parked(provider, args.target)
        if item:
            raise SystemExit(f"{item.get('label', args.target)} is already parked. "
                             f"Undo: hermes account {provider} unpark {item.get('label', args.target)}")
        raise SystemExit(f"{error} See: hermes account {provider} list")
    alive = [e for e in pool.entries() if getattr(e, "last_status", None) != "dead"]
    if len(alive) <= 1 and any(e.id == matched.id for e in alive):
        raise SystemExit(f"Refused: this is the last working {provider} account. Sessions would lose access.")
    payload = matched.to_dict()
    payload.update(_provider=provider, _parked_at=time.time(), _parked_at_h=time.strftime("%Y-%m-%d %H:%M"))
    if until:
        payload.update(_until=until, _until_h=time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
    parked = [p for p in _read_parked() if not (p["_provider"] == provider and p.get("id") == matched.id)]
    parked.append(payload)
    _write_parked(parked)                       # save first, then remove from the pool
    removed = pool.remove_index(index)
    if removed is None:
        _write_parked([p for p in parked if p is not payload])
        raise SystemExit("Could not remove the account from the pool; nothing changed.")
    if until:
        _p(f"Parked [{provider}]: {removed.label} (id={removed.id}) until {payload['_until_h']}.")
        _p("It returns to rotation on the first balance run after that time (timer runs every 5 minutes).")
        if not _timer_active():
            _p("WARNING: the balance timer is not active, so it will NOT come back by itself.")
    else:
        _p(f"Parked [{provider}]: {removed.label} (id={removed.id}). Out of rotation until unparked.")
    _p(f"Undo: hermes account {provider} unpark {removed.label}")
    return 0


def _cmd_unpark(args) -> int:
    from agent.credential_pool import PooledCredential
    provider = _norm(args.provider)
    raw = str(args.target).strip().lower()
    parked = _read_parked()
    hits = [p for p in parked if p["_provider"] == provider
            and (p.get("id", "").lower() == raw or (p.get("label") or "").lower() == raw)]
    if len(hits) != 1:
        names = ", ".join(p.get("label", "?") for p in parked if p["_provider"] == provider) or "(none)"
        raise SystemExit(f'No parked {provider} account named "{args.target}". Parked: {names}')
    hit = hits[0]
    payload = {k: v for k, v in hit.items() if not k.startswith("_")}
    rest = [p for p in parked if p is not hit]
    pool = _pool(provider)
    if any(e.id == payload.get("id") for e in pool.entries()):
        _write_parked(rest)
        _p(f"{payload.get('label')} is already in rotation; parked record cleared.")
        return 0
    entry = pool.add_entry(PooledCredential.from_dict(provider, payload))
    _write_parked(rest)
    _p(f"Unparked [{provider}]: {entry.label} (id={entry.id}), back in rotation.")
    ident = _identity(provider, entry)
    if ident is None:
        _p("Login check not available for this provider.")
    elif "@" in ident:
        _p(f"Login check: OK ({ident})")
    else:
        _p(f"Login check: {ident}. If requests keep failing, sign in to this account again.")
    return 0


def _cmd_balance(args) -> int:
    provider = _norm(args.provider)
    if not _entries(provider) and not any(p["_provider"] == provider for p in _read_parked()):
        _p(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{provider}] balance: no accounts, nothing to do.")
        return 0
    threshold = float(args.threshold)
    dry = bool(args.dry_run)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    actions = []

    # 1. timed parks that are due
    for item in [p for p in _read_parked() if p["_provider"] == provider and p.get("_until")]:
        if item["_until"] <= time.time():
            actions.append(f"unpark {item.get('label')} (park --until {item.get('_until_h')} reached)")
            if not dry:
                from types import SimpleNamespace
                with _capture():
                    try:
                        _cmd_unpark(SimpleNamespace(provider=provider, target=item.get("id")))
                    except SystemExit as x:
                        actions[-1] += f" FAILED: {x}"

    pool = _pool(provider)

    # 2. accounts cooling down after a failed token refresh: retry the refresh
    for e in list(pool.entries()):
        if _is_cooling(e):
            if dry:
                actions.append(f"retry token refresh for {e.label} (cooling down)")
                continue
            try:
                fixed = pool.try_refresh_matching(credential_id=e.id)
            except Exception:
                fixed = None
            after = next((x for x in pool.entries() if x.id == e.id), None)
            ok = fixed is not None and after is not None and getattr(after, "last_status", None) not in ("exhausted", "dead")
            actions.append(f"{'recovered' if ok else 'still cooling down'}: {e.label} (token refresh retried)")

    if not _has_usage(provider):
        # No usage adapter: timed parks, refresh recovery and sign-in alerts still run.
        if not dry:
            try:
                actions += _run_alerts(provider, pool, [])
            except Exception as x:
                actions.append(f"alerts failed: {x}")
        _p(f"{stamp} [{provider}] balance{' (dry run)' if dry else ''}: no usage adapter, order unchanged.")
        for a in actions:
            _p("  - " + a)
        return 0

    rows = []
    for e in sorted(pool.entries(), key=lambda x: x.priority):
        if getattr(e, "last_status", None) == "dead":
            rows.append((e, None, "dead"))
            continue
        if not dry:
            e = _refresh_if_expired(provider, pool, e)
        rows.append((e, _usage(provider, e), None))

    known = [(e, u) for e, u, flag in rows if u is not None]
    if not known:
        if not dry:
            try:
                actions += _run_alerts(provider, pool, [])
            except Exception as x:
                actions.append(f"alerts failed: {x}")
        _p(f"{stamp} [{provider}] balance: usage unavailable for every account; order unchanged.")
        for a in actions:
            _p("  - " + a)
        return 0

    full = [(e, u) for e, u in known if u[0] >= threshold]
    # Never bench the whole pool for being "nearly" full: keep anything below 100%
    # usable when no account is under the threshold.
    if len(full) == len(known):
        full = [(e, u) for e, u in known if u[0] >= 100]

    full_ids = {e.id for e, _ in full}
    for e, (util, reset) in full:
        msg = f"{MARK} {providers.get(provider).window_short} usage {util:.0f}% >= {threshold:.0f}%"
        prev = getattr(e, "last_error_reset_at", None)
        if getattr(e, "last_status", None) == "exhausted" and prev and reset and abs(prev - reset) < 300:
            continue
        actions.append(f"bench {e.label} ({util:.0f}%) until {_hhmm(reset)}")
        if not dry:
            pool.mark_exhausted_and_rotate(status_code=429, credential_id=e.id, error_context={
                "reason": "rate_limit_error", "message": msg, "reset_at": reset or time.time() + 3600})

    for e, u in known:
        if e.id in full_ids:
            continue
        if getattr(e, "last_status", None) == "exhausted" and MARK in (getattr(e, "last_error_message", None) or ""):
            actions.append(f"release {e.label} ({u[0]:.0f}%)")
            if not dry:
                pool.reset_status(e.id)

    def sort_key(row):
        e, u, flag = row
        if flag == "dead":
            return 1000
        if u is None:
            return 500           # unknown usage: after every known-good account
        return u[0] + (200 if e.id in full_ids else 0)

    order = sorted(rows, key=sort_key)
    current = [e.id for e, _, _ in sorted(rows, key=lambda r: r[0].priority)]
    target = [e.id for e, _, _ in order]
    if current != target:
        actions.append("order: " + " > ".join(
            f"{e.label.split('@')[0]}({u[0]:.0f}%)" if u else f"{e.label.split('@')[0]}(n/a)"
            for e, u, _ in order))
        if not dry:
            for pos, cid in enumerate(target):
                pool.move_entry(cid, pos)

    if not dry:
        try:
            _record_history(provider, known)
        except Exception as x:
            actions.append(f"history not written: {x}")
        try:
            actions += _run_alerts(provider, pool, known)
        except Exception as x:
            actions.append(f"alerts failed: {x}")

    head = f"{stamp} [{provider}] balance{' (dry run)' if dry else ''}:"
    _p(head + (" no change." if not actions else ""))
    for a in actions:
        _p("  - " + a)
    return 0

def _timer_info() -> dict:
    """Balance timer state from systemd: active, running, result, last (text), next (text)."""
    out = {"active": _timer_active(), "running": False, "result": "?", "last": "never", "next": ""}
    try:
        res = subprocess.run(["systemctl", "--user", "show", "hermes-account-balance.service",
                              "-p", "Result", "-p", "ExecMainExitTimestamp", "-p", "ActiveState"],
                             capture_output=True, text=True, timeout=10).stdout
        info = dict(l.split("=", 1) for l in res.strip().splitlines() if "=" in l)
        out["result"] = info.get("Result", "?")
        out["running"] = info.get("ActiveState") in ("activating", "active", "reloading")
        last = info.get("ExecMainExitTimestamp") or ""
        out["last"] = "running now" if out["running"] else (last.split(" ", 1)[-1] if last else "never")
        timers = subprocess.run(["systemctl", "--user", "list-timers", "hermes-account-balance.timer", "--all",
                                 "--no-legend", "-o", "json"], capture_output=True, text=True, timeout=10).stdout
        row = (json.loads(timers or "[]") or [{}])[0]
        out["next_ts"] = (row.get("next") or 0) / 1e6 or None
        out["last_ts"] = (row.get("last") or 0) / 1e6 or None
        out["next"] = _hhmm(out["next_ts"]) if out["next_ts"] else ""
    except Exception as x:
        out["error"] = str(x)
    return out


def _doctor_checks(provider: str) -> list:
    """[(level, text)] with level ok / warn / fail. Probes the usage endpoint once."""
    import yaml
    root = _root()
    checks = []                                    # (level, text) level: ok / warn / fail

    def add(level, text):
        checks.append((level, text))

    profiles = [("default", root)]
    pdir = root / "profiles"
    if pdir.is_dir():
        profiles += [(d.name, d) for d in sorted(pdir.iterdir()) if (d / "config.yaml").exists()]

    # strategy per profile
    bad = []
    for name, home in profiles:
        try:
            cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
        except Exception:
            cfg = {}
        strat = (cfg.get("credential_pool_strategies") or {}).get(provider) or "fill_first (default)"
        if not str(strat).startswith("fill_first"):
            bad.append(f"{name}={strat}")
    add("ok" if not bad else "fail",
        f"strategy fill_first in {len(profiles)} profile{'' if len(profiles) == 1 else 's'}" if not bad else
        f"strategy is not fill_first: {', '.join(bad)} (balance order is ignored there). "
        f"Fix: hermes -p <profile> config set credential_pool_strategies.{provider} fill_first")

    # profile-local pools shadowing the shared pool
    local = []
    for name, home in profiles[1:]:
        d = _load_json(home / "auth.json", {})
        if (d.get("credential_pool") or {}).get(provider):
            local.append(name)
    add("ok" if not local else "fail",
        "every profile uses the shared account pool" if not local else
        f"profiles with their OWN {provider} pool (they skip the shared accounts): {', '.join(local)}")

    # tracker plugin per profile
    missing = []
    for name, home in profiles:
        try:
            cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
        except Exception:
            cfg = {}
        enabled = ((cfg.get("plugins") or {}).get("enabled")) or []
        if "account-pool-tracker" not in enabled or not (home / "plugins" / "account-pool-tracker").exists():
            missing.append(name)
    add("ok" if not missing else "warn",
        "session tracker active in every profile" if not missing else
        f"session tracker missing in: {', '.join(missing)} (`who` will not show them)")

    # Accounts page: Hermes Desktop mounts its backend only for profiles that list account-pool
    if (root / "desktop-plugins" / "account-pool").is_dir():
        missing = []
        for name, home in profiles:
            try:
                cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
            except Exception:
                cfg = {}
            plugins = cfg.get("plugins") or {}
            if "account-pool" not in (plugins.get("enabled") or []) or "account-pool" in (plugins.get("disabled") or []):
                missing.append(name)
        add("ok" if not missing else "warn",
            "Accounts page backend enabled in every profile" if not missing else
            f"Accounts page backend not enabled in: {', '.join(missing)} (Hermes Desktop shows "
            "'backend did not answer' while it runs one of them). Fix: run install.sh again")

    # file permissions
    for path in (root / "auth.json", root / "account-pool-parked.json"):
        if path.exists():
            mode = path.stat().st_mode & 0o777
            add("ok" if mode == 0o600 else "fail",
                f"{path.name} permissions {oct(mode)[2:]}" + ("" if mode == 0o600 else f". Fix: chmod 600 {path}"))

    # timer
    try:
        timer = _timer_info()
        if "error" in timer:
            raise RuntimeError(timer["error"])
        active = timer["active"]
        if not active:
            add("fail", "balance timer is NOT active. Fix: systemctl --user enable --now hermes-account-balance.timer")
        elif timer["result"] != "success" and not timer["running"]:
            add("fail", f"balance timer active but the last run failed ({timer['result']}). "
                        f"See: journalctl --user -u hermes-account-balance.service -n 20")
        else:
            add("ok", f"balance timer active, last run {timer['last']}")
        execs = subprocess.run(["systemctl", "--user", "show", "hermes-account-balance.service", "-p", "ExecStart"],
                               capture_output=True, text=True, timeout=10).stdout
        if active and not re.search(rf"account\s+{re.escape(provider)}\s+balance", execs):
            add("warn", f"the balance timer does not run {provider} (timed unparks, cooldown recovery and alerts "
                        f"for {provider} wait for a manual balance). Fix: ./install.sh --provider {provider} "
                        f"(repeat --provider for each one), or add an ExecStart line: "
                        f"{_hermes_bin()} account {provider} balance")
    except Exception as x:
        add("warn", f"could not query systemd: {x}")

    # history freshness
    hist = _read_history(provider, time.time() - 3600) if _has_usage(provider) else None
    if hist is None:
        pass
    elif hist:
        age = (time.time() - hist[-1]["ts"]) / 60
        add("ok" if age < 15 else "warn", f"usage history last written {age:.0f} min ago")
    else:
        add("warn", "no usage history in the last hour (report needs the timer running)")

    # pool health
    pool = _pool(provider)
    entries = pool.entries()
    dead = [e.label for e in entries if getattr(e, "last_status", None) == "dead"]
    cooling = [e.label for e in entries if _is_cooling(e)]
    parked = [p.get("label") for p in _read_parked() if p["_provider"] == provider]
    add("ok" if entries and not dead else "fail",
        f"{len(entries)} account{'' if len(entries) == 1 else 's'} in rotation, {len(parked)} parked" + (f"; DEAD: {', '.join(dead)}" if dead else ""))
    if cooling:
        add("warn", f"cooling down (auto-retried by balance): {', '.join(cooling)}")

    # usage endpoint
    if not _has_usage(provider):
        add("ok", f"no usage adapter for {provider}: usage/balance ordering/report are off; "
                  f"list, check, park, unpark, who, alerts and relogin (OAuth) work")
    else:
        probe = next((e for e in entries if getattr(e, "last_status", None) != "dead" and not _token_expired(e)), None)
        if probe is None:
            add("warn", "usage endpoint not probed (no account with a fresh token)")
        else:
            ok = probe is not None and _usage(provider, probe)
        if probe is not None:
            add("ok" if ok else "fail",
                "usage endpoint reachable" if ok else
                "usage endpoint unreachable or changed: balance cannot order accounts")

    # notifications
    cfg = _config()
    chans = []
    if cfg["notify"].get("desktop"):
        chans.append("desktop" if shutil.which("notify-send") else "desktop (notify-send missing)")
    tgt = _telegram_target(cfg)
    if tgt:
        chans.append(f"telegram via {cfg['notify'].get('telegram_via') or 'default'}")
    add("ok" if chans else "warn", f"alert channels: {', '.join(chans) or 'none'} "
        f"(delivery is tested with: hermes account {provider} notify test)")
    return checks


def _cmd_doctor(args) -> int:
    provider = _norm(args.provider)
    if not _entries(provider) and not any(p["_provider"] == provider for p in _read_parked()):
        ad = providers.get(provider)
        feats = "usage, balance, report and email checks" if ad.has_usage else "the basic commands (no usage adapter)"
        _p(f"[{provider}] doctor")
        _p(f"  --    no {provider} accounts yet: not in use, nothing to check.")
        _p(f"        When you want it: hermes account {provider} add <email>  ({feats} are ready)")
        _p(f"        Using {provider} in a profile is a Hermes setting, not part of this plugin.")
        return 0
    checks = _doctor_checks(provider)
    icon = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    _p(f"[{provider}] doctor")
    for level, text in checks:
        _p(f"  {icon[level]}  {text}")
    fails = sum(1 for l, _ in checks if l == "fail")
    warns = sum(1 for l, _ in checks if l == "warn")
    _p(f"  {fails} failure(s), {warns} warning(s).")
    return 1 if fails else 0


def _signin(cmd, provider: str, before: set):
    """Run a `hermes auth add` child. Returns its exit code, or None when the user pressed Ctrl+C.

    On Ctrl+C the child gets the same signal and stops; anything it may still have saved
    is removed, so a cancelled sign-in never leaves a half-added account behind.
    """
    proc = subprocess.Popen(cmd, env=_hermes_env())
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=10)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()
        pool = _pool(provider)
        for e in [e for e in pool.entries() if e.id not in before]:
            idx, _, _ = pool.resolve_target(e.id)
            if idx is not None:
                pool.remove_index(idx)
        _p("\nCancelled (Ctrl+C). Nothing was added.")
        return None


def _relogin_target(provider: str, target: str):
    """(label, id, priority) of the OAuth account to sign in again; SystemExit with the reason otherwise."""
    pool = _pool(provider)
    index, matched, error = pool.resolve_target(target)
    if matched is None or index is None:
        parked = [p for p in _read_parked() if p["_provider"] == provider
                  and str(target).lower() in (p.get("id", "").lower(), (p.get("label") or "").lower())]
        if parked:
            raise SystemExit(f"{parked[0].get('label')} is parked. Unpark it first: "
                             f"hermes account {provider} unpark {parked[0].get('label')}")
        raise SystemExit(f"{error} See: hermes account {provider} list")
    label = matched.label
    if not _oauth(matched):
        raise SystemExit(f"{label} uses an API key, not a sign-in. Replace the key with:\n"
                         f"  hermes account {provider} remove {label}\n"
                         f"  hermes account {provider} add {label} --key")
    return label, matched.id, matched.priority


def _accept_relogin(provider: str, label: str, old_id: str, old_priority: int, fresh) -> int:
    """Swap a fresh sign-in in for the old entry, keeping label and position; discard it if it is someone else."""
    pool = _pool(provider)
    ident = _identity(provider, fresh)
    if ident and "@" in ident and ident.lower() != label.lower():
        idx, _, _ = pool.resolve_target(fresh.id)
        if idx is not None:
            pool.remove_index(idx)
        _p(f"Signed in as {ident}, not {label}. The new sign-in was discarded; the old entry is unchanged.")
        _p(f"Retry in a browser signed in as {label} (its own Chrome profile or a private window).")
        return 1
    idx, _, _ = pool.resolve_target(old_id)
    if idx is not None:
        pool.remove_index(idx)
    pool.move_entry(fresh.id, old_priority)
    _p(f"Re-login OK: {label} (new id={fresh.id})" + (f", verified as {ident}" if ident and "@" in ident else ""))
    return 0


def _cmd_relogin(args) -> int:
    provider = _norm(args.provider)
    label, old_id, old_priority = _relogin_target(provider, args.target)
    verify = providers.get(provider).has_identity
    _p(f"Re-login {label} ({provider}, id={old_id})")
    _p("  1. Open the sign-in link in a browser that is signed in as THIS account:")
    _p("     its own Chrome profile, or a private / incognito window.")
    _p(f"  2. Make sure the page says: Logged in as {label}  (otherwise: Switch account)")
    _p("     \"Sign in again to continue\" is normal when that browser login is old.")
    _p("  3. Authorize, then paste the code back here.")
    _p("The old entry is replaced only if the new sign-in really is that account."
          if verify else
          f"NOTE: {provider} has no identity adapter, so the account cannot be verified. Sign in carefully.")
    if not args.yes:
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            _p("Cancelled. Nothing changed.")
            return 1
    before = {e.id for e in _pool(provider).entries()}
    rc = _signin([_hermes_bin(), "auth", "add", provider, "--type", "oauth", "--label", label], provider, before)
    if rc is None:
        _p("The old entry is unchanged.")
        return 130
    new = [e for e in _pool(provider).entries() if e.id not in before]
    if rc != 0 or not new:
        _p("Sign-in did not complete. The old entry is unchanged.")
        return 1
    return _accept_relogin(provider, label, old_id, old_priority, new[0])


TOKEN_KEYS = ("input", "output", "cache_read", "cache_write", "requests")
TOKEN_BUCKET = 900         # seconds per bucket, as written by the session tracker


def _token_buckets(provider: str) -> tuple:
    """({label: {bucket_start: [in, out, cache_read, cache_write, requests]}}, counting_since or None).

    Written by the session tracker (account-pool-tracker >= 1.1.0) after every API call through the pool."""
    data = _load_json(_root() / "account-pool-tokens.json", {}) or {}
    raw = ((data.get("buckets") or {}).get(provider)) or {}
    out = {}
    for label, slots in raw.items():
        rows = {}
        for k, v in (slots or {}).items():
            try:
                rows[float(k)] = [int(x) for x in v[:5]]
            except (TypeError, ValueError):
                continue
        out[label] = rows
    return out, data.get("since")


def _token_sum(rows: dict, since: float, until: float = None) -> dict:
    """Totals of the buckets that start at or after `since` (and before `until`)."""
    acc = [0, 0, 0, 0, 0]
    for start, v in rows.items():
        if start >= since and (until is None or start < until):
            for i in range(5):
                acc[i] += v[i] if i < len(v) else 0
    out = dict(zip(TOKEN_KEYS, acc))
    out["total"] = sum(acc[:4])
    return out


def _fmt_tokens(n) -> str:
    n = float(n or 0)
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


def _report_data(provider: str, hours: float) -> dict:
    """Load per account from the usage history. Keys: snapshots, span_h, start, accounts (label, used,
    share, peak, hot_min; heaviest first), total, busiest [(hour, used)], full_min, advice."""
    since_ts = time.time() - hours * 3600
    hist = _read_history(provider, since_ts)
    buckets, counting = _token_buckets(provider)
    tokens = {label: _token_sum(rows, since_ts) for label, rows in buckets.items()}
    tokens = {label: t for label, t in tokens.items() if t["requests"]}
    tokens_total = _token_sum({0: [sum(t[k] for t in tokens.values()) for k in TOKEN_KEYS]}, 0)
    out = {"hours": hours, "snapshots": len(hist), "window": _window(provider), "accounts": [], "total": 0.0,
           "busiest": [], "full_min": 0.0, "span_h": 0.0, "start": None, "advice": "",
           "tokens_total": tokens_total, "tokens_since": counting}
    if len(hist) < 2:
        return out
    series = defaultdict(list)
    for rec in hist:
        for label, util in rec["usage"].items():
            series[label].append((rec["ts"], util))
    burn = defaultdict(float)
    hot = defaultdict(float)                      # minutes at/above 90%
    peak = defaultdict(float)
    hourly = defaultdict(float)
    for label, pts in series.items():
        for (t1, u1), (t2, u2) in zip(pts, pts[1:]):
            gap = t2 - t1
            if gap > 1200:                         # timer was off: skip the hole
                continue
            if u2 > u1:
                burn[label] += u2 - u1
                hourly[time.localtime(t2).tm_hour] += u2 - u1
            if u1 >= 90:
                hot[label] += gap / 60
        peak[label] = max(u for _, u in pts)
    full_min = 0.0
    for r1, r2 in zip(hist, hist[1:]):
        if r2["ts"] - r1["ts"] <= 1200 and r1["usage"] and all(u >= 90 for u in r1["usage"].values()):
            full_min += (r2["ts"] - r1["ts"]) / 60
    span = (hist[-1]["ts"] - hist[0]["ts"]) / 3600
    total = sum(burn.values())
    if span < 2 or total < 30:
        advice = "Too little data for recommendations yet: needs at least 2 hours and some real load."
    elif full_min > 0:
        advice = "The pool ran out of headroom. Consider adding an account."
    elif max(burn.values()) / total > 0.5 and len(series) > 2:
        advice = "One account carried most of the load; check `who` for long sessions pinned to it."
    else:
        advice = ""
    out.update(
        span_h=span, start=hist[0]["ts"], total=total, full_min=full_min, advice=advice,
        busiest=sorted(hourly.items(), key=lambda kv: -kv[1])[:3],
        accounts=[{"label": label, "used": burn[label], "share": burn[label] / total * 100 if total else 0,
                   "peak": peak[label], "hot_min": hot[label], "tokens": tokens.get(label)}
                  for label in sorted(series, key=lambda l: -burn[l])]
        + [{"label": label, "used": 0.0, "share": 0.0, "peak": 0.0, "hot_min": 0.0, "tokens": tokens[label]}
           for label in sorted(set(tokens) - set(series), key=lambda l: -tokens[l]["total"])])
    return out


def _cmd_report(args) -> int:
    provider = _norm(args.provider)
    hours = float(args.hours or 24)
    if not _has_usage(provider):
        _p(f"[{provider}] report needs usage history. {_no_usage_text(provider)}")
        return 0
    data = _report_data(provider, hours)
    n = data["snapshots"]
    if n < 2 and _no_accounts(provider):
        return 0
    if n < 2:
        _p(f"[{provider}] Not enough history yet ({n} snapshot{'' if n == 1 else 's'}). "
              f"The balance timer records one every 5 minutes.")
        return 0
    _p(f"[{provider}] usage report: last {hours:.0f}h ({n} snapshots, {data['span_h']:.1f}h covered, "
          f"from {time.strftime('%m-%d %H:%M', time.localtime(data['start']))})")
    w = data["window"]
    _p(f"  'used' adds up {w}-window percent: 100 = one full {w} window.")
    _p(f"  {'account':34s} {'used':>6s} {'share':>6s} {'peak':>5s}  {'time >= 90%':>11s}  {'tokens':>8s}")
    for a in data["accounts"]:
        tok = _fmt_tokens(a["tokens"]["total"]) if a.get("tokens") else "-"
        _p(f"  {a['label']:34s} {a['used']:6.0f} {a['share']:5.0f}% {a['peak']:4.0f}%  {a['hot_min']:8.0f} min  {tok:>7s}")
    tt = data["tokens_total"]
    _p(f"  {'total':34s} {data['total']:6.0f}{'':29s}{_fmt_tokens(tt['total']) if tt['requests'] else '-':>7s}")
    if tt["requests"]:
        since = data.get("tokens_since")
        _p(f"  Tokens through Hermes: {_fmt_tokens(tt['input'])} input, {_fmt_tokens(tt['output'])} output, "
           f"{_fmt_tokens(tt['cache_read'])} cache read, {_fmt_tokens(tt['cache_write'])} cache write")
        _p(f"  {tt['requests']} requests"
           + (f", counted since {time.strftime('%m-%d %H:%M', time.localtime(since))}." if since and since > data['start'] else "."))
    else:
        _p("  Tokens: none counted yet. The session tracker counts them from version 1.1.0 on.")
    if data["busiest"]:
        _p("  Busiest hours: " + ", ".join(f"{h:02d}:00-{(h + 1) % 24:02d}:00 ({v:.0f})" for h, v in data["busiest"]))
    _p(f"  Time with EVERY account >= 90%: {data['full_min']:.0f} min")
    if data["advice"]:
        _p(("  (" + data["advice"] + ")") if data["advice"].startswith("Too little") else "  -> " + data["advice"])
    return 0


def _who_data(provider: str, minutes: float) -> dict:
    """Sessions seen in the last `minutes`, grouped by account (pool order first, then any other label)."""
    data = _load_json(_root() / "account-pool-sessions.json", {})
    cutoff = time.time() - minutes * 60
    rows = [r for r in (data.get("sessions") or {}).values()
            if r.get("provider") == provider and r.get("last_seen", 0) >= cutoff]
    by_acc = defaultdict(list)
    for r in rows:
        by_acc[r.get("account", "?")].append(r)
    labels = [e.label for e in _entries(provider)]
    accounts = [{"label": label, "sessions": sorted(by_acc.get(label, []), key=lambda r: -r.get("last_seen", 0))}
                for label in labels + sorted(set(by_acc) - set(labels))]
    return {"recorded": bool(data), "minutes": minutes, "count": len(rows), "accounts": accounts}


def _cmd_who(args) -> int:
    provider = _norm(args.provider)
    minutes = float(args.minutes or 30)
    data = _who_data(provider, minutes)
    if not data["recorded"]:
        _p("No sessions recorded yet. The tracker records a session after its next API call.")
    _p(f"[{provider}] sessions active in the last {minutes:.0f} min: {data['count']}")
    for acc in data["accounts"]:
        sess = acc["sessions"]
        _p(f"  {acc['label']:34s}" + ("" if sess else " (idle)"))
        for r in sess:
            ago = (time.time() - r["last_seen"]) / 60
            moved = f"  (moved from {r['previous_account']})" if r.get("previous_account") else ""
            _p(f"      {r.get('profile', '?'):20s} {r.get('platform') or '-':9s} "
                  f"{(r.get('session_id') or '?')[:22]:22s} {r.get('model') or '':18s} {ago:3.0f}m ago{moved}")
    return 0


def _cmd_notify(args) -> int:
    sub = (args.target or "status").lower()
    cfg = _config()
    if sub == "status":
        tgt = _telegram_target(cfg)
        _p("Alert channels:")
        _p(f"  desktop  : {'on' if cfg['notify'].get('desktop') else 'off'}"
              + ("" if shutil.which("notify-send") else " (notify-send not installed)"))
        via = cfg["notify"].get("telegram_via") or "default"
        _p(f"  telegram : {'on (your private chat)' if tgt else 'off'}"
              + (f", sent with the bot of profile '{via}'" if tgt else ""))
        _p(f"  alert when every account is above {cfg.get('alert_all_above', 80)}%, "
              f"and when an account needs sign-in (DEAD).")
        _p(f"Settings: {_config_path()}  (created with defaults on first change)")
        _p("Change: hermes account <provider> notify desktop-on|desktop-off|telegram-on|telegram-off")
        _p("        hermes account <provider> notify telegram-via=<profile>   (which bot sends)")
        return 0
    if sub == "test":
        sent = _notify("Hermes account-pool: test", "Alerts from `hermes account` reach this channel.")
        _p(f"Test alert delivered to: {', '.join(sent) or 'no channel'}")
        return 0 if sent else 1
    if sub.startswith("telegram-via="):
        via = sub.split("=", 1)[1].strip() or "default"
        if via != "default" and not (_root() / "profiles" / via).is_dir():
            _p(f"No profile named '{via}'.")
            return 2
        user = _load_json(_config_path(), {})
        user.setdefault("notify", {})["telegram_via"] = via
        _atomic_json(_config_path(), user)
        _p(f"Telegram alerts are now sent with the bot of profile '{via}'.")
        return 0
    toggles = {"desktop-on": ("desktop", True), "desktop-off": ("desktop", False),
               "telegram-on": ("telegram", "auto"), "telegram-off": ("telegram", None)}
    if sub not in toggles:
        _p("notify accepts: status, test, desktop-on, desktop-off, telegram-on, telegram-off, telegram-via=<profile>")
        return 2
    user = _load_json(_config_path(), {})
    key, val = toggles[sub]
    user.setdefault("notify", {})[key] = val
    _atomic_json(_config_path(), user)
    _p(f"{key} alerts {'on' if val else 'off'}.")
    return 0


def _oauth_provider(provider: str) -> bool:
    try:
        from hermes_cli.auth_commands import _OAUTH_ADD_SPECS
        return provider in _OAUTH_ADD_SPECS
    except Exception:
        return provider in ("anthropic", "openai-codex")


def _find_parked(provider: str, target: str):
    t = str(target).lower()
    return next((p for p in _read_parked() if p["_provider"] == provider
                 and t in (str(p.get("id", "")).lower(), str(p.get("label") or "").lower())), None)


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _in_root() -> bool:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).resolve() == _root().resolve()
    except Exception:
        return False


def _add_key_in_process(provider: str, label: str):
    """Ask for the key here (masked, clean Ctrl+C) and hand it to Hermes' own `auth add`.

    The key never goes on a command line (other processes could read it there).
    Returns 0 on success, 1 on failure, None when cancelled.
    """
    from types import SimpleNamespace
    try:
        from hermes_cli.secret_prompt import masked_secret_prompt
        key = masked_secret_prompt("Paste the API key (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        _p("Cancelled. Nothing was added.")
        return None
    if not key:
        _p("No API key given.")
        return 1
    try:
        from hermes_cli.auth_commands import auth_add_command
        auth_add_command(SimpleNamespace(provider=provider, auth_type="api-key", api_key=key, label=label))
        return 0
    except SystemExit as x:
        if x.code not in (None, 0):
            _p(x.code if isinstance(x.code, str) else f"hermes auth add failed ({x.code}).")
            return 1
        return 0
    except KeyboardInterrupt:
        _p("\nCancelled. Nothing was added.")
        return None


def _add_check(provider: str, label: str) -> None:
    """SystemExit when the label is already in rotation or parked."""
    if any((e.label or "").lower() == label.lower() for e in _pool(provider).entries()):
        raise SystemExit(f"{label} is already in rotation. To sign it in again: "
                         f"hermes account {provider} relogin {label}")
    if _find_parked(provider, label):
        raise SystemExit(f"{label} is parked. Return it with: hermes account {provider} unpark {label}")


def _accept_added(provider: str, label: str, fresh, verify: bool) -> int:
    """Keep a fresh sign-in only if it is the account it claims to be and not a duplicate, then balance."""
    pool = _pool(provider)

    def discard(msg: str) -> int:
        idx, _, _ = pool.resolve_target(fresh.id)
        if idx is not None:
            pool.remove_index(idx)
        _p(msg)
        return 1

    if verify:
        ident = _identity(provider, fresh)
        if ident and "@" in ident:
            if ident.lower() != label.lower():
                same = next((e for e in pool.entries() if e.id != fresh.id
                             and (e.label or "").lower() == ident.lower()), None)
                hint = f" ({ident} is already in the pool as id={same.id})" if same else ""
                return discard(f"Signed in as {ident}, not {label}{hint}. The sign-in was discarded.\n"
                               f"Retry in a browser signed in as {label} (its own Chrome profile or a private window).")
            for e in pool.entries():
                if e.id == fresh.id:
                    continue
                if (e.label or "").lower() == ident.lower() or (
                        _oauth(e) and not _token_expired(e) and (_identity(provider, e) or "").lower() == ident.lower()):
                    return discard(f"{ident} is already in the pool as '{e.label}' (id={e.id}). "
                                   f"The duplicate sign-in was discarded.")
            _p(f"Verified: {ident}")
        else:
            _p(f"Could not verify the email ({ident or 'no answer'}). Kept as '{label}'; "
                  f"check it later with: hermes account {provider} check")

    _p(f"Added {label} (id={fresh.id}) to {provider}.")
    if _has_usage(provider):
        from types import SimpleNamespace
        with _capture() as out:
            try:
                _cmd_balance(SimpleNamespace(provider=provider, threshold=90.0, dry_run=False))
            except SystemExit:
                pass
        order = next((l.strip()[2:] for l in out.getvalue().splitlines() if l.strip().startswith("- order:")), None)
        _p("Balanced now: " + order[len("order: "):] if order else "Balanced now (order unchanged).")
    return 0


def _store_signin(provider: str, label: str, creds: dict):
    """Save a finished sign-in as a new pool entry: the same steps `hermes auth add <provider> --type oauth`
    takes after its login (un-suppress the provider, write the entry, mark the provider active if none is)."""
    import uuid
    from agent.credential_pool import PooledCredential
    from hermes_cli import auth as auth_mod
    from hermes_cli.auth_commands import _OAUTH_ADD_SPECS, _unsuppress_provider_sources
    spec = _OAUTH_ADD_SPECS[provider]
    _unsuppress_provider_sources(provider)
    pool = _pool(provider)
    existing = pool.entries()
    entry = PooledCredential(
        provider=provider, id=uuid.uuid4().hex[:6], label=label, auth_type=spec.auth_type, priority=0,
        source=spec.source(creds) if callable(spec.source) else spec.source,
        access_token=spec.token(creds), **spec.fields(creds, provider))
    entry = pool.add_entry(entry)
    if spec.activate_first and not existing:
        auth_mod.mark_provider_active_if_unset(provider)
    return entry


def _cmd_add(args) -> int:
    provider = _norm(args.provider)
    label = str(args.target).strip()
    _add_check(provider, label)
    entries = _pool(provider).entries()

    use_key = bool(args.key) or not _oauth_provider(provider)
    verify = providers.get(provider).has_identity and not use_key
    _p(f"Add {label} to {provider}")
    if use_key:
        _p("  You will be asked for the API key (input is hidden).")
    else:
        _p("  1. Open the sign-in link in a browser that is signed in as THIS account:")
        _p("     its own Chrome profile, or a private / incognito window.")
        _p(f"  2. Make sure the page says: Logged in as {label}  (otherwise: Switch account)")
        _p("     \"Sign in again to continue\" is normal when that browser login is old.")
        _p("  3. Authorize, then paste the code back here.")
        _p("  The account is kept only if the sign-in really is that account and not a duplicate."
              if verify else
              f"  NOTE: {provider} has no identity adapter, so the account cannot be verified.")
    if not _confirm("Continue?", args.yes):
        _p("Cancelled. Nothing changed.")
        return 1

    before = {e.id for e in entries}
    if use_key and _in_root():
        rc = _add_key_in_process(provider, label)
    else:
        cmd = [_hermes_bin(), "auth", "add", provider, "--type", "api-key" if use_key else "oauth", "--label", label]
        rc = _signin(cmd, provider, before)
    if rc is None:
        return 130
    new = [e for e in _pool(provider).entries() if e.id not in before]
    if rc != 0 or not new:
        _p("Sign-in did not complete. Nothing was added." if not use_key else "Nothing was added.")
        return 1
    return _accept_added(provider, label, new[0], verify)


def _cmd_remove(args) -> int:
    provider = _norm(args.provider)
    pool = _pool(provider)
    index, matched, error = pool.resolve_target(args.target)

    if matched is None or index is None:
        item = _find_parked(provider, args.target)
        if not item:
            raise SystemExit(f"{error} See: hermes account {provider} list")
        label = item.get("label", "?")
        _p(f"Remove PARKED account {label} (id={item.get('id')}) from {provider}.")
        _p("Its saved login is deleted; to use it again you must sign in again (add).")
        if not _confirm("Delete it?", args.yes):
            _p("Cancelled. Nothing changed.")
            return 1
        items = [p for p in _read_parked() if not (p["_provider"] == provider and p.get("id") == item.get("id"))]
        _write_parked(items)
        _p(f"Removed {label}.")
        return 0

    label = matched.label
    others = [e for e in pool.entries() if e.id != matched.id and getattr(e, "last_status", None) != "dead"]
    if not others:
        raise SystemExit(f"Refused: {label} is the last working {provider} account. "
                         f"Add another one first: hermes account {provider} add <email>")
    _p(f"Remove {label} (id={matched.id}) from {provider}.")
    _p("Its login is deleted; to use it again you must sign in again (add).")
    _p(f"To take it out of rotation for a while instead: hermes account {provider} park {label}")
    if not _confirm("Delete it?", args.yes):
        _p("Cancelled. Nothing changed.")
        return 1
    if _in_root():
        # In-process (no second Hermes start-up, no PATH lookup): what `hermes auth remove` runs.
        import contextlib
        from types import SimpleNamespace
        from hermes_cli.auth_commands import auth_remove_command
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                auth_remove_command(SimpleNamespace(provider=provider, target=matched.id))
        except SystemExit as x:
            _p(x.code if isinstance(x.code, str) else "hermes auth remove failed.")
            return 1
        except Exception as x:  # noqa: BLE001 - report it like the subprocess path would
            _p(f"hermes auth remove failed: {x}")
            return 1
        _p(f"Removed {label}.")
        return 0
    r = subprocess.run([_hermes_bin(), "auth", "remove", provider, matched.id],
                       capture_output=True, text=True, env=_hermes_env())
    if r.returncode != 0:
        _p((r.stderr or r.stdout).strip() or "hermes auth remove failed.")
        return 1
    _p(f"Removed {label}.")
    return 0


# ── registration ─────────────────────────────────────────────────────────────

ACTIONS = [
    ("list", "", "Accounts in rotation and parked accounts"),
    ("check", "", "Health: dead, rate-limited, wrong label, duplicate, real email"),
    ("usage", "", "Live usage per account, parked included (usage adapter needed)"),
    ("who", "[--minutes N]", "Which session is on which account (default: last 30 min)"),
    ("report", "[--hours N]", "Usage history: load per account, busiest hours (usage adapter needed)"),
    ("add", "<email> [--key] [--yes]", "Sign in a new account, verified, no duplicates (--key: API key)"),
    ("remove", "<target> [--yes]", "Delete an account's login (also works for parked accounts)"),
    ("park", "<target> [--until T]", "Take an account out of rotation; T = 17:00, +2h, 90m"),
    ("unpark", "<target>", "Return a parked account to rotation"),
    ("relogin", "<target> [--yes]", "Sign an account in again, verified, same label and position"),
    ("balance", "[--dry-run] [--threshold N]", "Order by usage, bench >= N% (90), auto-recover, alerts"),
    ("doctor", "", "Check the whole setup: strategy, timer, files, pools, alerts"),
    ("notify", "[status|test|...]", "Alert channels: desktop and Telegram"),
    ("help", "", "Show this help"),
]

HELP = "\n".join([
    "Manage accounts in the Hermes credential pool.",
    "",
    "Usage:",
    "  hermes account <provider> <action> [target] [options]",
    "",
    "Actions:",
    *[f"  {a:8s} {arg:28s} {d}" for a, arg, d in ACTIONS],
    "",
    "Targets: account label (email), list number, or id. unpark accepts label or id.",
    "",
    "Examples:",
    "  hermes account anthropic add carol@example.com",
    "  hermes account anthropic usage",
    "  hermes account anthropic who",
    "  hermes account anthropic park alice@example.com --until 17:00",
    "  hermes account anthropic relogin bob@example.com",
    "  hermes account anthropic report --hours 72",
    "  hermes account anthropic doctor",
    "  hermes account anthropic notify test",
    "",
    "Every provider in the credential pool: list, check, add, remove, park, unpark, relogin, who, doctor, alerts,",
    "  timed parks and refresh recovery.",
    f"Usage adapter (usage, report, balance ordering, real email): {', '.join(providers.with_usage())}.",
])


def _print_help(_args=None) -> int:
    _p(HELP)
    return 0


HANDLERS = {"add": _cmd_add, "remove": _cmd_remove, "list": _cmd_list, "check": _cmd_check, "usage": _cmd_usage, "who": _cmd_who,
            "report": _cmd_report, "park": _cmd_park, "unpark": _cmd_unpark, "relogin": _cmd_relogin,
            "balance": _cmd_balance, "doctor": _cmd_doctor, "notify": _cmd_notify}
NEEDS_TARGET = {"park", "unpark", "relogin", "add", "remove"}
OPTIONAL_TARGET = {"notify"}
OPTIONS = {"threshold": ("--threshold", {"balance"}), "dry_run": ("--dry-run", {"balance"}),
           "until": ("--until", {"park"}), "hours": ("--hours", {"report"}),
           "minutes": ("--minutes", {"who"}), "yes": ("--yes", {"relogin", "add", "remove"}),
           "key": ("--key", {"add"})}


def _dispatch(args) -> int:
    provider = (args.provider or "").strip()
    action = (args.action or "").strip().lower()
    if not provider or provider.lower() in ("help", "-h"):
        return _print_help()
    if not action or action == "help":
        if not action:
            _p(f"Missing action for provider '{provider}'.\n")
        _print_help()
        return 0 if action == "help" else 2
    if action not in HANDLERS:
        import difflib
        close = difflib.get_close_matches(action, list(HANDLERS), n=1, cutoff=0.5)
        hint = f" Did you mean: {close[0]}?" if close else ""
        _p(f"'{action}' is not an action.{hint}\nActions: {', '.join(HANDLERS)}, help")
        return 2
    if action in NEEDS_TARGET and not args.target:
        _p(f"Missing target. Usage: hermes account {provider} {action} <email|id>")
        return 2
    if action not in NEEDS_TARGET | OPTIONAL_TARGET and args.target:
        _p(f"'{action}' takes no target (got '{args.target}').")
        return 2
    for attr, (flag, allowed) in OPTIONS.items():
        val = getattr(args, attr, None)
        if val not in (None, False) and action not in allowed:
            _p(f"{flag} only applies to: {', '.join(sorted(allowed))}")
            return 2
    if args.threshold is None:
        args.threshold = 90.0
    elif not 1 <= args.threshold <= 100:
        _p("--threshold must be between 1 and 100 (percent).")
        return 2
    if args.hours is not None and args.hours <= 0:
        _p("--hours must be greater than 0.")
        return 2
    if args.minutes is not None and args.minutes <= 0:
        _p("--minutes must be greater than 0.")
        return 2
    if not _known_provider(_norm(provider)):
        _p(f"Unknown provider '{args.provider}'. Providers in your pool: {', '.join(_pool_providers()) or 'none'}. "
              f"All providers: hermes auth list")
        return 2
    try:
        return HANDLERS[action](args)
    except KeyboardInterrupt:
        _p("\nCancelled (Ctrl+C).")
        return 130


def _setup(parser) -> None:
    import argparse
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.usage = "hermes account <provider> <action> [target] [options]"
    parser.description = HELP.replace("%", "%%")
    parser.add_argument("provider", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("action", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("target", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--threshold", type=float, default=None, help="balance: bench at/above this usage %%")
    parser.add_argument("--dry-run", action="store_true", help="balance: show changes without applying them")
    parser.add_argument("--until", default=None, help="park: return automatically (17:00, +2h, 90m)")
    parser.add_argument("--hours", type=float, default=None, help="report: period in hours (default 24)")
    parser.add_argument("--minutes", type=float, default=None, help="who: activity window (default 30)")
    parser.add_argument("--yes", action="store_true", help="add/remove/relogin: skip the confirmation prompt")
    parser.add_argument("--key", action="store_true", help="add: add an API key instead of a sign-in")
    parser.set_defaults(func=_dispatch)


def _in_profile() -> bool:
    """True when this process runs a named profile (HERMES_HOME=<root>/profiles/<name>)."""
    return _home().parent.name == "profiles"


def register(ctx) -> None:
    # The command lives in the default profile only. install.sh also lists account-pool in every
    # profile's plugins.enabled, so Hermes Desktop mounts the Accounts page backend whichever
    # profile it runs; if a profile ever loads this plugin, it registers nothing there.
    if _in_profile():
        return
    ctx.register_cli_command(
        name="account",
        help="Manage credential-pool accounts: hermes account <provider> <action>",
        setup_fn=_setup,
        handler_fn=None,
        description=HELP,
    )
