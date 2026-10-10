"""`hermes account` — manage accounts in the Hermes credential pool.

Every command follows one pattern:

    hermes account <provider> <action> [target] [options]

    hermes account <provider> list             accounts in rotation + parked accounts
    hermes account <provider> check            health: dead, rate-limited, wrong label, duplicate
    hermes account <provider> usage            live 5-hour usage per account (anthropic)
    hermes account <provider> park <target>    take an account out of rotation, keep its login
    hermes account <provider> unpark <target>  put a parked account back into rotation
    hermes account <provider> balance          order accounts by live usage, bench nearly-full ones
    hermes account <provider> who|report|relogin|doctor|notify   (see `hermes account help`)
    hermes account help | hermes account <provider> help

`balance` is meant to run on a timer with `credential_pool_strategies.<provider>:
fill_first`: new sessions then always start on the least-used account, and an
account above the threshold is benched until its 5-hour window resets.

Pool changes go through the credential pool API (remove_index, add_entry,
move_entry, mark_exhausted_and_rotate, reset_status), so locking and the
auth.json format stay owned by Hermes. Parked accounts are stored in
$HERMES_HOME/account-pool-parked.json (mode 600).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

MARK = "[account-pool]"


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
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "?"


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


# ── provider probes (anthropic) ──────────────────────────────────────────────

def _anthropic_get(entry, path: str):
    req = urllib.request.Request(f"https://api.anthropic.com{path}", headers={
        "Authorization": f"Bearer {getattr(entry, 'access_token', '') or ''}",
        "anthropic-beta": "oauth-2025-04-20",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _token_expired(entry) -> bool:
    return (getattr(entry, "expires_at_ms", None) or 0) / 1000 < time.time() + 60


def _anthropic_identity(entry) -> str:
    try:
        acc = _anthropic_get(entry, "/api/oauth/profile").get("account") or {}
        return acc.get("email") or acc.get("email_address") or "?"
    except urllib.error.HTTPError as x:
        if x.code == 401 and _token_expired(entry):
            return "(access token expired: normal, refreshed automatically on next use)"
        return f"(HTTP {x.code})"
    except Exception as x:
        return f"(lookup failed: {type(x).__name__})"


def _anthropic_usage(entry):
    """(five_hour_percent, resets_at_epoch) or None when unavailable."""
    try:
        five = _anthropic_get(entry, "/api/oauth/usage").get("five_hour") or {}
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


IDENTITY = {"anthropic": _anthropic_identity}
USAGE = {"anthropic": _anthropic_usage}


def _oauth(entry) -> bool:
    return getattr(entry, "auth_type", "") == "oauth"


def _identity(provider, entry):
    fn = IDENTITY.get(provider)
    return fn(entry) if fn and _oauth(entry) else None


def _usage(provider, entry):
    fn = USAGE.get(provider)
    return fn(entry) if fn and _oauth(entry) else None


def _refresh_if_expired(provider: str, pool, entry):
    """Refresh an expired access token through the pool so usage can be read."""
    if not _oauth(entry) or not _token_expired(entry) or getattr(entry, "last_status", None) == "dead":
        return entry
    try:
        return pool.try_refresh_matching(credential_id=entry.id) or entry
    except Exception:
        return entry


def _require_usage(provider: str) -> None:
    if provider not in USAGE:
        raise SystemExit(f"Live usage is not available for provider '{provider}'. Supported: {', '.join(USAGE)}")


# ── status text ──────────────────────────────────────────────────────────────

def _is_cooling(entry) -> bool:
    """Exhausted without a provider limit code: a failed token refresh (network)."""
    return (getattr(entry, "last_status", None) == "exhausted"
            and MARK not in (getattr(entry, "last_error_message", None) or "")
            and getattr(entry, "last_error_code", None) not in (429, 402)
            and not getattr(entry, "last_error_reason", None))


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
    print(f"[{provider}] in rotation ({len(entries)}):")
    for n, e in enumerate(entries, 1):
        print(f"  #{n}  {e.label:34s} id={e.id}  status={getattr(e, 'last_status', None) or 'ok'}")
    print(f"[{provider}] parked ({len(parked)}):" + ("" if parked else " -"))
    for p in parked:
        until = f"  until {p['_until_h']}" if p.get("_until") else ""
        print(f"  -   {p.get('label', '?'):34s} id={p.get('id')}  since {p.get('_parked_at_h', '?')}{until}")
    return 0


def _cmd_check(args) -> int:
    provider = _norm(args.provider)
    entries = _entries(provider)
    parked = [p for p in _read_parked() if p["_provider"] == provider]
    note = "" if provider in IDENTITY else "   (real-identity lookup not available for this provider)"
    print(f"[{provider}] in rotation: {len(entries)}   parked: {len(parked)}{note}")
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
        print(f"  {'OK' if not probs else '!!'} #{n} id={e.id}  label={e.label}")
        if ident is not None:
            print(f"        account : {ident}")
        for p in probs:
            print(f"        issue   : {p}")
    for p in parked:
        print(f"  -- parked  id={p.get('id')}  label={p.get('label')}  (since {p.get('_parked_at_h', '?')})")
    print(f"  {bad} account(s) need attention." if bad else "  All accounts in rotation are healthy.")
    return 1 if bad else 0


def _refresh_parked(provider: str, item: dict) -> dict:
    """Refresh an expired access token of a PARKED anthropic account.

    Anthropic refresh tokens are single-use, so the rotated pair is written back
    to the parked file under a lock straight after the POST. On invalid_grant the
    record is flagged so `usage` shows it as needing a new sign-in.
    """
    from types import SimpleNamespace
    if provider != "anthropic" or item.get("auth_type") != "oauth" or item.get("_dead"):
        return item
    if not _token_expired(SimpleNamespace(**{"expires_at_ms": item.get("expires_at_ms")})):
        return item
    import fcntl
    lock_path = _parked_path().with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        items = _read_parked()                     # re-read: another run may have refreshed it
        cur = next((p for p in items if p["_provider"] == provider and p.get("id") == item.get("id")), None)
        if cur is None:
            return item
        if not _token_expired(SimpleNamespace(expires_at_ms=cur.get("expires_at_ms"))):
            return cur
        try:
            from agent.anthropic_credentials import refresh_anthropic_oauth_pure
            new = refresh_anthropic_oauth_pure(cur.get("refresh_token") or "",
                                               use_json=str(cur.get("source", "")).endswith("hermes_pkce"))
            cur.update(access_token=new["access_token"], refresh_token=new["refresh_token"],
                       expires_at_ms=new["expires_at_ms"])
            cur.pop("_dead", None)
        except Exception as x:
            text = str(x)
            if "invalid_grant" in text or "400" in text:
                cur["_dead"] = text[:160]
            else:
                return cur                             # network etc.: leave untouched
        _write_parked(items)
        return cur


def _cmd_usage(args) -> int:
    from types import SimpleNamespace
    provider = _norm(args.provider)
    _require_usage(provider)
    pool = _pool(provider)
    rows = []                                          # (label, state, usage)
    for e in sorted(pool.entries(), key=lambda x: x.priority):
        e = _refresh_if_expired(provider, pool, e)
        st = getattr(e, "last_status", None)
        msg = getattr(e, "last_error_message", None) or ""
        state = ("DEAD" if st == "dead" else
                 "BENCHED" if st == "exhausted" and MARK in msg else
                 "LIMITED" if st == "exhausted" else "active")
        rows.append((e.label, state, _usage(provider, e) if st != "dead" else None))
    for item in [p for p in _read_parked() if p["_provider"] == provider]:
        item = _refresh_parked(provider, item)
        if item.get("_dead"):
            rows.append((item.get("label", "?"), "PARKED", "dead"))
            continue
        ent = SimpleNamespace(access_token=item.get("access_token"), auth_type=item.get("auth_type"))
        rows.append((item.get("label", "?"), "PARKED", _usage(provider, ent)))

    order = {"active": 0, "BENCHED": 1, "LIMITED": 1, "PARKED": 2, "DEAD": 3}
    rows.sort(key=lambda r: (order[r[1]], r[2][0] if isinstance(r[2], tuple) else 999))
    print(f"[{provider}] 5-hour usage")
    print(f"  {'account':34s} {'state':8s} {'used':>5s}  {'':22s}  resets")
    last = None
    for label, state, u in rows:
        group = "parked" if state == "PARKED" else "rotation"
        if group != last:
            print(f"  -- {'in rotation' if group == 'rotation' else 'parked (not used by Hermes)'} --")
            last = group
        if u == "dead":
            print(f"  {label:34s} {state:8s}   n/a  sign-in expired: hermes auth add {provider} --type oauth --label {label}")
        elif u is None:
            print(f"  {label:34s} {state:8s}   n/a")
        else:
            util, reset = u
            fill = int(min(util, 100) // 5)
            ch = "=" if state == "PARKED" else "#"
            bar = ch * fill + "." * (20 - fill)
            print(f"  {label:34s} {state:8s} {util:4.0f}%  [{bar}]  {_hhmm(reset)}")
    return 0


def _parse_until(text: str) -> float:
    t = text.strip().lower()
    m = re.fullmatch(r"\+?(\d+)\s*(m|min|h|hr|d)", t)
    if m:
        return time.time() + int(m[1]) * {"m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400}[m[2]]
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        now = datetime.now()
        at = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        return at.timestamp()
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        raise SystemExit(f"Cannot read --until '{text}'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'.")


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
        print(f"Parked [{provider}]: {removed.label} (id={removed.id}) until {payload['_until_h']}.")
        print("It returns to rotation on the first balance run after that time (timer runs every 5 minutes).")
        if not _timer_active():
            print("WARNING: the balance timer is not active, so it will NOT come back by itself.")
    else:
        print(f"Parked [{provider}]: {removed.label} (id={removed.id}). Out of rotation until unparked.")
    print(f"Undo: hermes account {provider} unpark {removed.label}")
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
        print(f"{payload.get('label')} is already in rotation; parked record cleared.")
        return 0
    entry = pool.add_entry(PooledCredential.from_dict(provider, payload))
    _write_parked(rest)
    print(f"Unparked [{provider}]: {entry.label} (id={entry.id}), back in rotation.")
    ident = _identity(provider, entry)
    if ident is None:
        print("Login check not available for this provider.")
    elif "@" in ident:
        print(f"Login check: OK ({ident})")
    else:
        print(f"Login check: {ident}. If requests keep failing, sign in to this account again.")
    return 0


def _cmd_balance(args) -> int:
    provider = _norm(args.provider)
    _require_usage(provider)
    threshold = float(args.threshold)
    dry = bool(args.dry_run)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    actions = []

    # 1. timed parks that are due
    for item in [p for p in _read_parked() if p["_provider"] == provider and p.get("_until")]:
        if item["_until"] <= time.time():
            actions.append(f"unpark {item.get('label')} (park --until {item.get('_until_h')} reached)")
            if not dry:
                import contextlib
                import io
                from types import SimpleNamespace
                with contextlib.redirect_stdout(io.StringIO()):
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
        print(f"{stamp} [{provider}] balance: usage unavailable for every account; order unchanged.")
        for a in actions:
            print("  - " + a)
        return 0

    full = [(e, u) for e, u in known if u[0] >= threshold]
    # Never bench the whole pool for being "nearly" full: keep anything below 100%
    # usable when no account is under the threshold.
    if len(full) == len(known):
        full = [(e, u) for e, u in known if u[0] >= 100]

    full_ids = {e.id for e, _ in full}
    for e, (util, reset) in full:
        msg = f"{MARK} 5h usage {util:.0f}% >= {threshold:.0f}%"
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
    print(head + (" no change." if not actions else ""))
    for a in actions:
        print("  - " + a)
    return 0

def _cmd_doctor(args) -> int:
    import yaml
    provider = _norm(args.provider)
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
        f"strategy fill_first in {len(profiles)} profiles" if not bad else
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

    # file permissions
    for path in (root / "auth.json", root / "account-pool-parked.json"):
        if path.exists():
            mode = path.stat().st_mode & 0o777
            add("ok" if mode == 0o600 else "fail",
                f"{path.name} permissions {oct(mode)[2:]}" + ("" if mode == 0o600 else f". Fix: chmod 600 {path}"))

    # timer
    try:
        active = _timer_active()
        res = subprocess.run(["systemctl", "--user", "show", "hermes-account-balance.service",
                              "-p", "Result", "-p", "ExecMainExitTimestamp"],
                             capture_output=True, text=True, timeout=10).stdout
        info = dict(l.split("=", 1) for l in res.strip().splitlines() if "=" in l)
        last = info.get("ExecMainExitTimestamp") or "never"
        result = info.get("Result", "?")
        if not active:
            add("fail", "balance timer is NOT active. Fix: systemctl --user enable --now hermes-account-balance.timer")
        elif result != "success":
            add("fail", f"balance timer active but the last run failed ({result}). "
                        f"See: journalctl --user -u hermes-account-balance.service -n 20")
        else:
            add("ok", f"balance timer active, last run {last.split(' ', 1)[-1] if last != 'never' else 'never'}")
    except Exception as x:
        add("warn", f"could not query systemd: {x}")

    # history freshness
    hist = _read_history(provider, time.time() - 3600)
    if hist:
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
        f"{len(entries)} accounts in rotation, {len(parked)} parked" + (f"; DEAD: {', '.join(dead)}" if dead else ""))
    if cooling:
        add("warn", f"cooling down (auto-retried by balance): {', '.join(cooling)}")

    # usage endpoint
    if provider in USAGE:
        probe = next((e for e in entries if getattr(e, "last_status", None) != "dead" and not _token_expired(e)), None)
        if probe is None:
            add("warn", "usage endpoint not probed (no account with a fresh token)")
        else:
            add("ok" if _usage(provider, probe) else "fail",
                "usage endpoint reachable" if _usage(provider, probe) else
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

    icon = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    print(f"[{provider}] doctor")
    for level, text in checks:
        print(f"  {icon[level]}  {text}")
    fails = sum(1 for l, _ in checks if l == "fail")
    warns = sum(1 for l, _ in checks if l == "warn")
    print(f"  {fails} failure(s), {warns} warning(s).")
    return 1 if fails else 0


def _cmd_relogin(args) -> int:
    provider = _norm(args.provider)
    pool = _pool(provider)
    index, matched, error = pool.resolve_target(args.target)
    if matched is None or index is None:
        parked = [p for p in _read_parked() if p["_provider"] == provider
                  and str(args.target).lower() in (p.get("id", "").lower(), (p.get("label") or "").lower())]
        if parked:
            raise SystemExit(f"{parked[0].get('label')} is parked. Unpark it first: "
                             f"hermes account {provider} unpark {parked[0].get('label')}")
        raise SystemExit(f"{error} See: hermes account {provider} list")
    label, old_id, old_priority = matched.label, matched.id, matched.priority
    print(f"Re-login {label} ({provider}, id={old_id})")
    print("  1. A browser sign-in link opens. Use a PRIVATE / INCOGNITO window,")
    print(f"     otherwise the browser may sign in as a different account.")
    print(f"  2. Sign in as: {label}")
    print("  3. Paste the code back here.")
    print("The old entry is replaced only if the new sign-in really is that account.")
    if not args.yes:
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Cancelled. Nothing changed.")
            return 1
    before = {e.id for e in pool.entries()}
    rc = subprocess.call([_hermes_bin(), "auth", "add", provider, "--type", "oauth", "--label", label],
                         env=_hermes_env())
    pool = _pool(provider)
    new = [e for e in pool.entries() if e.id not in before]
    if rc != 0 or not new:
        print("Sign-in did not complete. The old entry is unchanged.")
        return 1
    fresh = new[0]
    ident = _identity(provider, fresh)
    if ident and "@" in ident and ident.lower() != label.lower():
        idx, _, _ = pool.resolve_target(fresh.id)
        pool.remove_index(idx)
        print(f"Signed in as {ident}, not {label}. The new sign-in was discarded; the old entry is unchanged.")
        print("Retry in a private/incognito window.")
        return 1
    idx, _, _ = pool.resolve_target(old_id)
    if idx is not None:
        pool.remove_index(idx)
    pool.move_entry(fresh.id, old_priority)
    print(f"Re-login OK: {label} (new id={fresh.id})" + (f", verified as {ident}" if ident and "@" in ident else ""))
    return 0


def _cmd_report(args) -> int:
    provider = _norm(args.provider)
    hours = float(args.hours or 24)
    since = time.time() - hours * 3600
    hist = _read_history(provider, since)
    if len(hist) < 2:
        print(f"[{provider}] Not enough history yet ({len(hist)} snapshot). "
              f"The balance timer records one every 5 minutes.")
        return 0
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
    print(f"[{provider}] usage report: last {hours:.0f}h ({len(hist)} snapshots, {span:.1f}h covered, "
          f"from {time.strftime('%m-%d %H:%M', time.localtime(hist[0]['ts']))})")
    print("  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.")
    print(f"  {'account':34s} {'used':>6s} {'share':>6s} {'peak':>5s}  {'time >= 90%':>11s}")
    for label in sorted(series, key=lambda l: -burn[l]):
        share = burn[label] / total * 100 if total else 0
        print(f"  {label:34s} {burn[label]:6.0f} {share:5.0f}% {peak[label]:4.0f}%  {hot[label]:8.0f} min")
    print(f"  {'total':34s} {total:6.0f}")
    if hourly:
        top = sorted(hourly.items(), key=lambda kv: -kv[1])[:3]
        print("  Busiest hours: " + ", ".join(f"{h:02d}:00-{(h + 1) % 24:02d}:00 ({v:.0f})" for h, v in top))
    print(f"  Time with EVERY account >= 90%: {full_min:.0f} min")
    if span < 2 or total < 30:
        print("  (Too little data for recommendations yet: needs at least 2 hours and some real load.)")
    elif full_min > 0:
        print("  -> The pool ran out of headroom. Consider adding an account.")
    elif max(burn.values()) / total > 0.5 and len(series) > 2:
        print("  -> One account carried most of the load; check `who` for long sessions pinned to it.")
    return 0


def _cmd_who(args) -> int:
    provider = _norm(args.provider)
    minutes = float(args.minutes or 30)
    data = _load_json(_root() / "account-pool-sessions.json", {})
    cutoff = time.time() - minutes * 60
    rows = [r for r in (data.get("sessions") or {}).values()
            if r.get("provider") == provider and r.get("last_seen", 0) >= cutoff]
    if not data:
        print("No sessions recorded yet. The tracker records a session after its next API call.")
    by_acc = defaultdict(list)
    for r in rows:
        by_acc[r.get("account", "?")].append(r)
    labels = [e.label for e in _entries(provider)]
    print(f"[{provider}] sessions active in the last {minutes:.0f} min: {len(rows)}")
    for label in labels + sorted(set(by_acc) - set(labels)):
        sess = sorted(by_acc.get(label, []), key=lambda r: -r.get("last_seen", 0))
        print(f"  {label}" + ("" if sess else "   (idle)"))
        for r in sess:
            ago = (time.time() - r["last_seen"]) / 60
            moved = f"  (moved from {r['previous_account']})" if r.get("previous_account") else ""
            print(f"      {r.get('profile', '?'):20s} {r.get('platform') or '-':9s} "
                  f"{(r.get('session_id') or '?')[:22]:22s} {r.get('model') or '':18s} {ago:3.0f}m ago{moved}")
    return 0


def _cmd_notify(args) -> int:
    sub = (args.target or "status").lower()
    cfg = _config()
    if sub == "status":
        tgt = _telegram_target(cfg)
        print("Alert channels:")
        print(f"  desktop  : {'on' if cfg['notify'].get('desktop') else 'off'}"
              + ("" if shutil.which("notify-send") else " (notify-send not installed)"))
        via = cfg["notify"].get("telegram_via") or "default"
        print(f"  telegram : {'on (your private chat)' if tgt else 'off'}"
              + (f", sent with the bot of profile '{via}'" if tgt else ""))
        print(f"  alert when every account is above {cfg.get('alert_all_above', 80)}%, "
              f"and when an account needs sign-in (DEAD).")
        print(f"Settings: {_config_path()}  (created with defaults on first change)")
        print("Change: hermes account <provider> notify desktop-on|desktop-off|telegram-on|telegram-off")
        print("        hermes account <provider> notify telegram-via=<profile>   (which bot sends)")
        return 0
    if sub == "test":
        sent = _notify("Hermes account-pool: test", "Alerts from `hermes account` reach this channel.")
        print(f"Test alert delivered to: {', '.join(sent) or 'no channel'}")
        return 0 if sent else 1
    if sub.startswith("telegram-via="):
        via = sub.split("=", 1)[1].strip() or "default"
        if via != "default" and not (_root() / "profiles" / via).is_dir():
            print(f"No profile named '{via}'.")
            return 2
        user = _load_json(_config_path(), {})
        user.setdefault("notify", {})["telegram_via"] = via
        _atomic_json(_config_path(), user)
        print(f"Telegram alerts are now sent with the bot of profile '{via}'.")
        return 0
    toggles = {"desktop-on": ("desktop", True), "desktop-off": ("desktop", False),
               "telegram-on": ("telegram", "auto"), "telegram-off": ("telegram", None)}
    if sub not in toggles:
        print("notify accepts: status, test, desktop-on, desktop-off, telegram-on, telegram-off, telegram-via=<profile>")
        return 2
    user = _load_json(_config_path(), {})
    key, val = toggles[sub]
    user.setdefault("notify", {})[key] = val
    _atomic_json(_config_path(), user)
    print(f"{key} alerts {'on' if val else 'off'}.")
    return 0


# ── registration ─────────────────────────────────────────────────────────────

ACTIONS = [
    ("list", "", "Accounts in rotation and parked accounts"),
    ("check", "", "Health: dead, rate-limited, wrong label, duplicate, real email"),
    ("usage", "", "Live 5-hour usage per account, parked included (anthropic)"),
    ("who", "[--minutes N]", "Which session is on which account (default: last 30 min)"),
    ("report", "[--hours N]", "Usage history: load per account, busiest hours (default 24h)"),
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
    "  hermes account anthropic usage",
    "  hermes account anthropic who",
    "  hermes account anthropic park alice@example.com --until 17:00",
    "  hermes account anthropic relogin bob@example.com",
    "  hermes account anthropic report --hours 72",
    "  hermes account anthropic doctor",
    "  hermes account anthropic notify test",
    "",
    "usage, balance, report and real-email lookup: anthropic only.",
    "list, check, park, unpark, relogin, who: every provider in the credential pool.",
])


def _print_help(_args=None) -> int:
    print(HELP)
    return 0


HANDLERS = {"list": _cmd_list, "check": _cmd_check, "usage": _cmd_usage, "who": _cmd_who,
            "report": _cmd_report, "park": _cmd_park, "unpark": _cmd_unpark, "relogin": _cmd_relogin,
            "balance": _cmd_balance, "doctor": _cmd_doctor, "notify": _cmd_notify}
NEEDS_TARGET = {"park", "unpark", "relogin"}
OPTIONAL_TARGET = {"notify"}
OPTIONS = {"threshold": ("--threshold", {"balance"}), "dry_run": ("--dry-run", {"balance"}),
           "until": ("--until", {"park"}), "hours": ("--hours", {"report"}),
           "minutes": ("--minutes", {"who"}), "yes": ("--yes", {"relogin"})}


def _dispatch(args) -> int:
    provider = (args.provider or "").strip()
    action = (args.action or "").strip().lower()
    if not provider or provider.lower() in ("help", "-h"):
        return _print_help()
    if not action or action == "help":
        if not action:
            print(f"Missing action for provider '{provider}'.\n")
        _print_help()
        return 0 if action == "help" else 2
    if action not in HANDLERS:
        import difflib
        close = difflib.get_close_matches(action, list(HANDLERS), n=1, cutoff=0.5)
        hint = f" Did you mean: {close[0]}?" if close else ""
        print(f"'{action}' is not an action.{hint}\nActions: {', '.join(HANDLERS)}, help")
        return 2
    if action in NEEDS_TARGET and not args.target:
        print(f"Missing target. Usage: hermes account {provider} {action} <email|id>")
        return 2
    if action not in NEEDS_TARGET | OPTIONAL_TARGET and args.target:
        print(f"'{action}' takes no target (got '{args.target}').")
        return 2
    for attr, (flag, allowed) in OPTIONS.items():
        val = getattr(args, attr, None)
        if val not in (None, False) and action not in allowed:
            print(f"{flag} only applies to: {', '.join(sorted(allowed))}")
            return 2
    if args.threshold is None:
        args.threshold = 90.0
    return HANDLERS[action](args)


def _setup(parser) -> None:
    import argparse
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.usage = "hermes account <provider> <action> [target] [options]"
    parser.description = HELP.replace("%", "%%")
    parser.add_argument("provider", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("action", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("target", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--threshold", type=float, default=None, help="balance: bench at/above this 5-hour %%")
    parser.add_argument("--dry-run", action="store_true", help="balance: show changes without applying them")
    parser.add_argument("--until", default=None, help="park: return automatically (17:00, +2h, 90m)")
    parser.add_argument("--hours", type=float, default=None, help="report: period in hours (default 24)")
    parser.add_argument("--minutes", type=float, default=None, help="who: activity window (default 30)")
    parser.add_argument("--yes", action="store_true", help="relogin: skip the confirmation prompt")
    parser.set_defaults(func=_dispatch)


def register(ctx) -> None:
    ctx.register_cli_command(
        name="account",
        help="Manage credential-pool accounts: hermes account <provider> <action>",
        setup_fn=_setup,
        handler_fn=None,
        description=HELP,
    )
