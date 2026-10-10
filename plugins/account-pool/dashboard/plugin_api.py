"""Backend for the account-pool Accounts page in Hermes Desktop.

Mounted by Hermes under /api/plugins/account-pool/ (see dashboard/manifest.json) once
`account-pool` is in plugins.enabled. Every route reuses the plugin's own functions
from ../__init__.py, so the page and `hermes account` always agree.

Rules this file keeps:
  * No route returns a token. Rows carry label, id, state and numbers only.
  * Reading the page costs no network call: usage comes from the history the
    balance timer writes every 5 minutes. Only the buttons call providers, and
    live usage is limited to one refresh per provider every 2 minutes, because
    the usage endpoint rate-limits per account.
  * The account pool is shared, so every route works on the default Hermes home,
    whichever profile the desktop is showing.
"""
from __future__ import annotations

import importlib.util
import json
import secrets
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

LIVE_MIN_GAP = 120          # seconds between live usage refreshes per provider
NET_MIN_GAP = 60            # seconds between balance / check runs per provider
SIGNIN_TTL = 15 * 60        # a started sign-in expires after this
SPARK_HOURS = 5
WHO_MINUTES = 30


def _load_core():
    name = "account_pool_core"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent.parent / "__init__.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


core = _load_core()
providers = core.providers

_LOCK = threading.Lock()                 # core functions share module state: one action at a time
_LIVE: dict[str, dict] = {}              # provider -> {"ts", "rows"} from the last live refresh
_NET: dict[str, float] = {}              # provider -> time of the last balance/check from this page
_FLOWS: dict[str, dict] = {}             # sign-in flows; the PKCE/device state never leaves the server
_TIMER: dict[str, Any] = {"ts": 0.0, "data": None}


# ── plumbing ─────────────────────────────────────────────────────────────────

@contextmanager
def _root_home():
    """Run with HERMES_HOME = the default root (the pool, parked file and history live there)."""
    from hermes_constants import get_default_hermes_root, reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(str(get_default_hermes_root()))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


@contextmanager
def _exclusive():
    if not _LOCK.acquire(timeout=1):
        raise HTTPException(409, "Another account action is still running. Try again in a moment.")
    try:
        with _root_home():
            core._reset_run_state()
            yield
    finally:
        _LOCK.release()


def _provider(value: Optional[str]) -> str:
    provider = core._norm(str(value or "anthropic").strip())
    with _root_home():
        known = bool(provider) and core._known_provider(provider)
    if not known:
        raise HTTPException(400, f"Unknown provider '{value}'.")
    return provider


def _exit_text(x: SystemExit) -> str:
    return x.code if isinstance(x.code, str) else f"Exited with code {x.code}."


def _run(handler, **kw) -> dict:
    """Run a CLI handler with its output captured. Caller holds _exclusive()."""
    # The page asks for confirmation itself, so `remove` and `strategy` run with --yes (_dispatch rejects it elsewhere).
    args = SimpleNamespace(provider=None, action=None, target=None, until=None, threshold=None, dry_run=False,
                           hours=None, minutes=None, yes=kw.get("action") in ("remove", "strategy"), key=False,
                           every=None, chart=False, only=None)
    for k, v in kw.items():
        setattr(args, k, v)
    with core._capture() as buf:
        try:
            rc = handler(args)
        except SystemExit as x:
            rc = 1 if isinstance(x.code, str) else (x.code or 0)
            if isinstance(x.code, str):
                core._p(x.code)
    rc = int(rc or 0)
    return {"ok": rc == 0, "rc": rc, "output": buf.getvalue().rstrip()}


def _wait(since: Optional[float], gap: float) -> int:
    """Seconds still to wait before the next network run, 0 when allowed."""
    return max(0, int((since or 0) + gap - time.time()))


def _usage_dict(u) -> Optional[dict]:
    if not u:
        return None
    pct, reset, *rest = u
    return {"pct": float(pct), "reset": reset, "detail": rest[0] if rest else ""}


# ── data from files only (no network) ───────────────────────────────────────

def _history_tail(provider: str, hours: float) -> list[dict]:
    """History records for the provider within `hours`, oldest first (reads the end of the file)."""
    path = core._history_path()
    since = time.time() - hours * 3600
    recs = []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 524288))
            lines = fh.read().decode(errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("provider") == provider and float(rec.get("ts", 0) or 0) >= since:
            recs.append(rec)
    return recs


def _timer() -> dict:
    if time.time() - _TIMER["ts"] > 20 or _TIMER["data"] is None:
        _TIMER["data"] = core._timer_info()
        _TIMER["ts"] = time.time()
    return _TIMER["data"]


def _alerts(provider: str, labels: dict) -> list[dict]:
    out = []
    for key, since in (core._load_json(core._alerts_path(), {}) or {}).items():
        if not key.startswith(provider + ":"):
            continue
        parts = key.split(":")
        if parts[1] == "dead":
            label = labels.get(parts[2], parts[2])
            out.append({"key": key, "since": since, "kind": "dead", "label": label,
                        "text": f"{label} needs to sign in again"})
        elif parts[1] == "all-high":
            limit = core._config().get("alert_all_above", 80)
            out.append({"key": key, "since": since, "kind": "all-high",
                        "text": f"Every account is above {limit}%. Hermes falls back to its fallback model when all are full."})
    return out


def _session_row(r: dict) -> dict:
    return {"profile": r.get("profile") or "?", "platform": r.get("platform") or "", "model": r.get("model") or "",
            "session": (r.get("session_id") or "")[:22], "last_seen": r.get("last_seen"),
            # Records from tracker < 1.2.0 have no account_since; a session that never moved has been
            # on its account since it started.
            "since": r.get("account_since") or (None if r.get("previous_account") else r.get("first_seen")),
            "moved_from": r.get("previous_account") or ""}


def _rotation_mode(provider: str) -> dict:
    """Hermes' pool strategy per profile. Balance's order only decides for fill_first."""
    rows = [{"profile": name, "strategy": core._effective_strategy(value), "configured": value}
            for name, value in core._strategies(provider)]
    return {"default": rows[0]["strategy"], "profiles": rows,
            "other": [r for r in rows if r["strategy"] != "fill_first"]}


def _status(provider: str) -> dict:
    ad = providers.get(provider)
    pool = core._pool(provider)
    entries = sorted(pool.entries(), key=lambda e: e.priority)
    parked = [p for p in core._read_parked() if p["_provider"] == provider]
    now = time.time()

    hist = _history_tail(provider, 24) if ad.has_usage else []
    snap, spark = {}, {}
    for rec in hist:                                   # oldest -> newest: the last write wins
        for label, pct in (rec.get("usage") or {}).items():
            snap[label] = {"pct": float(pct), "reset": (rec.get("reset") or {}).get(label), "ts": rec["ts"],
                           "source": "timer"}
            if rec["ts"] >= now - SPARK_HOURS * 3600:
                spark.setdefault(label, []).append([rec["ts"], float(pct)])
    live = _LIVE.get(provider)
    if live and now - live["ts"] < 900:
        for row in live["rows"]:
            u = row.get("usage")
            if u and u.get("detail", "").startswith("last known"):
                continue                                # a cached value is never newer than the history
            if u and (row["label"] not in snap or snap[row["label"]]["ts"] < live["ts"]):
                snap[row["label"]] = {"pct": u["pct"], "reset": u["reset"], "ts": live["ts"], "source": "live",
                                      "detail": u.get("detail", "")}

    def usage_for(label: str):
        u = snap.get(label)
        if not u:
            return None
        u = dict(u, age=max(0, int(now - u["ts"])))
        if u.get("reset") and u["reset"] <= now:      # its window has reset since: the old number is void
            u.update(pct=None, reset_passed=True)
        return u

    who = core._who_data(provider, WHO_MINUTES)
    by_label = {a["label"]: [_session_row(r) for r in a["sessions"]] for a in who["accounts"]}
    token_rows, counting = core._token_rows(provider)
    by_account = {}
    for row in token_rows:
        by_account.setdefault(row[0], []).append(row)

    def tokens_for(label: str, usage):
        """Tokens of the last 24 h (with their API list price), and of the current usage window when its
        start is known (to 15 min)."""
        rows = by_account.get(label) or []
        day = core._token_group(provider, rows, now - 24 * 3600, by="all").get("all") or core._empty_tokens()
        win = None
        if ad.window_seconds and usage and usage.get("pct") is not None and usage.get("reset") and usage["reset"] > now:
            start = usage["reset"] - ad.window_seconds - core.TOKEN_BUCKET + 1
            win = core._token_group(provider, rows, start, by="all").get("all") or core._empty_tokens()
        return {"day": day, "window": win}
    rotation = []
    for pos, e in enumerate(entries, 1):
        state = core._entry_state(e)
        rotation.append({
            "pos": pos, "id": e.id, "label": e.label, "state": state, "auth": getattr(e, "auth_type", ""),
            "problems": core._problems(provider, e, None),
            "back_at": getattr(e, "last_error_reset_at", None) if state in ("BENCHED", "LIMITED") else None,
            "usage": usage_for(e.label), "spark": spark.get(e.label, []), "sessions": by_label.get(e.label, []),
        })
        rotation[-1]["tokens"] = tokens_for(e.label, rotation[-1]["usage"])
    parked_rows = [{
        "id": p.get("id"), "label": p.get("label", "?"), "since": p.get("_parked_at"),
        "until": p.get("_until"), "dead": bool(p.get("_dead")), "auth": p.get("auth_type", ""), "by": p.get("_by"),
        "usage": usage_for(p.get("label", "?")), "spark": spark.get(p.get("label", "?"), []),
    } for p in parked]
    for row in parked_rows:
        row["tokens"] = tokens_for(row["label"], row["usage"])
    other_sessions = [s for a in who["accounts"] if a["label"] not in {e.label for e in entries}
                      for s in (_session_row(r) for r in a["sessions"])]

    cfg = core._config()
    pool_names = core._pool_providers()
    plist = []
    for name in sorted(set(pool_names) | set(providers.ADAPTERS)):
        a = providers.get(name)
        plist.append({"name": name, "has_usage": a.has_usage, "in_use": name in pool_names})
    return {
        "provider": provider, "providers": plist, "window": ad.window, "has_usage": ad.has_usage,
        "has_identity": ad.has_identity, "web_signin": ad.has_web_signin and core._oauth_provider(provider),
        "rotation": rotation, "parked": parked_rows, "other_sessions": other_sessions,
        "sessions_active": who["count"], "who_minutes": WHO_MINUTES,
        "snapshot": {"ts": hist[-1]["ts"] if hist else None, "count": len(hist)},
        "live": {"ts": live["ts"] if live else None, "retry_after": _wait(live and live["ts"], LIVE_MIN_GAP)},
        "timer": _timer(), "alerts": _alerts(provider, {e.id: e.label for e in entries}),
        "threshold": 90, "alert_all_above": cfg.get("alert_all_above", 80), "now": now,
        "rotation_mode": _rotation_mode(provider),
        "tokens": {"since": counting,
                   "day": core._token_group(provider, token_rows, now - 24 * 3600, by="all").get("all") or core._empty_tokens()},
        "schedules": core._schedule_rows(provider),
    }


# ── read routes ──────────────────────────────────────────────────────────────

@router.get("/status")
def status(provider: str = "anthropic"):
    """Everything the page shows, from files only."""
    with _root_home():
        p = _provider(provider)
        try:
            return _status(p)
        except SystemExit as x:
            raise HTTPException(500, _exit_text(x))


@router.get("/summary")
def summary(provider: str = "anthropic"):
    """Small payload for the status-bar chip: counts, the next account and alerts (files only)."""
    with _root_home():
        p = _provider(provider)
        try:
            data = _status(p)
        except SystemExit as x:
            raise HTTPException(500, _exit_text(x))
    usable = [r for r in data["rotation"] if r["state"] == "active"]
    known = [r for r in usable if r["usage"] and r["usage"].get("pct") is not None]
    nxt = usable[0] if usable else None
    return {
        "provider": p, "rotation": len(data["rotation"]), "usable": len(usable), "parked": len(data["parked"]),
        "next": {"label": nxt["label"], "pct": (nxt["usage"] or {}).get("pct")} if nxt else None,
        "max": max((r["usage"]["pct"] for r in known), default=None),
        "min": min((r["usage"]["pct"] for r in known), default=None),
        "alerts": len(data["alerts"]), "sessions": data["sessions_active"],
    }


@router.get("/report")
def report(provider: str = "anthropic", hours: float = 24):
    if not 0 < hours <= 24 * 14:
        raise HTTPException(400, "hours must be between 0 and 336.")
    with _root_home():
        p = _provider(provider)
        if not providers.get(p).has_usage:
            return {"available": False, "message": core._no_usage_text(p)}
        return dict(core._report_data(p, hours), available=True, chart=core._chart_data(p))


@router.get("/notify")
def notify_status(provider: str = "anthropic"):
    with _root_home():
        p = _provider(provider)
        at = core._daily_at(core._config())
        cfg = core._config()
        root = core._root()
        profiles = ["default"] + sorted(d.name for d in (root / "profiles").iterdir()
                                        if (d / "config.yaml").exists()) if (root / "profiles").is_dir() else ["default"]
        return {
            "desktop": bool(cfg["notify"].get("desktop")), "notify_send": bool(core.shutil.which("notify-send")),
            "telegram": bool(core._telegram_target(cfg)), "telegram_setting": cfg["notify"].get("telegram"),
            "via": cfg["notify"].get("telegram_via") or "default", "profiles": profiles,
            "alert_all_above": cfg.get("alert_all_above", 80),
            "daily": f"{at[0]:02d}:{at[1]:02d}" if at else None,
            "daily_last": (core._load_json(core._state_path(), {}) or {}).get(f"daily:{p}"),
        }


# ── routes that call the provider or change the pool ────────────────────────

@router.post("/live")
def live(body: dict):
    """Live usage of every account, parked included. One refresh per provider every 2 minutes."""
    p = _provider(body.get("provider"))
    if not providers.get(p).has_usage:
        return {"ok": False, "message": core._no_usage_text(p)}
    with _exclusive():
        prev = _LIVE.get(p)
        wait = _wait(prev and prev["ts"], LIVE_MIN_GAP)
        if wait:
            return {"ok": False, "retry_after": wait,
                    "message": f"Live usage was refreshed {LIVE_MIN_GAP - wait}s ago. Next refresh in {wait}s "
                               f"(the usage endpoint rate-limits per account)."}
        rows = core._usage_rows(p)
        _LIVE[p] = {"ts": time.time(), "rows": [{"label": r["label"], "id": r["id"], "state": r["state"],
                                                 "usage": _usage_dict(r["usage"]), "note": r["note"]} for r in rows]}
    failed = [r for r in _LIVE[p]["rows"] if not r["usage"] and r["note"] and r["note"] != "dead"]
    return {"ok": True, "ts": _LIVE[p]["ts"], "rows": _LIVE[p]["rows"],
            "message": f"Usage n/a for {len(failed)} account(s): {failed[0]['note']}" if failed else ""}


ACTIONS = {"park", "unpark", "remove", "balance", "check", "notify", "schedule", "unschedule", "strategy"}


@router.post("/action")
def action(body: dict):
    """park / unpark / remove / balance / check / notify / schedule / unschedule / strategy, with the CLI's rules."""
    name = str(body.get("action") or "").strip().lower()
    if name not in ACTIONS:
        raise HTTPException(400, f"Action must be one of: {', '.join(sorted(ACTIONS))}.")
    p = _provider(body.get("provider"))
    kw = {"provider": p, "action": name, "target": body.get("target") or None}
    if name == "park" and body.get("until"):
        kw["until"] = str(body["until"])
    if name == "schedule":
        if not kw["target"] or not body.get("every"):
            raise HTTPException(400, "schedule needs a target and every (e.g. \"mon-fri 09:00-17:00\").")
        kw["every"] = str(body["every"])
    if name == "strategy":
        if not kw["target"]:
            raise HTTPException(400, "strategy needs a value: fill_first, round_robin, least_used or random.")
        only = body.get("only")
        if isinstance(only, (list, tuple)):
            only = ",".join(str(x) for x in only)
        kw["only"] = str(only) if only else None
    if name == "balance":
        kw["dry_run"] = bool(body.get("dry_run"))
        if body.get("threshold") is not None:
            kw["threshold"] = float(body["threshold"])
    with _exclusive():
        if name in ("balance", "check"):
            wait = _wait(_NET.get(p), NET_MIN_GAP)
            if wait:
                return {"ok": False, "rc": 2, "output": f"This ran less than a minute ago. Try again in {wait}s."}
            _NET[p] = time.time()
        return _run(core._dispatch, **kw)


@router.post("/doctor")
def doctor(body: dict):
    p = _provider(body.get("provider"))
    with _exclusive():
        if not core._entries(p) and not any(x["_provider"] == p for x in core._read_parked()):
            return {"checks": [], "empty": True}
        checks = core._doctor_checks(p)
    return {"checks": [{"level": lvl, "text": text} for lvl, text in checks], "empty": False}


# ── sign-in from the page (add / relogin) ────────────────────────────────────

def _expire_flows() -> None:
    for fid in [k for k, v in _FLOWS.items() if time.time() - v["created"] > SIGNIN_TTL]:
        _FLOWS.pop(fid, None)


@router.post("/signin/start")
def signin_start(body: dict):
    """Start an OAuth sign-in for a new account (mode=add) or an existing one (mode=relogin)."""
    _expire_flows()
    p = _provider(body.get("provider"))
    mode = body.get("mode")
    target = str(body.get("target") or "").strip()
    ad = providers.get(p)
    if mode not in ("add", "relogin") or not target:
        raise HTTPException(400, "mode must be add or relogin, with a target.")
    if not (ad.has_web_signin and core._oauth_provider(p)):
        raise HTTPException(400, f"Sign-in from the desktop is not available for {p}. "
                                 f"Use the terminal: hermes account {p} {mode} {target}")
    flow = {"provider": p, "mode": mode, "created": time.time(), "verify": ad.has_identity}
    with _exclusive():
        try:
            if mode == "add":
                if "@" not in target and ad.has_identity:
                    raise SystemExit("Use the account's email as its name: the sign-in is checked against it.")
                core._add_check(p, target)
                flow["label"] = target
            else:
                flow["label"], flow["old_id"], flow["old_priority"] = core._relogin_target(p, target)
        except SystemExit as x:
            raise HTTPException(400, _exit_text(x))
    try:
        info = ad.signin_start()
    except Exception as x:
        raise HTTPException(502, f"Could not start the sign-in: {str(x)[:200] or type(x).__name__}")
    flow.update(kind=info["kind"], state=info["state"])
    fid = secrets.token_urlsafe(16)
    _FLOWS[fid] = flow
    return {"flow": fid, "kind": info["kind"], "url": info["url"], "user_code": info.get("user_code"),
            "label": flow["label"], "mode": mode, "verify": flow["verify"], "expires_in": SIGNIN_TTL}


@router.post("/signin/step")
def signin_step(body: dict):
    """Finish with a pasted code (kind=code), or check once whether a device sign-in finished."""
    _expire_flows()
    flow = _FLOWS.get(str(body.get("flow") or ""))
    if flow is None:
        return {"status": "error", "message": "This sign-in expired or was cancelled. Start again."}
    ad = providers.get(flow["provider"])
    try:
        creds = ad.signin_step(flow["state"], str(body.get("code") or ""))
    except ValueError as x:
        return {"status": "error", "message": str(x)}
    except Exception as x:
        return {"status": "error", "message": f"Sign-in failed: {str(x)[:200] or type(x).__name__}"}
    if creds is None:
        return {"status": "pending"}
    _FLOWS.pop(str(body.get("flow")), None)          # tokens are single-use: never run the same flow twice
    p, label = flow["provider"], flow["label"]
    with _exclusive():
        with core._capture() as buf:
            try:
                if flow["mode"] == "add":
                    core._add_check(p, label)
                    fresh = core._store_signin(p, label, creds)
                    rc = core._accept_added(p, label, fresh, flow["verify"])
                else:
                    fresh = core._store_signin(p, label, creds)
                    rc = core._accept_relogin(p, label, flow["old_id"], flow["old_priority"], fresh)
            except SystemExit as x:
                core._p(_exit_text(x))
                rc = 1
    _LIVE.pop(p, None)
    return {"status": "done" if rc == 0 else "rejected", "output": buf.getvalue().rstrip()}


@router.post("/signin/cancel")
def signin_cancel(body: dict):
    _FLOWS.pop(str(body.get("flow") or ""), None)
    return {"ok": True}
