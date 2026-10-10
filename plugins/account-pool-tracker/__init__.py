"""Record which credential-pool account each session is using.

Companion to the `account-pool` plugin (`hermes account <provider> who`).
Hermes does not persist the account chosen for a session, so this hook reads
the live pool from the running agent after each API call and writes
{profile, session, platform, model, account} to
<hermes root>/account-pool-sessions.json (mode 600). Labels and ids only,
never tokens.

Writes are throttled: once per session per minute, or immediately when the
session's account changes (e.g. after a rotation). Any failure is swallowed
so the hook can never break a turn.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

KEEP_SECONDS = 24 * 3600
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
        if prev.get("account") and prev.get("account") != record["account"]:
            record["previous_account"] = prev["account"]
        elif prev.get("previous_account"):
            record["previous_account"] = prev["previous_account"]
        sessions[key] = record
        cutoff = time.time() - KEEP_SECONDS
        data["sessions"] = {k: v for k, v in sessions.items() if v.get("last_seen", 0) >= cutoff}
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)


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
        prev = _last.get(key)
        if prev and prev[0] == label and now - prev[1] < 60:
            return
        _last[key] = (label, now)
        _write(root, key, {
            "profile": profile,
            "session_id": session_id,
            "platform": kw.get("platform") or getattr(agent, "platform", "") or "",
            "model": kw.get("model") or getattr(agent, "model", "") or "",
            "provider": kw.get("provider") or getattr(pool, "provider", "") or "",
            "account": label,
            "account_id": entry.id,
            "last_seen": now,
        })
    except Exception:
        pass


def register(ctx) -> None:
    ctx.register_hook("post_api_request", _on_api_request)
