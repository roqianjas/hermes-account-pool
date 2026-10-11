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
    hermes account <provider> setup            profiles, tracker and timer after hermes plugins install
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
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
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
    rec = getattr(_OUT, "rec", None)
    if rec is not None:
        rec.append(sep.join(str(a) for a in args))


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
                   "alert_all_above": 80,
                   # a bot that uses far more than usual in the last hour (a loop, a runaway task)
                   "alert_bot": {"on": True, "usd": 15, "requests": 300, "factor": 3, "cooldown_h": 6}}


def _config_path() -> Path:
    return _root() / "account-pool.json"


def _config() -> dict:
    cfg = json.loads(json.dumps(CONFIG_DEFAULTS))
    user = _load_json(_config_path(), {})
    cfg["notify"].update(user.get("notify") or {})
    cfg["alert_bot"].update(user.get("alert_bot") or {})
    for k, v in user.items():
        if k not in ("notify", "alert_bot"):
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


def _read_history(provider: str, since: float, tail: int = 0) -> list[dict]:
    """Snapshots of `provider` from `since` on. tail > 0: read only the last `tail` bytes when they reach back
    to `since` (the newest hour without parsing 14 days)."""
    path = _history_path()
    if not path.exists():
        return []
    text = None
    if tail:
        with path.open("rb") as fh:
            size = fh.seek(0, 2)
            if size > tail:
                fh.seek(size - tail)
                chunk = fh.read().decode("utf-8", "replace").split("\n", 1)[-1]
                try:
                    first = json.loads(chunk.split("\n", 1)[0])
                except Exception:
                    first = {}
                if first.get("ts", since) < since:
                    text = chunk
    if text is None:
        text = path.read_text()
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("provider") == provider and rec.get("ts", 0) >= since:
            out.append(rec)
    return out


# ── activity log: what the timer, the command and the page changed ──────────

ACTIVITY_KEEP = 30 * 86400
ACTIVITY_MAX_BYTES = 1_000_000
_TIMER_PROC = []


def _activity_path() -> Path:
    return _root() / "account-pool-activity.jsonl"


def _in_timer() -> bool:
    """True inside the balance timer's service (its cgroup carries the unit name)."""
    if not _TIMER_PROC:
        try:
            _TIMER_PROC.append("hermes-account-balance" in Path("/proc/self/cgroup").read_text())
        except OSError:
            _TIMER_PROC.append(False)
    return _TIMER_PROC[0]


def _by() -> str:
    """Who made a change: "page" (the Accounts page backend sets it), "timer" or "cli"."""
    return getattr(_OUT, "by", None) or ("timer" if _in_timer() else "cli")


def _log(provider: str, kind: str, text: str) -> None:
    """Append one event to the activity log. Never raises: the log must not break an action."""
    try:
        path = _activity_path()
        line = json.dumps({"ts": round(time.time(), 1), "provider": provider, "by": _by(), "kind": kind,
                           "text": str(text).strip()})
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write(line + "\n")
        if path.stat().st_size > ACTIVITY_MAX_BYTES:
            cutoff = time.time() - ACTIVITY_KEEP
            keep = [l for l in path.read_text().splitlines() if _load_line_ts(l) >= cutoff]
            if sum(len(l) + 1 for l in keep) > ACTIVITY_MAX_BYTES:
                keep = keep[len(keep) // 4:]            # still too big: drop the oldest quarter
            tmp = path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write("\n".join(keep) + "\n")
            os.replace(tmp, path)
    except Exception:
        pass


def _read_activity(provider: str, since: float) -> list[dict]:
    path = _activity_path()
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


# The lines of a command's output that go into the activity log, per action.
LOG_LINES = {
    "park": r"^Parked \[",
    "unpark": r"^(Unparked \[|.+ is already in rotation)",
    "remove": r"^Removed ",
    "schedule": r"^Schedule saved",
    "unschedule": r"^Schedule removed",
    "strategy": r"^(Rotation strategy \[|FAILED )",
    "notify": r"^(desktop alerts|telegram alerts|Telegram alerts are now|Daily summary (on|off)|Bot alerts)",
}


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


def _notify(title: str, body: str, icon: str = "dialog-warning") -> list[str]:
    """Send to every configured channel; return the channels that succeeded."""
    cfg = _config()
    sent = []
    if cfg["notify"].get("desktop") and shutil.which("notify-send"):
        try:
            r = subprocess.run(["notify-send", "-a", "Hermes", "-i", icon, title, body],
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


# ── a bot that uses far more than usual ──────────────────────────────────────

def _bot_spikes(provider: str, now: float = None) -> list[dict]:
    """Profiles whose last hour is far above their usual hour, by API price or by requests.

    Usual = the mean of the profile's active hours in the 7 days before (hours with at least one request;
    needs 3 of them). A spike needs the floor (alert_bot.usd or .requests per hour) AND factor x the usual;
    while the usual is not known yet the floor counts double. Tokens without a bot name are skipped.
    Files only."""
    cfg = _config()["alert_bot"]
    now = now or time.time()
    rows, _ = _token_rows(provider)
    last = defaultdict(lambda: [0.0, 0, 0])
    hours = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for _label, profile, model, start, v in rows:
        if profile == "?" or start < now - 7 * 86400 or start > now:
            continue
        price = _model_price(provider, model)
        cost = sum(v[i] * price[i] for i in range(4)) / 1e6 if price else 0.0
        if start >= now - 3600:
            g = last[profile]
            g[0] += cost
            g[1] += v[4]
            g[2] += sum(v[:4])
        else:
            h = hours[profile][int(start // 3600)]
            h[0] += cost
            h[1] += v[4]
    factor = float(cfg.get("factor", 3))
    out = []
    for profile, (cost, req, tok) in last.items():
        active = [h for h in hours[profile].values() if h[1]]
        base_cost = sum(h[0] for h in active) / len(active) if len(active) >= 3 else None
        base_req = sum(h[1] for h in active) / len(active) if len(active) >= 3 else None
        warm = 1 if base_cost is not None else 2               # no usual yet: twice the floor
        by_cost = cost >= warm * float(cfg.get("usd", 15)) and (base_cost is None or cost >= factor * base_cost)
        by_req = req >= warm * int(cfg.get("requests", 300)) and (base_req is None or req >= factor * base_req)
        if by_cost or by_req:
            out.append({"profile": profile, "cost": round(cost, 2), "requests": req, "tokens": tok,
                        "usual_cost": round(base_cost, 2) if base_cost is not None else None,
                        "usual_requests": round(base_req) if base_req is not None else None,
                        "by": "cost" if by_cost else "requests"})
    out.sort(key=lambda r: -r["cost"])
    if out:
        top = {}
        for r in _sessions_data(provider, 1, top=50)["sessions"]:
            top.setdefault(r["profile"], r)
        for r in out:
            s = top.get(r["profile"])
            r["session"] = (dict({k: s.get(k) for k in ("session", "title", "source", "task")},
                                 cost=s["tokens"]["cost"], requests=s["tokens"]["requests"]) if s else None)
    return out


def _spike_text(provider: str, r: dict) -> tuple:
    """(title, body) of a bot alert."""
    if r["by"] == "cost":
        usual = (f", {r['cost'] / r['usual_cost']:.0f}x its usual ${r['usual_cost']:.2f} per active hour"
                 if r.get("usual_cost") else "")
    else:
        usual = (f", {r['requests'] / r['usual_requests']:.0f}x its usual {r['usual_requests']} per active hour"
                 if r.get("usual_requests") else "")
    body = f"Last hour: ${r['cost']:.2f} at API prices, {r['requests']} requests, {_fmt_tokens(r['tokens'])} tokens{usual}."
    s = r.get("session")
    if s:
        task = f", task {s['task']}" if s.get("task") else ""
        body += f"\nBusiest session: {s['title']} ({s['source']}{task}, {s['requests']} requests)."
    body += f"\nCheck: hermes account {provider} sessions --hours 1"
    return f"Hermes: {r['profile']} is using far more than usual", body


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
    if cfg["alert_bot"].get("on"):
        try:
            for r in _bot_spikes(provider):
                current[f"{provider}:bot:{r['profile']}"] = _spike_text(provider, r)
        except Exception:
            pass
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
    now = time.time()
    bot_state = _load_json(_state_path(), {}) or {}
    cooldown = float(cfg["alert_bot"].get("cooldown_h", 6)) * 3600
    sent_bot = False
    for key, (title, body) in current.items():
        if key not in mine:
            if ":bot:" in key:
                # a bot near the floor goes over and under it from run to run: one message per cooldown
                if now - float(bot_state.get(f"botsent:{key}", 0)) < cooldown:
                    continue
                bot_state[f"botsent:{key}"] = now
                sent_bot = True
            sent = _notify(title, body)
            actions.append(f"alert: {title} -> {', '.join(sent) or 'no channel delivered'}")
    if sent_bot:
        _atomic_json(_state_path(), bot_state)
    if f"{provider}:all-high" in mine and f"{provider}:all-high" not in current:
        lo_e, lo_u = min(known, key=lambda r: r[1][0]) if known else (None, None)
        body = f"{lo_e.label} is at {lo_u[0]:.0f}%." if lo_e else ""
        sent = _notify(f"Hermes: {provider} accounts available again", body)
        actions.append(f"alert cleared: all-high -> {', '.join(sent) or 'no channel delivered'}")
    other.update({k: mine.get(k, now) for k in current})
    _atomic_json(_alerts_path(), other)
    return actions


def _state_path() -> Path:
    """Timer bookkeeping that is not a setting: last daily summary, schedule windows already applied."""
    return _root() / "account-pool-state.json"


def _short(label: str) -> str:
    return str(label or "?").split("@")[0]


def _summary(provider: str, hours: float = 24) -> tuple:
    """(title, body) of the daily summary: tokens, bots, load per account, the pool now. Files only."""
    data = _report_data(provider, hours)
    tt = data["tokens_total"]
    lines = []
    if tt["requests"]:
        cost = _fmt_cost(tt)
        lines.append(f"Tokens: {_fmt_tokens(tt['total'])} in {tt['requests']} requests"
                     + (f", {cost} at API list prices." if cost != "-" else "."))
        bots = [g for g in data["by_profile"] if g["requests"]]
        if bots:
            lines.append("Bots: " + ", ".join(
                f"{'(older)' if g['name'] == '?' else g['name']} {_fmt_tokens(g['total'])}" for g in bots[:4])
                + (f", +{len(bots) - 4} more" if len(bots) > 4 else "") + ".")
    else:
        lines.append("Tokens: none counted through Hermes.")
    used = [a for a in data["accounts"] if a["used"] > 0]
    if used:
        top = max(data["accounts"], key=lambda a: a["peak"])
        lines.append("Share of the load: " + ", ".join(f"{_short(a['label'])} {a['share']:.0f}%" for a in used[:3])
                     + (f" and {len(used) - 3} more" if len(used) > 3 else "") + f". Highest {data['window']} usage: {top['peak']:.0f}% "
                     f"({_short(top['label'])}). Every account >= 90% at once: {data['full_min']:.0f} min.")
    if data["busiest"]:
        h = data["busiest"][0][0]
        lines.append(f"Busiest hour: {h:02d}:00-{(h + 1) % 24:02d}:00.")
    entries = sorted(_entries(provider), key=lambda e: e.priority)
    parked = [p for p in _read_parked() if p["_provider"] == provider]
    last = (_read_history(provider, time.time() - 1800) or [{}])[-1].get("usage") or {}
    usable = [e for e in entries if _entry_state(e) == "active"]
    now = f"Now: {len(entries)} in rotation, {len(parked)} parked"
    if usable:
        nxt = usable[0]
        pct = last.get(nxt.label)
        now += f"; new sessions start on {_short(nxt.label)}" + (f" ({pct:.0f}%)" if pct is not None else "")
    lines.append(now + ".")
    if _has_usage(provider):
        fc = _forecast(provider)
        if fc["status"] == "ok":
            lines.append("Forecast: " + fc["text"])
    try:
        top = _sessions_data(provider, hours, top=1)["sessions"]
    except Exception:
        top = []
    if top:
        t = top[0]
        lines.append(f"Top session: {t['title'][:60]} ({t['profile']}, {_fmt_tokens(t['tokens']['total'])} tokens, "
                     f"{_fmt_cost(t['tokens'])}).")
    dead = [e.label for e in entries if getattr(e, "last_status", None) == "dead"]
    if dead:
        lines.append(f"Needs sign-in: {', '.join(_short(x) for x in dead)}. Fix: hermes account {provider} relogin <account>")
    if data["advice"] and not data["advice"].startswith("Too little"):
        lines.append(data["advice"])
    return f"Hermes {provider}: last {hours:.0f} h", "\n".join(lines)


def _daily_at(cfg: dict):
    """The daily summary time as (hour, minute), or None when it is off."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str((cfg.get("notify") or {}).get("daily") or ""))
    return (int(m[1]), int(m[2])) if m and int(m[1]) < 24 and int(m[2]) < 60 else None


def _run_daily(provider: str) -> list[str]:
    """Send the daily summary on the first balance run at or after its time, once a day."""
    at = _daily_at(_config())
    if not at:
        return []
    now = datetime.now()
    if (now.hour, now.minute) < at:
        return []
    state = _load_json(_state_path(), {}) or {}
    key, today = f"daily:{provider}", now.strftime("%Y-%m-%d")
    if state.get(key) == today:
        return []
    title, body = _summary(provider)
    sent = _notify(title, body, icon="dialog-information")
    state[key] = today
    _atomic_json(_state_path(), state)
    return [f"daily summary -> {', '.join(sent) or 'no channel delivered'}"]


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_every(text: str) -> dict:
    """'mon-fri 09:00-17:00' -> {"days": [0..4], "from": "09:00", "to": "17:00"}. Days: daily, weekdays,
    weekend, names (mon..sun) and ranges, comma-separated. A window that ends before it starts runs past
    midnight."""
    bad = (f"Cannot read --every '{text}'. Use days and a time range, e.g. \"mon-fri 09:00-17:00\", "
           f"\"daily 22:00-06:00\" or \"sat,sun 10:00-14:00\".")
    m = re.fullmatch(r"\s*(.+?)\s+(\d{1,2})[:.](\d{2})\s*-\s*(\d{1,2})[:.](\d{2})\s*", str(text or "").lower())
    if not m:
        raise SystemExit(bad)
    h1, m1, h2, m2 = (int(x) for x in m.groups()[1:])
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or (h1, m1) == (h2, m2):
        raise SystemExit(bad)
    days = set()
    for part in re.split(r"\s*,\s*", m[1].strip()):
        part = part.strip()
        if part in ("daily", "every day", "everyday", "all"):
            days |= set(range(7))
        elif part in ("weekdays", "workdays"):
            days |= set(range(5))
        elif part in ("weekend", "weekends"):
            days |= {5, 6}
        else:
            r = re.fullmatch(r"([a-z]{3})[a-z]*(?:\s*-\s*([a-z]{3})[a-z]*)?", part)
            if not r or r[1] not in DAYS or (r[2] and r[2] not in DAYS):
                raise SystemExit(bad)
            a, b = DAYS.index(r[1]), DAYS.index(r[2] or r[1])
            days |= {(a + i) % 7 for i in range((b - a) % 7 + 1)}
    return {"days": sorted(days), "from": f"{h1:02d}:{m1:02d}", "to": f"{h2:02d}:{m2:02d}"}


def _every_text(s: dict) -> str:
    days = sorted(s.get("days") or [])
    if len(days) == 7:
        d = "Every day"
    else:
        runs, run = [], [days[0]] if days else []
        for x in days[1:]:
            if x == run[-1] + 1:
                run.append(x)
            else:
                runs.append(run)
                run = [x]
        if run:
            runs.append(run)
        d = ", ".join(DAYS[r[0]].title() + (f"-{DAYS[r[-1]].title()}" if len(r) > 2 else
                                             f", {DAYS[r[-1]].title()}" if len(r) == 2 else "") for r in runs)
    return f"{d} {s.get('from')}-{s.get('to')}"


def _schedule_window(s: dict, now: float, ahead: bool = False):
    """(start, end) of the window that contains `now`; with ahead=True the next one that starts after it."""
    h1, m1 = (int(x) for x in s["from"].split(":"))
    h2, m2 = (int(x) for x in s["to"].split(":"))
    base = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in (range(0, 8) if ahead else (0, -1)):
        day = base + timedelta(days=d)
        if day.weekday() not in s.get("days", []):
            continue
        start = day.replace(hour=h1, minute=m1).timestamp()
        end = (day + timedelta(days=1 if (h2, m2) <= (h1, m1) else 0)).replace(hour=h2, minute=m2).timestamp()
        if (start > now) if ahead else (start <= now < end):
            return start, end
    return None


def _schedules(provider: str) -> list:
    return [s for s in ((_config().get("schedules") or {}).get(provider) or []) if s.get("label")]


def _run_schedules(provider: str, dry: bool = False) -> list[str]:
    """Park scheduled accounts at the start of their window, until its end (the timed-park return brings
    them back). Each window is applied once: unparking by hand inside it is not undone."""
    from types import SimpleNamespace
    scheds = _schedules(provider)
    state = _load_json(_state_path(), {}) or {}
    applied = state.get("schedule") or {}
    keep = {k: v for k, v in applied.items() if not k.startswith(provider + ":")}
    now = time.time()
    actions = []
    for s in scheds:
        key = f"{provider}:{s['label'].lower()}"
        win = _schedule_window(s, now)
        if not win:
            continue
        start, end = win
        if applied.get(key) == start:
            keep[key] = start
            continue
        entry = next((e for e in _entries(provider) if e.label.lower() == s["label"].lower()), None) \
            or next((e for e in _entries(provider) if s.get("id") and e.id == s["id"]), None)
        if entry is None:
            if _find_parked(provider, s["label"]):
                keep[key] = start                     # parked already: leave it as it is
            continue
        until = time.strftime("%Y-%m-%d %H:%M", time.localtime(end))
        if dry:
            actions.append(f"schedule: park {entry.label} until {_hhmm(end)}")
            continue
        with _capture():
            try:
                _cmd_park(SimpleNamespace(provider=provider, target=entry.id, until=until, by="schedule"))
                actions.append(f"schedule: parked {entry.label} until {_hhmm(end)} ({_every_text(s)})")
                keep[key] = start
            except SystemExit as x:
                actions.append(f"schedule: could not park {entry.label}: {x}")
    if not dry and keep != applied:
        state["schedule"] = keep
        _atomic_json(_state_path(), state)
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
        by = " (schedule)" if p.get("_by") == "schedule" else ""
        _p(f"  -   {p.get('label', '?'):34s} id={p.get('id')}  since {p.get('_parked_at_h', '?')}{until}{by}")
    rows = _schedule_rows(provider)
    if rows:
        _p(f"[{provider}] park schedules ({len(rows)}):")
        for r in rows:
            _p(f"  -   {r['label']:34s} {r['every']}" + ("" if r["found"] else "  (not in the pool)"))
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
    fc = _forecast(provider)
    if fc["status"] != "no-data":
        _p(f"  Forecast (balance timer history): {fc['text']}")
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
    if getattr(args, "by", None):
        payload["_by"] = args.by
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


def _log_actions(provider: str, actions: list, dry: bool) -> None:
    """Balance's changes into the activity log. The new order is left out: it changes on most runs."""
    if dry:
        return
    for a in actions:
        if a.startswith("order:"):
            continue
        kind = ("alert" if a.startswith("alert") else "schedule" if a.startswith("schedule") else
                "unpark" if a.startswith("unpark ") else "summary" if a.startswith("daily") else "balance")
        _log(provider, kind, a)


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

    # 1b. park schedules whose window has started
    try:
        actions += _run_schedules(provider, dry)
    except Exception as x:
        actions.append(f"schedules failed: {x}")

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
            try:
                actions += _run_daily(provider)
            except Exception as x:
                actions.append(f"daily summary failed: {x}")
        _p(f"{stamp} [{provider}] balance{' (dry run)' if dry else ''}: no usage adapter, order unchanged.")
        _log_actions(provider, actions, dry)
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
            try:
                actions += _run_daily(provider)
            except Exception as x:
                actions.append(f"daily summary failed: {x}")
        _p(f"{stamp} [{provider}] balance: usage unavailable for every account; order unchanged.")
        _log_actions(provider, actions, dry)
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
        try:
            actions += _run_daily(provider)
        except Exception as x:
            actions.append(f"daily summary failed: {x}")

    head = f"{stamp} [{provider}] balance{' (dry run)' if dry else ''}:"
    _p(head + (" no change." if not actions else ""))
    _log_actions(provider, actions, dry)
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


POOL_STRATEGIES = ("fill_first", "round_robin", "random", "least_used")   # Hermes' credential_pool_strategies


def _profile_homes() -> list:
    """[(name, home)] for the default profile and every profile with a config.yaml."""
    root = _root()
    out = [("default", root)]
    pdir = root / "profiles"
    if pdir.is_dir():
        out += [(d.name, d) for d in sorted(pdir.iterdir()) if (d / "config.yaml").exists()]
    return out


def _strategies(provider: str) -> list:
    """[(profile, value of credential_pool_strategies.<provider> or None when unset)]."""
    import yaml
    out = []
    for name, home in _profile_homes():
        try:
            cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
        except Exception:
            cfg = {}
        value = (cfg.get("credential_pool_strategies") or {}).get(provider) if isinstance(cfg, dict) else None
        out.append((name, str(value) if value else None))
    return out


def _effective_strategy(value) -> str:
    """The strategy Hermes uses for a configured value: unset or unknown values mean fill_first."""
    v = str(value or "").strip().lower()
    return v if v in POOL_STRATEGIES else "fill_first"


STRATEGY_TEXT = {
    "fill_first": "every new session takes the first usable account. With the balance timer that is the least-used one.",
    "round_robin": "each new session takes the next account in turn and moves it to the end. Rewrites the order balance sets.",
    "least_used": "each new session takes the account picked least often by this computer, not the one with the most quota left.",
    "random": "each new session takes a random usable account.",
}


def _set_strategy(home: Path, provider: str, value: str) -> None:
    """Write credential_pool_strategies.<provider> into one profile's config.yaml. Raises RuntimeError on failure."""
    _set_config_value(home, f"credential_pool_strategies.{provider}", value)


def _set_config_value(home: Path, key: str, value: str) -> None:
    """Write one key into one profile's config.yaml with Hermes' own writer (`hermes config set`), so the
    file keeps Hermes' format and checks. Raises RuntimeError on failure."""
    try:
        from hermes_cli.config import set_config_value
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    except ImportError:                                  # older Hermes: same command in a subprocess
        r = subprocess.run([_hermes_bin(), "config", "set", key, value], env=dict(os.environ, HERMES_HOME=str(home)),
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or [f"exit code {r.returncode}"])[-1])
        return
    out = io.StringIO()
    token = set_hermes_home_override(str(home))        # context-local: other threads keep their home
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            set_config_value(key, value)
    except SystemExit as x:
        lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
        raise RuntimeError(lines[-1] if lines else str(x.code))
    finally:
        reset_hermes_home_override(token)


def _cmd_strategy(args) -> int:
    """Show or set Hermes' rotation strategy (credential_pool_strategies.<provider>) per profile."""
    provider = _norm(args.provider)
    homes = dict(_profile_homes())
    only = [p.strip() for p in str(getattr(args, "only", None) or "").split(",") if p.strip()]
    unknown = [p for p in only if p not in homes]
    if unknown:
        raise SystemExit(f"No profile named {', '.join(unknown)}. Profiles: {', '.join(homes)}")
    rows = _strategies(provider)
    if not args.target:
        if only:
            _p(f"--only needs a strategy: hermes account {provider} strategy <{'|'.join(POOL_STRATEGIES)}> --only {','.join(only)}")
            return 2
        _p(f"[{provider}] rotation strategy per profile (Hermes: credential_pool_strategies.{provider}):")
        for name, value in rows:
            eff = _effective_strategy(value)
            note = ("  (not set: Hermes uses fill_first)" if not value else
                    f"  (unknown value '{value}': Hermes uses fill_first)" if value.strip().lower() != eff else "")
            _p(f"  {name:28s} {eff}{note}")
        _p("")
        for name, text in STRATEGY_TEXT.items():
            _p(f"  {name:12s} {text}")
        _p("Balance is built for fill_first: the order it sets decides where new sessions start.")
        _p(f"Change: hermes account {provider} strategy <{'|'.join(POOL_STRATEGIES)}> [--only <profile>,...]")
        return 0
    value = str(args.target).strip().lower()
    if value not in POOL_STRATEGIES:
        _p(f"'{args.target}' is not a strategy. Strategies: {', '.join(POOL_STRATEGIES)}")
        return 2
    targets = [(n, v) for n, v in rows if not only or n in only]
    change = [(n, v) for n, v in targets if (v or "").strip().lower() != value and (v or value != "fill_first")]
    if not change:
        _p(f"Nothing to change: {', '.join(n for n, _ in targets)} already use{'s' if len(targets) == 1 else ''} {value}.")
        return 0
    if value != "fill_first":
        _p(f"WARNING: {value} ignores the order balance sets, so a new session can start on a nearly full account.")
        if not _confirm(f"Set {value} in {', '.join(n for n, _ in change)}?", args.yes):
            _p("Nothing changed.")
            return 1
    done, failed = [], []
    for name, old in change:
        try:
            _set_strategy(homes[name], provider, value)
            now = dict(_strategies(provider)).get(name)
            if (now or "").strip().lower() != value:
                raise RuntimeError(f"config.yaml still says {now or 'nothing'}")
            done.append(f"{name} (was {old or 'not set'})")
        except Exception as e:  # noqa: BLE001  (report per profile, keep going)
            failed.append(f"{name}: {e}")
    if done:
        _p(f"Rotation strategy [{provider}]: {value} in {', '.join(done)}.")
        _p("New sessions there use it from now; running sessions keep their account.")
    for f in failed:
        _p(f"FAILED {f}")
    if done and value != "fill_first":
        _p(f"Back to the strategy balance needs: hermes account {provider} strategy fill_first")
    return 1 if failed else 0


# ── running processes with an older session tracker ─────────────────────────

TRACKER_DIR = Path(__file__).resolve().parent.parent / "account-pool-tracker"
MESSAGING_KIND = "gateway"


def _tracker_installed() -> tuple:
    """(version, time it was installed) of the session tracker next to this plugin; (None, None) without it."""
    try:
        m = re.search(r"^version:\s*['\"]?([\w.]+)", (TRACKER_DIR / "plugin.yaml").read_text(), re.M)
        return (m[1] if m else None), (TRACKER_DIR / "__init__.py").stat().st_mtime
    except OSError:
        return None, None


def _process_kind(pid):
    """"gateway", "desktop" or "session" for a running process; None when it has ended."""
    try:
        pid = int(pid)
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return None
    except PermissionError:
        pass
    try:
        args = [a.decode(errors="replace") for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")]
    except OSError:
        return "session"
    if "gateway" in args:
        return "gateway"
    if "serve" in args or "desktop" in args:
        return "desktop"
    return "session"


TRACKER_FIX = {"gateway": "hermes gateway restart (it serves the Telegram bots and cron jobs)",
               "desktop": "restart Hermes Desktop",
               "session": "it loads the new tracker when it ends; restart it to switch sooner"}


def _tracker_status(provider: str) -> dict:
    """Which running processes still count with an older session tracker.

    A tracker is loaded when its process starts, so after an update the gateway, Hermes Desktop and long
    sessions keep the old one until they restart. Found from the session records written since the
    update: tracker 1.4.0 and later write their version and process id; older ones write neither.
    Keys: version, stale [{kind, pid, profiles, platforms, tracker, last_seen, fix}], unnamed_since (start of
    the latest 15-minute bucket of the last half hour with tokens but no bot name: tracker 1.2.0 or older)."""
    version, installed_at = _tracker_installed()
    now = time.time()
    out = {"version": version, "stale": [], "unnamed_since": None}
    if not version:
        return out
    data = _load_json(_root() / "account-pool-sessions.json", {}) or {}
    groups = {}
    for r in (data.get("sessions") or {}).values():
        seen = r.get("last_seen") or 0
        if r.get("provider") != provider or seen < max(now - 1800, installed_at + 120) or r.get("tracker") == version:
            continue
        pid = r.get("pid")
        if pid:
            kind = _process_kind(pid)
            if kind is None:                        # that process has ended
                continue
        else:
            plat = (r.get("platform") or "").lower()
            kind = "desktop" if plat == "desktop" else "session" if plat in ("cli", "") else MESSAGING_KIND
        key = pid or f"{kind}:{r.get('profile')}"
        g = groups.setdefault(key, {"kind": kind, "pid": pid, "profiles": [], "platforms": [],
                                    "tracker": r.get("tracker") or "older than 1.4.0", "last_seen": 0})
        for field, value in (("profiles", r.get("profile") or "?"), ("platforms", r.get("platform") or "-")):
            if value not in g[field]:
                g[field].append(value)
        g["last_seen"] = max(g["last_seen"], seen)
    out["stale"] = [dict(g, fix=TRACKER_FIX[g["kind"]]) for g in
                    sorted(groups.values(), key=lambda g: ({"gateway": 0, "desktop": 1}.get(g["kind"], 2), -g["last_seen"]))]
    rows, _ = _token_rows(provider)
    unnamed = [row[3] for row in rows if row[1] == "?" and row[3] >= now - 1800 - TOKEN_BUCKET]
    out["unnamed_since"] = max(unnamed) if unnamed else None
    return out


def _tracker_who(g: dict) -> str:
    """One stale process in words: "the gateway (worker-1, telegram; tracker 1.3.0)"."""
    name = {"gateway": "the gateway", "desktop": "Hermes Desktop"}.get(g["kind"], f"a {'/'.join(g['platforms'])} session")
    pid = f", pid {g['pid']}" if g.get("pid") else ""
    return f"{name} ({', '.join(g['profiles'])}{pid}; tracker {g['tracker']})"


def _doctor_checks(provider: str) -> list:
    """[(level, text)] with level ok / warn / fail. Probes the usage endpoint once."""
    import yaml
    root = _root()
    checks = []                                    # (level, text) level: ok / warn / fail

    def add(level, text):
        checks.append((level, text))

    profiles = _profile_homes()

    # strategy per profile
    strategies = _strategies(provider)
    bad = [f"{name}={value}" for name, value in strategies if _effective_strategy(value) != "fill_first"]
    odd = [f"{name}={value}" for name, value in strategies
           if value and _effective_strategy(value) == "fill_first" and value.strip().lower() != "fill_first"]
    add("ok" if not bad else "fail",
        f"strategy fill_first in {len(profiles)} profile{'' if len(profiles) == 1 else 's'}" if not bad else
        f"strategy is not fill_first: {', '.join(bad)} (balance order is ignored there). "
        f"Fix: hermes account {provider} strategy fill_first")
    if odd:
        add("warn", f"unknown strategy value: {', '.join(odd)} (Hermes uses fill_first). "
                    f"Fix: hermes account {provider} strategy fill_first")

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
        f"session tracker missing in: {', '.join(missing)} (`who` will not show them). Fix: hermes account {provider} setup")

    # processes that loaded the tracker before its last update
    tr = _tracker_status(provider)
    if tr["stale"]:
        fixes = []
        for g in tr["stale"]:
            if g["fix"] not in fixes:
                fixes.append(g["fix"])
        add("warn", f"session tracker {tr['version']} is not loaded yet by: {'; '.join(_tracker_who(g) for g in tr['stale'])}. "
                    f"They count without the newest tracker features until they restart. Fix: {'; '.join(fixes)}")
    if tr["unnamed_since"]:
        add("warn", f"tokens without a bot name until {_hhmm(tr['unnamed_since'] + TOKEN_BUCKET)}: a process with tracker 1.2.0 "
                    f"or older was running then. Fix: hermes gateway restart, restart Hermes Desktop, or end long "
                    f"sessions (once it has ended, this line clears within 45 min)")
    if tr["version"] and not tr["stale"] and not tr["unnamed_since"]:
        add("ok", f"running sessions count with tracker {tr['version']}")

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
            f"'backend did not answer' while it runs one of them). Fix: hermes account {provider} setup")

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
            add("fail", f"balance timer is NOT active. Fix: hermes account {provider} setup --timer")
        elif timer["result"] != "success" and not timer["running"]:
            add("fail", f"balance timer active but the last run failed ({timer['result']}). "
                        f"See: journalctl --user -u hermes-account-balance.service -n 20")
        else:
            add("ok", f"balance timer active, last run {timer['last']}")
        execs = subprocess.run(["systemctl", "--user", "show", "hermes-account-balance.service", "-p", "ExecStart"],
                               capture_output=True, text=True, timeout=10).stdout
        if active and not re.search(rf"account\s+{re.escape(provider)}\s+balance", execs):
            add("warn", f"the balance timer does not run {provider} (timed unparks, cooldown recovery and alerts "
                        f"for {provider} wait for a manual balance). Fix: hermes account {provider} setup --timer")
    except Exception as x:
        add("warn", f"could not query systemd: {x}")

    # history freshness
    hist = _read_history(provider, time.time() - 3600) if _has_usage(provider) else None
    if hist is None:
        pass
    elif hist:
        age = max(0.0, (time.time() - hist[-1]["ts"]) / 60)      # a run that just wrote it: not "-0"
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
    at = _daily_at(cfg)
    if at:
        add("ok" if chans else "warn", f"daily summary at {at[0]:02d}:{at[1]:02d}"
            + ("" if chans else ", but no alert channel is on to deliver it"))
    rows = _schedule_rows(provider)
    lost = [r["label"] for r in rows if not r["found"]]
    if lost:
        add("warn", f"park schedule for an account that is not in the pool: {', '.join(lost)}. "
                    f"Fix: hermes account {provider} unschedule <account>")
    elif rows:
        add("ok", f"park schedules: {', '.join(r['label'] + ' ' + r['every'] for r in rows)}")
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


def _codex_browser_signin() -> bool:
    """True when this Hermes can sign in to OpenAI Codex in the browser (`hermes auth add openai-codex --browser`)."""
    import importlib.util
    try:
        return importlib.util.find_spec("hermes_cli.auth_codex_browser") is not None
    except (ImportError, ValueError):
        return False


def _signin_method(provider: str, args) -> str:
    """How `hermes auth add` signs in: "code" (paste a code), "browser" or "device" (openai-codex).

    Codex signs in through the browser by default: ChatGPT Business and Enterprise workspaces turn
    device codes off, and the browser sign-in works with or without them. --device picks the device
    code; Hermes before 0.21.6 knows only that one."""
    if provider != "openai-codex":
        if getattr(args, "device", False):
            raise SystemExit("--device is only for openai-codex. Nothing changed.")
        return "code"
    if getattr(args, "device", False) or not _codex_browser_signin():
        return "device"
    return "browser"


def _signin_cmd(provider: str, label: str, method: str) -> list:
    cmd = [_hermes_bin(), "auth", "add", provider, "--type", "oauth", "--label", label]
    if method == "browser":
        cmd += ["--browser", "--no-browser"]     # print the link: the user picks the browser profile
    return cmd


def _signin_steps(provider: str, label: str, method: str) -> None:
    if method == "browser":
        _p("  1. Open the sign-in link in a browser ON THIS COMPUTER that is signed in to ChatGPT as THIS")
        _p("     account: its own Chrome profile, or a private / incognito window.")
        _p("  2. Pick the workspace and authorize. The browser then opens a localhost:1455 page that says")
        _p("     \"authorization received\", and the sign-in finishes here by itself.")
        _p("     Browser on another computer? Use the Accounts page in Hermes Desktop (it takes the")
        _p("     address the browser ends on), or sign in with a code: add --device.")
    elif method == "device":
        _p("  1. Open https://auth.openai.com/codex/device in a browser signed in to ChatGPT as THIS account.")
        _p("  2. Enter the code shown below and authorize. The sign-in finishes here by itself.")
        _p("     \"Contact your workspace admin to enable device code authentication\": the ChatGPT")
        _p("     workspace turned device codes off. Sign in without --device instead.")
    else:
        _p("  1. Open the sign-in link in a browser that is signed in as THIS account:")
        _p("     its own Chrome profile, or a private / incognito window.")
        _p(f"  2. Make sure the page says: Logged in as {label}  (otherwise: Switch account)")
        _p("     \"Sign in again to continue\" is normal when that browser login is old.")
        _p("  3. Authorize, then paste the code back here.")


def _signin_needs_tty(provider: str, action: str, target: str, key: bool = False, method: str = "code") -> bool:
    """True (after saying why) when a sign-in cannot run here: the link is shown and the code or the key
    is pasted in a terminal. `--yes` does not change that, so cron, the gateway and an agent's shell get
    an answer instead of a hang."""
    if _tty():
        return False
    what = ("the API key is typed" if key else "the authorization code is pasted" if method == "code"
            else "the sign-in link is shown")
    _p(f"{action} needs a terminal: {what} there. Nothing changed.")
    _p(f"Run it in a terminal: hermes account {provider} {action} {target}{' --key' if key else ''}")
    if not key and providers.get(provider).has_web_signin and _oauth_provider(provider):
        _p("Or use Add account / Sign in again on the Accounts page in Hermes Desktop.")
    return True


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
    _log(provider, "relogin", f"Re-login OK: {label}")
    return 0


def _cmd_relogin(args) -> int:
    provider = _norm(args.provider)
    label, old_id, old_priority = _relogin_target(provider, args.target)
    method = _signin_method(provider, args)
    if _signin_needs_tty(provider, "relogin", label, method=method):
        return 1
    verify = providers.get(provider).has_identity
    _p(f"Re-login {label} ({provider}, id={old_id})")
    _signin_steps(provider, label, method)
    _p("The old entry is replaced only if the new sign-in really is that account."
          if verify else
          f"NOTE: {provider} has no identity adapter, so the account cannot be verified. Sign in carefully.")
    if not _confirm("Continue?", args.yes):
        _p("Cancelled. Nothing changed.")
        return 1
    before = {e.id for e in _pool(provider).entries()}
    rc = _signin(_signin_cmd(provider, label, method), provider, before)
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


def _token_rows(provider: str) -> tuple:
    """([(label, profile, model, bucket_start, [in, out, cache_read, cache_write, requests])], counting_since).

    Written by the session tracker after every API call through the pool: per account, profile and model
    from tracker 1.3.0 on; 1.1.0 buckets (account only) read as profile "?" and model "?"."""
    data = _load_json(_root() / "account-pool-tokens.json", {}) or {}
    out = []

    def take(slots, label, profile, model):
        for k, v in (slots or {}).items():
            try:
                vals = [int(x) for x in list(v)[:5]]
                out.append((label, profile, model, float(k), vals + [0] * (5 - len(vals))))
            except (TypeError, ValueError):
                continue

    for label, profiles in ((data.get("counts") or {}).get(provider) or {}).items():
        for profile, models in (profiles or {}).items():
            for model, slots in (models or {}).items():
                take(slots, label, profile, model)
    for label, slots in ((data.get("buckets") or {}).get(provider) or {}).items():
        take(slots, label, "?", "?")
    return out, data.get("since")


def _token_buckets(provider: str) -> tuple:
    """({label: {bucket_start: [in, out, cache_read, cache_write, requests]}}, counting_since or None)."""
    rows, since = _token_rows(provider)
    out = {}
    for label, _profile, _model, start, v in rows:
        acc = out.setdefault(label, {}).setdefault(start, [0, 0, 0, 0, 0])
        for i in range(5):
            acc[i] += v[i]
    return out, since


def _token_sum(rows: dict, since: float, until: float = None) -> dict:
    """Totals of {bucket_start: [in, out, cache_read, cache_write, requests]} from `since` (to `until`)."""
    acc = [0, 0, 0, 0, 0]
    for start, v in rows.items():
        if start >= since and (until is None or start < until):
            for i in range(5):
                acc[i] += v[i] if i < len(v) else 0
    out = dict(zip(TOKEN_KEYS, acc))
    out["total"] = sum(acc[:4])
    return out


_PRICES = {}


def _model_price(provider: str, model: str):
    """API list price per million tokens (input, output, cache read, cache write) for a model, or None.

    From Hermes' bundled price snapshot, else its models.dev disk cache. Never a network request."""
    key = (provider, model)
    if key in _PRICES:
        return _PRICES[key]
    api = {"openai-codex": "openai"}.get(provider, provider)
    bare = str(model or "").split("/")[-1]
    price = None
    if bare and bare != "?":
        try:
            from agent.usage_pricing import _lookup_official_docs_pricing, resolve_billing_route
            e = _lookup_official_docs_pricing(resolve_billing_route(bare, provider=api))
            if e and e.input_cost_per_million is not None and e.output_cost_per_million is not None:
                inp = float(e.input_cost_per_million)
                cr, cw = e.cache_read_cost_per_million, e.cache_write_cost_per_million
                price = (inp, float(e.output_cost_per_million), float(cr) if cr is not None else inp,
                         float(cw) if cw is not None else inp)
        except Exception:
            price = None
        if price is None:
            try:
                from agent.models_dev import _load_disk_cache
                cost = ((((_load_disk_cache() or {}).get(api) or {}).get("models") or {}).get(bare) or {}).get("cost") or {}
                if cost.get("input") is not None and cost.get("output") is not None:
                    inp = float(cost["input"])
                    price = (inp, float(cost["output"]), float(cost.get("cache_read", inp)),
                             float(cost.get("cache_write", inp)))
            except Exception:
                price = None
    _PRICES[key] = price
    return price


def _token_group(provider: str, rows: list, since: float, until: float = None, by: str = "label") -> dict:
    """Token totals of the buckets in [since, until), grouped by "label", "profile", "model" or "all".

    Each value: input, output, cache_read, cache_write, requests, total, cost (USD at API list prices,
    for the tokens whose model has a known price), unpriced (tokens without a price), model (largest)."""
    idx = {"label": 0, "profile": 1, "model": 2}
    groups = {}
    for row in rows:
        start, v = row[3], row[4]
        if start < since or (until is not None and start >= until):
            continue
        key = "all" if by == "all" else row[idx[by]]
        g = groups.setdefault(key, {"v": [0, 0, 0, 0, 0], "cost": 0.0, "unpriced": 0, "models": defaultdict(int),
                                    "labels": set()})
        g["labels"].add(row[0])
        for i in range(5):
            g["v"][i] += v[i]
        price = _model_price(provider, row[2])
        if price:
            g["cost"] += sum(v[i] * price[i] for i in range(4)) / 1e6
        else:
            g["unpriced"] += sum(v[:4])
        g["models"][row[2]] += sum(v[:4])
    out = {}
    for key, g in groups.items():
        d = dict(zip(TOKEN_KEYS, g["v"]))
        d.update(total=sum(g["v"][:4]), cost=round(g["cost"], 4), unpriced=g["unpriced"],
                 model=max(g["models"], key=g["models"].get) if g["models"] else None, accounts=len(g["labels"]))
        out[key] = d
    return out


def _empty_tokens() -> dict:
    return dict(dict.fromkeys(TOKEN_KEYS, 0), total=0, cost=0.0, unpriced=0, model=None, accounts=0)


def _fmt_tokens(n) -> str:
    n = float(n or 0)
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


def _fmt_cost(t) -> str:
    """API list price of a token group: "$12.34", "$12.34+" when part of it has no known price, "-" when none."""
    if not t or not t.get("requests"):
        return "-"
    if t.get("cost", 0) <= 0 and t.get("unpriced"):
        return "-"
    return f"${t['cost']:,.2f}" + ("+" if t.get("unpriced") else "")


def _report_data(provider: str, hours: float) -> dict:
    """Load per account from the usage history. Keys: snapshots, span_h, start, accounts (label, used,
    share, peak, hot_min; heaviest first), total, busiest [(hour, used)], full_min, advice."""
    since_ts = time.time() - hours * 3600
    hist = _read_history(provider, since_ts)
    rows, counting = _token_rows(provider)
    tokens = {k: t for k, t in _token_group(provider, rows, since_ts).items() if t["requests"]}
    tokens_total = _token_group(provider, rows, since_ts, by="all").get("all") or _empty_tokens()

    def ranked(by):
        return [dict(t, name=k) for k, t in sorted(_token_group(provider, rows, since_ts, by=by).items(),
                                                     key=lambda kv: -kv[1]["total"])]
    out = {"hours": hours, "snapshots": len(hist), "window": _window(provider), "accounts": [], "total": 0.0,
           "busiest": [], "full_min": 0.0, "span_h": 0.0, "start": None, "advice": "",
           "tokens_total": tokens_total, "tokens_since": counting,
           "by_profile": ranked("profile"), "by_model": ranked("model")}
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


# ── when every account will be at the threshold, at the last hour's pace ─────

def _forecast(provider: str, now: float = None, threshold: float = 90) -> dict:
    """Forecast from the balance timer's history; no provider call.

    Pace = the usage-window percent the pool used in the last hour (sum of every account's increases).
    The simulation spends it minute by minute on the least-used account below the threshold (what balance
    and fill_first do), resets an account when its window resets, and stops when none is left below the
    threshold or after one window length. Assumes accounts of the same plan, so percents add up.
    Keys: status (no-data / idle / ok), pace (percent of one window per hour), full_at, back_at,
    horizon_h, accounts, threshold, text."""
    now = now or time.time()
    win_s = getattr(providers.get(provider), "window_seconds", None) or 5 * 3600
    out = {"status": "no-data", "pace": 0.0, "full_at": None, "back_at": None, "horizon_h": win_s / 3600,
           "accounts": 0, "threshold": threshold, "text": "Not enough usage history for a forecast yet."}
    if not _has_usage(provider):
        out["text"] = _no_usage_text(provider)
        return out
    hist = _read_history(provider, now - 3600 - 600, tail=400_000)
    if len(hist) < 3 or now - hist[-1]["ts"] > 1200 or hist[-1]["ts"] - hist[0]["ts"] < 1500:
        return out
    series = defaultdict(list)
    for rec in hist:
        for label, util in (rec.get("usage") or {}).items():
            series[label].append((rec["ts"], float(util)))
    burn = 0.0
    for pts in series.values():
        for (t1, u1), (t2, u2) in zip(pts, pts[1:]):
            if t2 - t1 <= 1200 and u2 > u1:
                burn += u2 - u1
    minutes = (hist[-1]["ts"] - hist[0]["ts"]) / 60
    rate = burn / minutes                                   # percent of one window per minute, whole pool
    last = hist[-1]
    accs = []
    for e in _entries(provider):
        if getattr(e, "last_status", None) == "dead" or e.label not in (last.get("usage") or {}):
            continue
        u, reset = float(last["usage"][e.label]), (last.get("reset") or {}).get(e.label)
        if reset and reset <= now:
            u, reset = 0.0, reset + win_s
        accs.append([u, reset or now + win_s])
    out.update(status="idle" if rate <= 0 else "ok", pace=round(rate * 60, 1), accounts=len(accs))
    w = _window(provider)
    if not accs:
        out.update(status="no-data", text="No account in rotation with a known usage.")
        return out
    if rate <= 0:
        out["text"] = "No load in the last hour."
        return out
    pace = f"At the last hour's pace ({rate * 60:.0f}% of one {w} window per hour)"
    for m in range(1, int(win_s // 60) + 1):
        t = now + m * 60
        for a in accs:
            if a[1] <= t:
                a[0], a[1] = 0.0, a[1] + win_s
        usable = [a for a in accs if a[0] < threshold]
        if not usable:
            back = min(a[1] for a in accs)
            out.update(full_at=t, back_at=back,
                       text=f"{pace}, every account is at {threshold:.0f}% or more around {_hhmm(t)}, "
                            f"until about {_hhmm(back)} when the first one resets.")
            return out
        min(usable, key=lambda a: a[0])[0] += rate
    out["text"] = f"{pace}, the {len(accs)} accounts last beyond the next {win_s / 3600:.0f} hours."
    return out


def _chart_data(provider: str, days: int = 7) -> dict:
    """Load per local hour for the last `days` days (today last): quota used (sum of usage-window percent
    increases, from the balance timer's history) and tokens through Hermes (from the session tracker)."""
    import bisect
    now = time.time()
    lt = time.localtime(now)
    starts = [time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - d, 0, 0, 0, 0, 0, -1)) for d in range(days - 1, -1, -1)]
    used = [[0.0] * 24 for _ in starts]
    tok = [[0] * 24 for _ in starts]
    req = [[0] * 24 for _ in starts]

    def cell(ts):
        i = bisect.bisect_right(starts, ts) - 1
        return (i, time.localtime(ts).tm_hour) if 0 <= i < len(starts) and ts <= now + 60 else (None, None)

    series = defaultdict(list)
    for rec in _read_history(provider, starts[0] - 1200):
        for label, util in (rec.get("usage") or {}).items():
            series[label].append((rec["ts"], float(util)))
    for pts in series.values():
        for (t1, u1), (t2, u2) in zip(pts, pts[1:]):
            if t2 - t1 <= 1200 and u2 > u1:
                i, hr = cell(t2)
                if i is not None:
                    used[i][hr] += u2 - u1
    rows, _ = _token_rows(provider)
    for _label, _profile, _model, start, v in rows:
        i, hr = cell(start)
        if i is not None:
            tok[i][hr] += sum(v[:4])
            req[i][hr] += v[4]
    return {"window": _window(provider), "has_usage": _has_usage(provider), "days": [
        {"start": st, "date": time.strftime("%m-%d", time.localtime(st)), "dow": time.strftime("%a", time.localtime(st)),
         "used": [round(x, 1) for x in used[i]], "tokens": tok[i], "requests": req[i]}
        for i, st in enumerate(starts)]}


def _print_chart(provider: str) -> None:
    data = _chart_data(provider)
    shades = "░▒▓█"
    blocks = [("used", f"quota used ({data['window']}-window percent)")] if data["has_usage"] else []
    blocks.append(("tokens", "tokens through Hermes"))
    for key, title in blocks:
        top = max((x for d in data["days"] for x in d[key]), default=0)
        _p(f"  Load by hour, last {len(data['days'])} days: {title}. "
           + (f"Darkest = {_fmt_tokens(top) if key == 'tokens' else f'{top:.0f}'} in one hour." if top else "None yet."))
        _p(f"  {'':10s} " + " ".join(f"{h:02d}" for h in range(0, 24, 3)))
        for d in data["days"]:
            line = "".join("·" if not x else shades[min(3, int(x / top * 4)) if top else 0] for x in d[key])
            _p(f"  {d['dow']} {d['date']}  {line}")


def _cmd_report(args) -> int:
    provider = _norm(args.provider)
    hours = float(args.hours or 24)
    if getattr(args, "chart", False):
        _p(f"[{provider}] load by hour (local time; one row per day, one column per hour)")
        _print_chart(provider)
        return 0
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
    _p(f"  {'account':34s} {'used':>6s} {'share':>6s} {'peak':>5s}  {'time >= 90%':>11s}  {'tokens':>8s} {'API $':>9s}")
    for a in data["accounts"]:
        tok = _fmt_tokens(a["tokens"]["total"]) if a.get("tokens") else "-"
        _p(f"  {a['label']:34s} {a['used']:6.0f} {a['share']:5.0f}% {a['peak']:4.0f}%  {a['hot_min']:8.0f} min  {tok:>7s} "
           f"{_fmt_cost(a.get('tokens')):>9s}")
    tt = data["tokens_total"]
    _p(f"  {'total':34s} {data['total']:6.0f}{'':29s}{_fmt_tokens(tt['total']) if tt['requests'] else '-':>7s} "
       f"{_fmt_cost(tt):>9s}")
    if tt["requests"]:
        since = data.get("tokens_since")
        _p(f"  Tokens through Hermes: {_fmt_tokens(tt['input'])} input, {_fmt_tokens(tt['output'])} output, "
           f"{_fmt_tokens(tt['cache_read'])} cache read, {_fmt_tokens(tt['cache_write'])} cache write")
        _p(f"  {tt['requests']} requests"
           + (f", counted since {time.strftime('%m-%d %H:%M', time.localtime(since))}." if since and since > data['start'] else "."))
        _p("  API $ = these tokens at the provider's API list prices (a subscription is billed flat)."
           + (" '+': some tokens have no known price." if tt.get("unpriced") else ""))
        for key, title in (("by_profile", "By profile (bot)"), ("by_model", "By model")):
            groups = [g for g in data[key] if g["requests"]]
            if not groups:
                continue
            _p(f"  {title:32s} {'tokens':>7s} {'requests':>9s} {'API $':>9s} {'share':>6s}")
            for g in groups:
                name = "(older tracker, no name)" if g["name"] == "?" else g["name"]
                share = g["total"] / tt["total"] * 100 if tt["total"] else 0
                _p(f"    {name:30s} {_fmt_tokens(g['total']):>7s} {g['requests']:>9d} {_fmt_cost(g):>9s} {share:5.0f}%")
    else:
        _p("  Tokens: none counted yet. The session tracker counts them from version 1.1.0 on.")
    if data["busiest"]:
        _p("  Busiest hours: " + ", ".join(f"{h:02d}:00-{(h + 1) % 24:02d}:00 ({v:.0f})" for h, v in data["busiest"]))
    _p(f"  Time with EVERY account >= 90%: {data['full_min']:.0f} min")
    fc = _forecast(provider)
    if fc["status"] != "no-data":
        _p(f"  Forecast: {fc['text']}")
    if data["advice"]:
        _p(("  (" + data["advice"] + ")") if data["advice"].startswith("Too little") else "  -> " + data["advice"])
    _p(f"  Load by hour for the last 7 days: hermes account {provider} report --chart")
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


# ── tokens per session (task) ───────────────────────────────────────────────

def _session_rows(provider: str) -> tuple:
    """([(profile, session, model, bucket start, [in, out, cache read, cache write, requests])], counted since)
    from the tracker's per-session buckets (tracker 1.5.0 and later)."""
    data = _load_json(_root() / "account-pool-tokens.json", {}) or {}
    out = []
    for profile, sessions in ((data.get("sessions") or {}).get(provider) or {}).items():
        for sid, models in (sessions or {}).items():
            for model, slots in (models or {}).items():
                for slot, v in (slots or {}).items():
                    try:
                        out.append((profile, sid, model, int(slot), [int(x) for x in v[:5]]))
                    except (TypeError, ValueError):
                        continue
    return out, data.get("sessions_since")


def _session_meta(keys) -> dict:
    """{(profile, session): {title, source, started, ended}} from each profile's Hermes session database
    (state.db, read-only). Missing databases or rows are skipped."""
    import sqlite3
    homes = dict(_profile_homes())
    wanted = defaultdict(set)
    for profile, sid in keys:
        wanted[profile].add(sid)
    out = {}
    for profile, ids in wanted.items():
        db = homes.get(profile, _root() / "profiles" / profile) / "state.db"
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            try:
                ids = sorted(ids)
                for i in range(0, len(ids), 500):
                    part = ids[i:i + 500]
                    q = f"select id, source, title, started_at, ended_at from sessions where id in ({','.join('?' * len(part))})"
                    for sid, source, title, started, ended in con.execute(q, part):
                        out[(profile, sid)] = {"title": title, "source": source, "started": started, "ended": ended}
            finally:
                con.close()
        except Exception:
            continue
    return out


def _sessions_data(provider: str, hours: float, top: int = 15) -> dict:
    """The sessions with the most tokens in the last `hours`, by API price then tokens. Each: profile, session,
    title, source, platform, task, accounts, models, tokens (as in _token_group), first and last bucket."""
    now = time.time()
    since = now - hours * 3600
    rows, counted = _session_rows(provider)
    groups = {}
    for profile, sid, model, start, v in rows:
        if start < since:
            continue
        g = groups.setdefault((profile, sid), {"v": [0, 0, 0, 0, 0], "cost": 0.0, "unpriced": 0,
                                                "models": defaultdict(int), "first": start, "last": start})
        for i in range(5):
            g["v"][i] += v[i]
        price = _model_price(provider, model)
        if price:
            g["cost"] += sum(v[i] * price[i] for i in range(4)) / 1e6
        else:
            g["unpriced"] += sum(v[:4])
        g["models"][model] += sum(v[:4])
        g["first"], g["last"] = min(g["first"], start), max(g["last"], start)
    total = dict(dict.fromkeys(TOKEN_KEYS, 0), total=0, cost=0.0, unpriced=0)
    for g in groups.values():
        for i, k in enumerate(TOKEN_KEYS):
            total[k] += g["v"][i]
        total["total"] += sum(g["v"][:4])
        total["cost"] += g["cost"]
        total["unpriced"] += g["unpriced"]
    total["cost"] = round(total["cost"], 4)
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["cost"], -sum(kv[1]["v"][:4])))
    shown = ranked[:top]
    meta = _session_meta(k for k, _ in shown)
    recs = (_load_json(_root() / "account-pool-sessions.json", {}) or {}).get("sessions") or {}
    out = []
    for (profile, sid), g in shown:
        m = meta.get((profile, sid)) or {}
        r = recs.get(f"{profile}:{sid}") or {}
        d = dict(zip(TOKEN_KEYS, g["v"]))
        d.update(total=sum(g["v"][:4]), cost=round(g["cost"], 4), unpriced=g["unpriced"])
        out.append({
            "profile": profile, "session": sid, "title": m.get("title") or f"{m.get('source') or 'session'} {sid}",
            "named": bool(m.get("title")), "source": m.get("source") or r.get("platform") or "?",
            "platform": r.get("platform") or "", "task": r.get("task"),
            "accounts": [x for x in (r.get("previous_account"), r.get("account")) if x],
            "models": sorted(g["models"], key=lambda k: -g["models"][k]), "tokens": d,
            "first": g["first"], "last": g["last"] + TOKEN_BUCKET, "ended": m.get("ended"),
        })
    return {"hours": hours, "since": counted, "count": len(groups), "total": total, "sessions": out,
            "rest": {"count": max(0, len(groups) - len(shown)),
                     "total": sum(sum(g["v"][:4]) for _, g in ranked[top:]),
                     "cost": round(sum(g["cost"] for _, g in ranked[top:]), 4)}}


def _cmd_sessions(args) -> int:
    provider = _norm(args.provider)
    if _no_accounts(provider):
        return 0
    hours = float(args.hours or 24)
    data = _sessions_data(provider, hours)
    if not data["since"]:
        _p(f"[{provider}] no tokens per session yet. Session tracker 1.5.0 counts them from its first API call; "
           f"running bots switch to it when they restart (doctor names them).")
        return 0
    since = data["since"]
    _p(f"[{provider}] sessions by API price, last {hours:g} h ({data['count']} session{'' if data['count'] == 1 else 's'}"
       + (f"; counted per session since {time.strftime('%m-%d %H:%M', time.localtime(since))}" if since > time.time() - hours * 3600 else "")
       + ")")
    if not data["sessions"]:
        _p("  None in this period.")
        return 0
    _p(f"  {'profile':20s} {'source':8s} {'tokens':>7s} {'requests':>8s} {'API $':>9s}  title")
    for r in data["sessions"]:
        t = r["tokens"]
        title = r["title"] if len(r["title"]) <= 60 else r["title"][:59] + "…"
        _p(f"  {r['profile'][:20]:20s} {r['source'][:8]:8s} {_fmt_tokens(t['total']):>7s} {t['requests']:>8d} "
           f"{_fmt_cost(t):>9s}  {title}" + (f" ({r['task']})" if r.get("task") else ""))
    rest = data["rest"]
    if rest["count"]:
        _p(f"  {rest['count']} more: {_fmt_tokens(rest['total'])} tokens, ${rest['cost']:,.2f}.")
    tt = data["total"]
    _p(f"  Total: {_fmt_tokens(tt['total'])} tokens in {tt['requests']} requests, {_fmt_cost(tt)} at API list prices.")
    _p("  Tokens count only the time in this period; the title comes from Hermes' session list.")
    return 0


def _cmd_log(args) -> int:
    provider = _norm(args.provider)
    hours = float(args.hours or 24)
    recs = _read_activity(provider, time.time() - hours * 3600)
    _p(f"[{provider}] activity, last {hours:g} h: {len(recs)} event{'' if len(recs) == 1 else 's'}"
       + (" (newest last)" if recs else ""))
    for r in recs[-300:]:
        _p(f"  {time.strftime('%m-%d %H:%M', time.localtime(r['ts']))}  {r.get('by', '?'):5s}  {r.get('kind', ''):10s}  {r.get('text', '')}")
    if len(recs) > 300:
        _p(f"  ({len(recs) - 300} older events not shown; use a shorter --hours)")
    if not recs:
        _p("  Nothing recorded. Balance changes, park, unpark, schedules, strategy and alert settings are logged.")
    return 0


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
        ab = cfg["alert_bot"]
        _p(f"  bot alerts: {'on' if ab.get('on') else 'off'}"
           + (f" (a bot's last hour >= ${float(ab.get('usd', 15)):g} at API prices or >= {ab.get('requests', 300)} requests, "
              f"and {float(ab.get('factor', 3)):g}x its usual hour; twice the floor until it has 3 active hours; "
              f"once per bot per {float(ab.get('cooldown_h', 6)):g} h)" if ab.get("on") else ""))
        at = _daily_at(cfg)
        last = (_load_json(_state_path(), {}) or {}).get(f"daily:{_norm(args.provider)}")
        _p(f"  daily summary: {f'{at[0]:02d}:{at[1]:02d}, the first balance run after it' if at else 'off'}"
           + (f" (last sent {last})" if at and last else ""))
        _p(f"Settings: {_config_path()}  (created with defaults on first change)")
        _p("Change: hermes account <provider> notify desktop-on|desktop-off|telegram-on|telegram-off")
        _p("        hermes account <provider> notify telegram-via=<profile>   (which bot sends)")
        _p("        hermes account <provider> notify daily=08:00|daily-off|summary   (summary: send it now)")
        _p("        hermes account <provider> notify bots-on|bots-off|bots=<USD per hour>")
        return 0
    if sub == "test":
        sent = _notify("Hermes account-pool: test", "Alerts from `hermes account` reach this channel.")
        _p(f"Test alert delivered to: {', '.join(sent) or 'no channel'}")
        return 0 if sent else 1
    if sub == "summary":
        title, body = _summary(_norm(args.provider))
        sent = _notify(title, body, icon="dialog-information")
        _p(title)
        _p(body)
        _p(f"Delivered to: {', '.join(sent) or 'no channel'}")
        return 0 if sent else 1
    if sub.startswith("daily=") or sub == "daily-off":
        user = _load_json(_config_path(), {})
        if sub == "daily-off":
            user.setdefault("notify", {})["daily"] = None
            _atomic_json(_config_path(), user)
            _p("Daily summary off.")
            return 0
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", sub.split("=", 1)[1].strip())
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            _p("daily= takes a time of day, e.g. daily=08:00")
            return 2
        at = f"{int(m[1]):02d}:{int(m[2]):02d}"
        user.setdefault("notify", {})["daily"] = at
        _atomic_json(_config_path(), user)
        now = datetime.now()
        if (now.hour, now.minute) >= (int(m[1]), int(m[2])):     # past today's time: start tomorrow
            state = _load_json(_state_path(), {}) or {}
            for p in set(_pool_providers()) | {_norm(args.provider)}:
                state[f"daily:{p}"] = now.strftime("%Y-%m-%d")
            _atomic_json(_state_path(), state)
        _p(f"Daily summary on: at {at}, sent by the first balance run after it"
           + (", first one tomorrow." if (now.hour, now.minute) >= (int(m[1]), int(m[2])) else ", first one today."))
        _p(f"Preview it now: hermes account {_norm(args.provider)} notify summary")
        if not _timer_active():
            _p("WARNING: the balance timer is not active, so no summary will be sent.")
        return 0
    if sub in ("bots-on", "bots-off") or sub.startswith("bots="):
        user = _load_json(_config_path(), {})
        ab = user.setdefault("alert_bot", {})
        if sub.startswith("bots="):
            m = re.fullmatch(r"\$?(\d+(?:\.\d+)?)", sub.split("=", 1)[1].strip())
            if not m or not 0 < float(m[1]) <= 10000:
                _p("bots= takes US dollars per hour at API prices, e.g. bots=15")
                return 2
            ab.update(on=True, usd=float(m[1]))
        else:
            ab["on"] = sub == "bots-on"
        _atomic_json(_config_path(), user)
        cur = _config()["alert_bot"]
        _p(f"Bot alerts on: when a bot's last hour reaches ${float(cur['usd']):g} at API prices or {cur['requests']} requests, "
           f"and {float(cur['factor']):g}x its usual hour." if cur["on"] else "Bot alerts off.")
        return 0
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
        _p("notify accepts: status, test, summary, desktop-on, desktop-off, telegram-on, telegram-off, "
           "telegram-via=<profile>, daily=<HH:MM>, daily-off, bots-on, bots-off, bots=<USD per hour>")
        return 2
    user = _load_json(_config_path(), {})
    key, val = toggles[sub]
    user.setdefault("notify", {})[key] = val
    _atomic_json(_config_path(), user)
    _p(f"{key} alerts {'on' if val else 'off'}.")
    return 0


def _schedule_rows(provider: str) -> list[dict]:
    """Park schedules with their state now: in_window, parked (by the schedule or by hand), next start."""
    now = time.time()
    labels = {e.label.lower() for e in _entries(provider)}
    parked = {(p.get("label") or "").lower(): p for p in _read_parked() if p["_provider"] == provider}
    out = []
    for s in _schedules(provider):
        win = _schedule_window(s, now)
        nxt = _schedule_window(s, now, ahead=True)
        p = parked.get(s["label"].lower())
        out.append({"label": s["label"], "id": s.get("id"), "every": _every_text(s), "days": s.get("days"),
                    "from": s.get("from"), "to": s.get("to"), "in_window": bool(win), "end": win[1] if win else None,
                    "next": nxt[0] if nxt else None, "found": s["label"].lower() in labels or p is not None,
                    "parked": bool(p), "parked_by_schedule": bool(p and p.get("_by") == "schedule"),
                    "until": p.get("_until") if p else None})
    return out


def _cmd_schedule(args) -> int:
    provider = _norm(args.provider)
    every = getattr(args, "every", None)
    if not args.target:
        if every:
            _p(f"Which account? Usage: hermes account {provider} schedule <target> --every \"mon-fri 09:00-17:00\"")
            return 2
        rows = _schedule_rows(provider)
        if not rows:
            _p(f"[{provider}] no park schedules. Add one: "
               f"hermes account {provider} schedule <target> --every \"mon-fri 09:00-17:00\"")
            return 0
        _p(f"[{provider}] park schedules: the balance timer parks the account when a window starts and returns it "
           f"when it ends.")
        for r in rows:
            if not r["found"]:
                state = "not in the pool"
            elif r["in_window"] and r["parked"]:
                state = f"parked now, back {_hhmm(r['until'])}" if r["until"] else "parked now (by hand, no return time)"
            elif r["in_window"]:
                state = "in its window but in rotation (unparked by hand, or parking was refused)"
            else:
                state = "next " + time.strftime("%a %m-%d %H:%M", time.localtime(r["next"])) if r["next"] else "-"
            _p(f"  {r['label']:34s} {r['every']:28s} {state}")
        _p(f"Remove: hermes account {provider} unschedule <target>")
        if not _timer_active():
            _p("WARNING: the balance timer is not active, so schedules are not applied.")
        return 0
    if not every:
        _p(f"Add --every, e.g. hermes account {provider} schedule {args.target} --every \"mon-fri 09:00-17:00\". "
           f"Remove a schedule: hermes account {provider} unschedule {args.target}")
        return 2
    spec = _parse_every(every)
    pool = _pool(provider)
    index, matched, error = pool.resolve_target(args.target)
    if matched is None:
        item = _find_parked(provider, args.target)
        if not item:
            raise SystemExit(f"{error} See: hermes account {provider} list")
        label, cid = item.get("label"), item.get("id")
    else:
        label, cid = matched.label, matched.id
    user = _load_json(_config_path(), {})
    mine = [s for s in ((user.get("schedules") or {}).get(provider) or []) if (s.get("label") or "").lower() != label.lower()]
    mine.append(dict(spec, label=label, id=cid))
    user.setdefault("schedules", {})[provider] = mine
    _atomic_json(_config_path(), user)
    s = mine[-1]
    _p(f"Schedule saved [{provider}]: {label} is parked {_every_text(s)}.")
    if _schedule_window(s, time.time()):
        _p("The current window has started: the next balance run (within 5 minutes) parks it.")
    else:
        nxt = _schedule_window(s, time.time(), ahead=True)
        if nxt:
            _p(f"Next: {time.strftime('%a %m-%d %H:%M', time.localtime(nxt[0]))}.")
    _p("Unparking it by hand inside a window keeps it in rotation until the next window.")
    if not _timer_active():
        _p("WARNING: the balance timer is not active, so the schedule will NOT be applied.")
    _p(f"Undo: hermes account {provider} unschedule {label}")
    return 0


def _cmd_unschedule(args) -> int:
    provider = _norm(args.provider)
    raw = str(args.target).strip().lower()
    user = _load_json(_config_path(), {})
    mine = (user.get("schedules") or {}).get(provider) or []
    hits = [s for s in mine if (s.get("label") or "").lower() == raw or (s.get("id") or "").lower() == raw]
    if not hits:
        names = ", ".join(s.get("label", "?") for s in mine) or "(none)"
        raise SystemExit(f'No park schedule for "{args.target}". Schedules: {names}')
    user["schedules"][provider] = [s for s in mine if s not in hits]
    _atomic_json(_config_path(), user)
    label = hits[0].get("label")
    _p(f"Schedule removed [{provider}]: {label}.")
    p = _find_parked(provider, label)
    if p and p.get("_by") == "schedule":
        _p(f"It stays parked until {_hhmm(p.get('_until'))}. Return it now: hermes account {provider} unpark {label}")
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


def _tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _confirm(question: str, yes: bool) -> bool:
    """yes/no prompt. Without a terminal (cron, the gateway, an agent's shell) it answers no at once
    instead of waiting for input nobody can give."""
    if yes:
        return True
    if not _tty():
        _p(f"{question} [y/N] no terminal to answer, so no. Add --yes to confirm without a prompt.")
        return False
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
    _log(provider, "add", f"Added {label}.")
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
    method = "key" if use_key else _signin_method(provider, args)
    if _signin_needs_tty(provider, "add", label, key=use_key, method=method):
        return 1
    verify = providers.get(provider).has_identity and not use_key
    _p(f"Add {label} to {provider}")
    if use_key:
        _p("  You will be asked for the API key (input is hidden).")
    else:
        _signin_steps(provider, label, method)
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
        cmd = ([_hermes_bin(), "auth", "add", provider, "--type", "api-key", "--label", label] if use_key
               else _signin_cmd(provider, label, method))
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


# ── setup: what a plugin install leaves out ─────────────────────────────────

UNIT_NAME = "hermes-account-balance"


def _unit_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def _systemctl(*args: str) -> None:
    """`systemctl --user <args>`; RuntimeError with its message on failure."""
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"systemctl --user {' '.join(args)}: exit {r.returncode}")


def _run_hermes(profile: str, *args: str) -> None:
    """`hermes [-p <profile>] <args>` against the shared root; RuntimeError with its last line on failure."""
    cmd = [_hermes_bin()] + ([] if profile == "default" else ["-p", profile]) + list(args)
    r = subprocess.run(cmd, env=_hermes_env(), capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if r.returncode:
        lines = [ln for ln in (r.stderr + "\n" + r.stdout).splitlines() if ln.strip()]
        raise RuntimeError(lines[-1] if lines else f"exit code {r.returncode}")


def _plugin_lists(home: Path) -> tuple:
    """(plugins.enabled, plugins.disabled) of one profile's config.yaml."""
    import yaml
    try:
        cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
    except Exception:
        cfg = {}
    plugins = cfg.get("plugins") if isinstance(cfg, dict) else None
    plugins = plugins if isinstance(plugins, dict) else {}

    def names(v):
        return [str(x) for x in v] if isinstance(v, list) else []
    return names(plugins.get("enabled")), names(plugins.get("disabled"))


def _set_enabled(home: Path, name: str, on: bool) -> None:
    """Add or remove one name in plugins.enabled, read fresh so another change in between is kept."""
    enabled = _plugin_lists(home)[0]
    new = (enabled + [name]) if on else [n for n in enabled if n != name]
    if new != enabled:
        _set_config_value(home, "plugins.enabled", json.dumps(new))


def _timer_lines() -> dict:
    """{provider: its ExecStart line} of the installed balance service, in order (empty without the unit file).
    Lines are kept as written, so options added by hand (--threshold 85) survive a rewrite."""
    try:
        text = (_unit_dir() / f"{UNIT_NAME}.service").read_text()
    except OSError:
        return {}
    return {m.group(1): m.group(0) for m in re.finditer(r"^ExecStart=.*?\baccount\s+(\S+)\s+balance\b.*$", text, re.M)}


def _timer_providers() -> list:
    return list(_timer_lines())


def _write_timer(provs: list) -> None:
    """Write the balance service (one ExecStart per provider, run in order) and, when missing, its 5-minute
    timer. An existing timer file is left alone (its interval may have been changed by hand)."""
    d = _unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    root = _root()
    keep = _timer_lines()
    env = "" if root.resolve() == (Path.home() / ".hermes").resolve() else f"Environment=HERMES_HOME={root}\n"
    execs = "".join((keep.get(p) or f"ExecStart={_hermes_bin()} account {p} balance") + "\n" for p in provs)
    (d / f"{UNIT_NAME}.service").write_text(
        f"[Unit]\nDescription=Hermes account pool: balance {' '.join(provs)} accounts by live usage\n\n"
        f"[Service]\nType=oneshot\n{env}{execs}TimeoutStartSec={120 * len(provs)}\n")
    timer = d / f"{UNIT_NAME}.timer"
    if not timer.exists():
        timer.write_text(
            "[Unit]\nDescription=Run hermes account balance every 5 minutes\n\n[Timer]\nOnBootSec=2min\n"
            "OnUnitActiveSec=5min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")


def _timer_on(provs: list) -> None:
    _write_timer(provs)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", f"{UNIT_NAME}.timer")
    _systemctl("start", "--no-block", f"{UNIT_NAME}.service")       # first run now, in the background


def _timer_drop(provider: str, provs: list) -> None:
    rest = [p for p in provs if p != provider]
    if rest:
        _write_timer(rest)
        _systemctl("daemon-reload")
        return
    try:
        _systemctl("disable", "--now", f"{UNIT_NAME}.timer")
    except RuntimeError:
        pass                                    # already off: the files still go
    for suffix in ("service", "timer"):
        (_unit_dir() / f"{UNIT_NAME}.{suffix}").unlink(missing_ok=True)
    _systemctl("daemon-reload")


def _link_tracker(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and not link.exists():  # dangling link from an older install
        link.unlink()
    link.symlink_to(target)


def _cmd_setup(args) -> int:
    """Set up what `hermes plugins install` leaves out (install.sh does the same after copying the plugins):
    the Accounts page backend and the session tracker in every profile; with --timer the balance timer,
    with --strategy fill_first. --undo takes the profile and timer parts back. Shows the plan first."""
    provider = _norm(args.provider)
    undo, want_timer, want_strategy = (bool(getattr(args, k, False)) for k in ("undo", "timer", "strategy"))
    if undo and (want_timer or want_strategy):
        _p("--undo cannot be combined with --timer or --strategy.")
        return 2
    root = _root()
    homes = _profile_homes()
    named = homes[1:]
    home_of = dict(homes)
    lists = {name: _plugin_lists(home) for name, home in homes}
    tracker = root / "plugins" / "account-pool-tracker"
    status, changes = [], []

    def change(text, fn):
        changes.append((text, fn))

    if undo:
        linked = [n for n, h in named if (h / "plugins" / "account-pool-tracker").is_symlink()
                  and (h / "plugins" / "account-pool-tracker").resolve() == tracker.resolve()]
        for n in linked:
            link = home_of[n] / "plugins" / "account-pool-tracker"
            change(f"remove the session tracker from {n} (plugins.enabled and the link {link})",
                   lambda n=n, link=link: (_set_enabled(home_of[n], "account-pool-tracker", False), link.unlink()))
        listed = [n for n, _ in named if "account-pool" in lists[n][0]]
        for n in listed:
            change(f"unlist account-pool from plugins.enabled of {n}",
                   lambda n=n: _set_enabled(home_of[n], "account-pool", False))
        provs = _timer_providers()
        if provider in provs:
            rest = [p for p in provs if p != provider]
            change(f"take {provider} out of the balance timer (it keeps running {', '.join(rest)})" if rest else
                   f"remove the balance timer ({_unit_dir()}/{UNIT_NAME}.service and .timer)",
                   lambda: _timer_drop(provider, provs))
        status.append(("Session tracker", f"linked into {len(linked)} profile(s)"))
        status.append(("Accounts page", f"listed in {len(listed)} profile(s)"))
        status.append(("Balance timer", f"runs {', '.join(provs)}" if provs else "not installed"))
    else:
        # Accounts page: Hermes Desktop mounts the backend only for profiles that list the plugin
        off = [n for n, _ in named if "account-pool" in lists[n][1]]
        unlisted = [n for n, _ in named if "account-pool" not in lists[n][0] and n not in off]
        if named:
            status.append(("Accounts page", f"backend listed in {len(named) - len(unlisted) - len(off)} of {len(named)} "
                           f"other profile(s)" + (f"; skipped, in plugins.disabled: {', '.join(off)}" if off else "")))
        for n in unlisted:
            change(f"list account-pool in plugins.enabled of {n} (Hermes Desktop serves the page's backend from there; "
                   f"the profile gets no command and no tools)", lambda n=n: _set_enabled(home_of[n], "account-pool", True))
        # session tracker: one copy in the default profile, linked into every other profile
        if not (tracker / "plugin.yaml").is_file():
            status.append(("Session tracker", "not installed, so `who`, tokens and sessions stay empty. Install it, "
                           "then run setup again: hermes plugins install account-pool-tracker"))
        else:
            ver = (re.search(r"^version:\s*['\"]?([\w.]+)", (tracker / "plugin.yaml").read_text(), re.M) or [None, "?"])[1]
            todo = 0
            if "account-pool-tracker" not in lists["default"][0]:
                todo += 1
                change("enable the session tracker in the default profile (hermes plugins enable account-pool-tracker)",
                       lambda: _run_hermes("default", "plugins", "enable", "account-pool-tracker"))
            for n, h in named:
                link = h / "plugins" / "account-pool-tracker"
                need_link = not link.exists()
                need_on = "account-pool-tracker" not in lists[n][0]
                if need_link:
                    change(f"link the session tracker into {n} ({link} -> {tracker})",
                           lambda link=link: _link_tracker(link, tracker))
                if need_on:
                    note = " (it is in plugins.disabled there now)" if "account-pool-tracker" in lists[n][1] else ""
                    change(f"enable the session tracker in {n}{note} (hermes -p {n} plugins enable account-pool-tracker)",
                           lambda n=n: _run_hermes(n, "plugins", "enable", "account-pool-tracker"))
                todo += bool(need_link or need_on)
            status.append(("Session tracker", f"{ver}, active in {len(homes) - todo} of {len(homes)} profile(s)"))
        # balance timer (opt-in: a background job every 5 minutes)
        provs, active = _timer_providers(), _timer_active()
        state = (f"runs {', '.join(provs)}, {'active' if active else 'NOT active'}" if provs else
                 "active, but not from this setup (no unit file found)" if active else "not installed")
        if want_timer and not shutil.which("systemctl"):
            status.append(("Balance timer", f"systemd not found: run `hermes account {provider} balance` every few "
                           "minutes some other way (cron)"))
        elif want_timer and provider not in provs:
            new = provs + [provider]
            change(f"{'add ' + provider + ' to' if provs else 'install'} the balance timer: systemd user units in "
                   f"{_unit_dir()}, every 5 minutes runs: {'; '.join('hermes account ' + p + ' balance' for p in new)}",
                   lambda: _timer_on(new))
        elif want_timer and not active:
            change("start the balance timer (systemctl --user enable --now)", lambda: _timer_on(provs))
        if not want_timer and provider not in provs:
            state += f"; add --timer to run `hermes account {provider} balance` every 5 minutes"
        status.append(("Balance timer", state))
        # rotation strategy: Hermes' setting, written only on request
        rows = _strategies(provider)
        bad = [n for n, v in rows if v and v.strip().lower() != "fill_first"]
        if want_strategy and bad:
            change(f"set credential_pool_strategies.{provider}: fill_first in {', '.join(bad)} (balance needs it)",
                   lambda: [_set_strategy(home_of[n], provider, "fill_first") for n in bad])
        status.append(("Rotation", f"fill_first in all {len(rows)} profile(s)" if not bad else
                       f"not fill_first in {', '.join(bad)}" + ("" if want_strategy else "; add --strategy to set it")))

    _p(f"[{provider}] {'Undo setup' if undo else 'Setup'}: the default profile and {len(named)} other profile(s) in {root}")
    for name, text in status:
        _p(f"  {name:16s} {text}")
    if not changes:
        _p("Nothing to change." + ("" if undo else f" Check the whole setup with: hermes account {provider} doctor"))
        return 0
    _p("Changes:")
    for text, _ in changes:
        _p(f"  - {text}")
    if not _confirm("Apply these changes?", getattr(args, "yes", False)):
        _p("Nothing changed.")
        return 1
    failed = 0
    for text, fn in changes:
        try:
            fn()
            _p(f"  done: {text}")
            _log(provider, "setup", text[0].upper() + text[1:] + ".")
        except Exception as x:  # noqa: BLE001  (report each step, keep going)
            failed += 1
            _p(f"  FAILED: {text}: {x}")
    if undo:
        _p("Kept: account-pool and account-pool-tracker in the default profile (remove them with "
           "`hermes plugins remove <name>`), the accounts, parked accounts, settings and data files, "
           "and credential_pool_strategies.")
        parked = [it.get("label") or it.get("id") for it in _read_parked() if it.get("_provider") == provider]
        if parked:
            _p(f"{len(parked)} {provider} account(s) are parked and stay out of rotation: {', '.join(map(str, parked))}. "
               f"Unpark them before you remove the plugin, or their logins stay in account-pool-parked.json only.")
    else:
        _p("Running sessions load the tracker after /reset; the gateway after `hermes gateway restart`; "
           "Hermes Desktop after a restart (also needed for the Accounts page in newly listed profiles).")
    return 1 if failed else 0


# ── registration ─────────────────────────────────────────────────────────────

ACTIONS = [
    ("list", "", "Accounts in rotation and parked accounts"),
    ("check", "", "Health: dead, rate-limited, wrong label, duplicate, real email"),
    ("usage", "", "Live usage per account, parked included (usage adapter needed)"),
    ("who", "[--minutes N]", "Which session is on which account (default: last 30 min)"),
    ("report", "[--hours N] [--chart]", "Load and tokens per account, bot and model; --chart: by hour, 7 days"),
    ("sessions", "[--hours N]", "The sessions (tasks) with the most tokens, with their API price"),
    ("log", "[--hours N]", "What the timer, the command and the page changed (default: 24 h)"),
    ("add", "<email> [--key] [--yes]", "Sign in a new account, verified, no duplicates (--key: API key)"),
    ("remove", "<target> [--yes]", "Delete an account's login (also works for parked accounts)"),
    ("park", "<target> [--until T]", "Take an account out of rotation; T = 17:00, +2h, 90m"),
    ("unpark", "<target>", "Return a parked account to rotation"),
    ("schedule", "[<target> --every SPEC]", 'Park on a weekly schedule; SPEC = "mon-fri 09:00-17:00"'),
    ("unschedule", "<target>", "Remove an account's park schedule"),
    ("relogin", "<target> [--device] [--yes]", "Sign an account in again, verified, same label and position"),
    ("balance", "[--dry-run] [--threshold N]", "Order by usage, bench >= N% (90), auto-recover, alerts"),
    ("strategy", "[<name>] [--only P,...]", "Hermes' rotation strategy per profile; set it (balance needs fill_first)"),
    ("doctor", "", "Check the whole setup: strategy, timer, files, pools, alerts"),
    ("setup", "[--timer] [--strategy] [--undo]", "Profiles, tracker and (--timer) the balance timer; shows the plan first"),
    ("notify", "[status|test|summary|...]", "Alert channels (desktop, Telegram) and the daily summary"),
    ("help", "", "Show this help"),
]

HELP = "\n".join([
    "Manage accounts in the Hermes credential pool.",
    "",
    "Usage:",
    "  hermes account <provider> <action> [target] [options]",
    "",
    "Actions:",
    *[f"  {a:10s} {arg:28s} {d}" for a, arg, d in ACTIONS],
    "",
    "Targets: account label (email), list number, or id. unpark accepts label or id.",
    "openai-codex add/relogin sign in through the browser on this computer; --device: with a device code.",
    "",
    "Examples:",
    "  hermes account anthropic add carol@example.com",
    "  hermes account anthropic usage",
    "  hermes account anthropic who",
    "  hermes account anthropic park alice@example.com --until 17:00",
    "  hermes account anthropic relogin bob@example.com",
    "  hermes account anthropic report --hours 72",
    "  hermes account anthropic sessions --hours 1",
    "  hermes account anthropic log",
    "  hermes account anthropic schedule alice@example.com --every \"mon-fri 09:00-17:00\"",
    "  hermes account anthropic notify daily=08:00",
    "  hermes account anthropic strategy",
    "  hermes account anthropic doctor",
    "  hermes account anthropic setup --timer",
    "  hermes account anthropic notify test",
    "",
    "Every provider in the credential pool: list, check, add, remove, park, unpark, schedule, relogin, who, sessions,",
    "  log, doctor, alerts, timed parks and refresh recovery.",
    f"Usage adapter (usage, report, forecast, balance ordering, real email): {', '.join(providers.with_usage())}.",
])


def _print_help(_args=None) -> int:
    _p(HELP)
    return 0


HANDLERS = {"add": _cmd_add, "remove": _cmd_remove, "list": _cmd_list, "check": _cmd_check, "usage": _cmd_usage, "who": _cmd_who,
            "report": _cmd_report, "park": _cmd_park, "unpark": _cmd_unpark, "relogin": _cmd_relogin,
            "balance": _cmd_balance, "doctor": _cmd_doctor, "notify": _cmd_notify, "schedule": _cmd_schedule,
            "unschedule": _cmd_unschedule, "strategy": _cmd_strategy, "sessions": _cmd_sessions, "log": _cmd_log,
            "setup": _cmd_setup}
NEEDS_TARGET = {"park", "unpark", "relogin", "add", "remove", "unschedule"}
OPTIONAL_TARGET = {"notify", "schedule", "strategy"}
OPTIONS = {"threshold": ("--threshold", {"balance"}), "dry_run": ("--dry-run", {"balance"}),
           "until": ("--until", {"park"}), "hours": ("--hours", {"report", "sessions", "log"}),
           "minutes": ("--minutes", {"who"}), "yes": ("--yes", {"relogin", "add", "remove", "strategy", "setup"}),
           "key": ("--key", {"add"}), "every": ("--every", {"schedule"}), "chart": ("--chart", {"report"}),
           "only": ("--only", {"strategy"}), "timer": ("--timer", {"setup"}), "strategy": ("--strategy", {"setup"}),
           "undo": ("--undo", {"setup"})}


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
    logged = action in LOG_LINES and args.target and not (action == "notify" and args.target.lower() in ("status", "test", "summary"))
    prev = getattr(_OUT, "rec", None)
    if logged:
        _OUT.rec = []
    try:
        return HANDLERS[action](args)
    except KeyboardInterrupt:
        _p("\nCancelled (Ctrl+C).")
        return 130
    finally:
        if logged:
            lines, _OUT.rec = _OUT.rec, prev
            for line in lines:
                if re.match(LOG_LINES[action], line):
                    _log(_norm(provider), action, line)


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
    parser.add_argument("--hours", type=float, default=None, help="report, sessions, log: period in hours (default 24)")
    parser.add_argument("--minutes", type=float, default=None, help="who: activity window (default 30)")
    parser.add_argument("--yes", action="store_true", help="add/remove/relogin/strategy/setup: skip the confirmation prompt")
    parser.add_argument("--key", action="store_true", help="add: add an API key instead of a sign-in")
    parser.add_argument("--device", action="store_true",
                        help="add/relogin (openai-codex): sign in with a device code instead of the browser")
    parser.add_argument("--every", default=None, help='schedule: days and hours, e.g. "mon-fri 09:00-17:00"')
    parser.add_argument("--chart", action="store_true", help="report: load by hour for the last 7 days")
    parser.add_argument("--only", default=None, help="strategy: only these profiles (comma-separated)")
    parser.add_argument("--timer", action="store_true", help="setup: install the balance timer (every 5 minutes)")
    parser.add_argument("--strategy", action="store_true", help="setup: set fill_first in every profile")
    parser.add_argument("--undo", action="store_true", help="setup: take the profile and timer changes back")
    parser.set_defaults(func=_dispatch)


def _in_profile() -> bool:
    """True when this process runs a named profile (HERMES_HOME=<root>/profiles/<name>)."""
    return _home().parent.name == "profiles"


def register(ctx) -> None:
    # The command lives in the default profile only. `setup` (and install.sh) also lists account-pool
    # in every profile's plugins.enabled, so Hermes Desktop mounts the Accounts page backend whichever
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
