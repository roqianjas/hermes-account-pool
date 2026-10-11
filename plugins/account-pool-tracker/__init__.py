"""Record which credential-pool account each session is using, and how many tokens each account used.

Companion to the `account-pool` plugin (`hermes account <provider> who`, `report`, the Accounts page).
Hermes does not persist the account chosen for a session, so this hook reads
the live pool from the running agent after each API call and writes:

- {profile, session, platform, model, account, since when on that account, tracker version, process id,
  Kanban task} to <hermes root>/account-pool-sessions.json. Throttled: once per session per minute, or
  immediately when the session's account changes. The version and process id let `doctor` name a process
  that still runs an older tracker after an update.
- the call's token counts (input, output, cache read, cache write, 1 request) added to a
  15-minute bucket of that account, profile and model in <hermes root>/account-pool-tokens.json.
  Every call.

Both files are mode 600 and hold labels, ids and numbers only, never credentials.
Any failure is swallowed so the hook can never break a turn.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

VERSION = "1.4.0"                 # keep in step with plugin.yaml
KEEP_SECONDS = 24 * 3600
TOKEN_BUCKET = 900                 # seconds per token bucket
TOKEN_KEEP = 8 * 24 * 3600         # token buckets older than this are dropped
_last: dict[str, tuple[str, float]] = {}


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
    """Find the AIAgent for this session.

    Hooks run on a helper thread while the calling turn waits, so the agent is
    on another thread's stack: scan every thread's frames for a local `agent`
    (or `self`) with a credential pool and the matching session id.
    """
    import sys
    fallback = None
    for frame in sys._current_frames().values():
        depth = 0
        while frame is not None and depth < 60:
            for name in ("agent", "self"):
                obj = frame.f_locals.get(name)
                if obj is not None and hasattr(obj, "_credential_pool") and hasattr(obj, "session_id"):
                    if session_id and getattr(obj, "session_id", None) == session_id:
                        return obj
                    fallback = fallback or obj
            frame = frame.f_back
            depth += 1
    return fallback if not session_id else None


def _write(root: Path, key: str, record: dict) -> None:
    import fcntl
    path = root / "account-pool-sessions.json"
    with open(root / "account-pool-sessions.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
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
        sessions[key] = record
        cutoff = time.time() - KEEP_SECONDS
        data["sessions"] = {k: v for k, v in sessions.items() if v.get("last_seen", 0) >= cutoff}
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)


def _replace_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    os.replace(tmp, path)


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
    """Drop buckets older than `cutoff` and the levels they leave empty (provider > label > profile > model)."""
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


def _add_tokens(root: Path, provider: str, label: str, profile: str, model: str, usage, now: float) -> None:
    """Add one call's tokens: counts[provider][label][profile][model][bucket start] = [in, out, cache read,
    cache write, calls]."""
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
    import fcntl
    path = root / "account-pool-tokens.json"
    with open(root / "account-pool-tokens.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {"version": 2, "bucket": TOKEN_BUCKET, "since": now, "counts": {}}
        data = _upgrade_tokens(data, now)
        slot = str(int(now // TOKEN_BUCKET * TOKEN_BUCKET))
        row = (data["counts"].setdefault(provider, {}).setdefault(label, {}).setdefault(profile or "?", {})
               .setdefault(model or "?", {}).setdefault(slot, [0, 0, 0, 0, 0]))
        for i, v in enumerate(vals):
            row[i] += v
        row[4] += 1
        _prune(data["counts"], now - TOKEN_KEEP)
        _replace_json(path, data)


def _on_api_request(**kw) -> None:
    try:
        agent = _find_agent(kw.get("session_id") or "")
        pool = getattr(agent, "_credential_pool", None) if agent is not None else None
        if pool is None:
            return
        entry = pool.current()
        if entry is None:
            return
        session_id = kw.get("session_id") or getattr(agent, "session_id", "") or "?"
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
                _add_tokens(root, pool_provider, label, profile, model, kw.get("usage"), now)
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


def register(ctx) -> None:
    ctx.register_hook("post_api_request", _on_api_request)
