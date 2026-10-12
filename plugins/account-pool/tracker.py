"""Session tracking for account-pool: which pool account each session uses, and the tokens it used.

account-pool registers `on_api_request` as its post_api_request hook in every profile (the `account`
command only in the default profile). Hermes does not persist the account chosen for a session, so the
hook reads the live pool of the running agent after each API call and writes:

- {profile, session, platform, model, account, since when on that account, tracker version, process id,
  Kanban task} to <hermes root>/account-pool-sessions.json. Throttled: once per session per minute, or
  immediately when the session's account changes. The version and process id let `doctor` name a process
  that still runs an older plugin after an update.
- the call's token counts (input, output, cache read, cache write, 1 request) added to a
  15-minute bucket of that account, profile and model, and of that profile, session and model, in
  <hermes root>/account-pool-tokens.json. Every call.

A call without a session id is not counted: guessing the agent could put tokens on the wrong account.
Both files are mode 600 and hold labels, ids and numbers only, never credentials. Any failure is
swallowed so the hook can never break a turn. Before 4.0 this was the separate account-pool-tracker
plugin; while a process still has that one loaded, this hook leaves the counting to it.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

VERSION = "4.0.0"                 # account-pool's version: keep in step with plugin.yaml
KEEP_SECONDS = 24 * 3600
TOKEN_BUCKET = 900                 # seconds per token bucket
TOKEN_KEEP = 8 * 24 * 3600         # token buckets older than this are dropped
_last: dict[str, tuple[str, float]] = {}
_legacy: list = [None, 0.0]        # [old tracker loaded in this process?, checked at]


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _root_and_profile() -> tuple[Path, str]:
    home = _home()
    if home.parent.name == "profiles":
        return home.parent.parent, home.name
    return home, "default"


def _find_agent(session_id: str):
    """Find the AIAgent for this session, or None.

    Hooks run on a helper thread while the calling turn waits, so the agent is
    on another thread's stack: scan every thread's frames for a local `agent`
    (or `self`) with a credential pool and this session id. Without a session id
    there is nothing to match, and any other agent found could be on another
    account, so the call is not counted.
    """
    import sys
    if not session_id:
        return None
    for frame in sys._current_frames().values():
        depth = 0
        while frame is not None and depth < 60:
            for name in ("agent", "self"):
                obj = frame.f_locals.get(name)
                if (obj is not None and hasattr(obj, "_credential_pool")
                        and getattr(obj, "session_id", None) == session_id):
                    return obj
            frame = frame.f_back
            depth += 1
    return None


def _legacy_tracker_loaded() -> bool:
    """True while this process also runs the old account-pool-tracker plugin (1.x): it counts the same
    calls, so this hook stays out of the way until that process restarts. Checked once a minute."""
    import sys
    now = time.time()
    if _legacy[0] is None or now - _legacy[1] > 60:
        found = False
        for mod in list(sys.modules.values()):
            path = str(getattr(mod, "__file__", "") or "").replace("\\", "/")
            if path.endswith("account-pool-tracker/__init__.py") and str(getattr(mod, "VERSION", "")).startswith("1."):
                found = True
                break
        _legacy[0], _legacy[1] = found, now
    return bool(_legacy[0])


@contextmanager
def _locked(path: Path, timeout: float = 30):
    """An exclusive lock between processes: flock on Linux and macOS, a byte lock (msvcrt) on Windows."""
    with open(path, "a+b") as fh:
        if os.name != "nt":
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield
            return
        import msvcrt
        deadline = time.monotonic() + timeout
        while True:
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def _replace(src: Path, dst: Path) -> None:
    """os.replace; on Windows a file another process has open cannot be replaced for that moment."""
    for attempt in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 39:
                raise
            time.sleep(0.05)


def _write(root: Path, key: str, record: dict) -> None:
    path = root / "account-pool-sessions.json"
    with _locked(root / "account-pool-sessions.lock"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"version": 1, "sessions": {}}
        sessions = data.setdefault("sessions", {})
        prev = sessions.get(key) or {}
        record["first_seen"] = prev.get("first_seen", record["last_seen"])
        moved = bool(prev.get("account")) and prev.get("account") != record["account"]
        if moved:
            record["previous_account"] = prev["account"]
        elif prev.get("previous_account"):
            record["previous_account"] = prev["previous_account"]
        # When the session started on its current account. Unknown for a session that moved
        # before tracker 1.2.0 recorded this.
        if moved:
            record["account_since"] = record["last_seen"]
        elif "account_since" in prev:
            record["account_since"] = prev["account_since"]
        elif not prev.get("previous_account"):
            record["account_since"] = record["first_seen"]
        if "task" not in record and prev.get("task"):
            record["task"] = prev["task"]          # a session belongs to one Kanban task
        sessions[key] = record
        cutoff = time.time() - KEEP_SECONDS
        data["sessions"] = {k: v for k, v in sessions.items() if v.get("last_seen", 0) >= cutoff}
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            json.dump(data, fh, indent=1)
        _replace(tmp, path)


def _replace_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, separators=(",", ":"))
    _replace(tmp, path)


def _upgrade_tokens(data, now: float) -> dict:
    """Bring the token file to version 2. Buckets written by tracker 1.1.0 (top-level "buckets": no
    profile, no model) are folded in under profile "?" and model "?"; a 1.1.0 tracker still running
    in another process can add such buckets again until it restarts, so this runs on every write."""
    if not isinstance(data, dict) or data.get("version") != 2:
        old = data if isinstance(data, dict) else {}
        data = {"version": 2, "bucket": TOKEN_BUCKET, "since": old.get("since") or now, "counts": {},
                "buckets": old.get("buckets") or {}}
    counts = data.setdefault("counts", {})
    for prov, labels in (data.pop("buckets", None) or {}).items():
        for label, slots in (labels or {}).items():
            dest = counts.setdefault(prov, {}).setdefault(label, {}).setdefault("?", {}).setdefault("?", {})
            for slot, v in (slots or {}).items():
                row = dest.setdefault(slot, [0, 0, 0, 0, 0])
                for i in range(5):
                    row[i] += int(v[i]) if i < len(v) else 0
    return data


def _prune(node: dict, cutoff: float, depth: int = 0) -> None:
    """Drop buckets older than `cutoff` and the levels they leave empty (counts: provider > label > profile >
    model; sessions: provider > profile > session > model)."""
    if depth == 4:
        for k in list(node):
            try:
                if int(k) < cutoff:
                    del node[k]
            except ValueError:
                del node[k]
        return
    for k in list(node):
        if isinstance(node[k], dict):
            _prune(node[k], cutoff, depth + 1)
        if not node[k]:
            del node[k]


def _add_tokens(root: Path, provider: str, label: str, profile: str, model: str, usage, now: float,
                session: str = "") -> None:
    """Add one call's tokens: counts[provider][label][profile][model][bucket start] = [in, out, cache read,
    cache write, calls], and the same per session: sessions[provider][profile][session][model][bucket start]."""
    if not isinstance(usage, dict) or not provider or not label:
        return
    vals = []
    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        try:
            vals.append(int(usage.get(k) or 0))
        except (TypeError, ValueError):
            vals.append(0)
    if not any(vals):
        return
    path = root / "account-pool-tokens.json"
    with _locked(root / "account-pool-tokens.lock"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"version": 2, "bucket": TOKEN_BUCKET, "since": now, "counts": {}}
        data = _upgrade_tokens(data, now)
        slot = str(int(now // TOKEN_BUCKET * TOKEN_BUCKET))
        row = (data["counts"].setdefault(provider, {}).setdefault(label, {}).setdefault(profile or "?", {})
               .setdefault(model or "?", {}).setdefault(slot, [0, 0, 0, 0, 0]))
        rows = [row]
        if session:
            data.setdefault("sessions_since", now)
            rows.append(data.setdefault("sessions", {}).setdefault(provider, {}).setdefault(profile or "?", {})
                        .setdefault(session, {}).setdefault(model or "?", {}).setdefault(slot, [0, 0, 0, 0, 0]))
        for r in rows:
            for i, v in enumerate(vals):
                r[i] += v
            r[4] += 1
        _prune(data["counts"], now - TOKEN_KEEP)
        _prune(data.get("sessions") or {}, now - TOKEN_KEEP)
        _replace_json(path, data)


def on_api_request(**kw) -> None:
    """account-pool's post_api_request hook."""
    try:
        session_id = str(kw.get("session_id") or "")
        if not session_id or _legacy_tracker_loaded():
            return
        agent = _find_agent(session_id)
        pool = getattr(agent, "_credential_pool", None) if agent is not None else None
        if pool is None:
            return
        entry = pool.current()
        if entry is None:
            return
        root, profile = _root_and_profile()
        key = f"{profile}:{session_id}"
        label = entry.label or entry.id
        now = time.time()
        pool_provider = getattr(pool, "provider", "") or ""
        call_provider = kw.get("provider") or ""
        # A call that went to another provider (a fallback) did not use this pool's account.
        if pool_provider and (not call_provider or call_provider == pool_provider):
            try:
                model = str(kw.get("model") or getattr(agent, "model", "") or "?").split("/")[-1]
                _add_tokens(root, pool_provider, label, profile, model, kw.get("usage"), now, session_id)
            except Exception:
                pass
        prev = _last.get(key)
        if prev and prev[0] == label and now - prev[1] < 60:
            return
        _last[key] = (label, now)
        record = {
            "profile": profile,
            "session_id": session_id,
            "platform": kw.get("platform") or getattr(agent, "platform", "") or "",
            "model": kw.get("model") or getattr(agent, "model", "") or "",
            "provider": kw.get("provider") or getattr(pool, "provider", "") or "",
            "account": label,
            "account_id": entry.id,
            "last_seen": now,
            "tracker": VERSION,
            "pid": os.getpid(),
        }
        task = os.environ.get("HERMES_KANBAN_TASK")
        if task:
            record["task"] = task
        _write(root, key, record)
    except Exception:
        pass

