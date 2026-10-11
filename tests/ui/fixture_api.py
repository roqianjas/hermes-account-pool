"""Stand-in for dashboard/plugin_api.py that answers from fixtures.json, for the screenshots in docs/screenshots/.

tests/ui/screenshots.mjs copies it, with fixtures.json, over the backend of a throwaway copy of the plugin in a
throwaway Hermes home, so a real Hermes Desktop draws the real page from made-up accounts (alice@example.com,
worker-1, ...). It reads no credential, writes nothing and calls no provider. Times in the fixtures are moved so
that the fixtures' own `now` is the moment the backend starts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
_START = time.time()


def _load() -> dict:
    fx = json.loads(Path(__file__).with_name("fixtures.json").read_text())
    ref = max((v.get("now") for v in fx.values() if isinstance(v, dict) and isinstance(v.get("now"), (int, float))),
              default=_START)
    shift = _START - ref

    def move(o):
        if isinstance(o, dict):
            return {k: move(v) for k, v in o.items()}
        if isinstance(o, list):
            return [move(v) for v in o]
        if isinstance(o, (int, float)) and not isinstance(o, bool) and 1.5e9 < o < 2.2e9:
            return type(o)(o + shift)
        return o
    return move(fx)


FX = _load()


def _next_window(spec: str, now: float):
    """Start of the next window of a schedule like 'Mon-Fri 09:00-17:00' or 'Sat, Sun 10:00-14:00'."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    days_part, _, hours = spec.rpartition(" ")
    days = set()
    for part in days_part.replace(" ", "").lower().split(","):
        a, _, b = part.partition("-")
        if a[:3] in names:
            i, j = names.index(a[:3]), names.index((b or a)[:3])
            days.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
    hh, mm = (int(x) for x in hours.split("-")[0].split(":"))
    for ahead in range(8):
        d = time.localtime(now + ahead * 86400)
        start = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, hh, mm, 0, 0, 0, -1))
        if d.tm_wday in days and start > now:
            return start
    return now + 86400


for _key, _value in FX.items():
    if not isinstance(_value, dict):
        continue
    _t = _value.get("timer") or {}
    if _t.get("next_ts"):
        _t["next"] = time.strftime("%H:%M", time.localtime(_t["next_ts"]))
    if _t.get("last_ts"):
        _t["last"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_t["last_ts"]))
    for _s in _value.get("schedules") or []:
        if _s.get("next") and (_s.get("spec") or _s.get("every")):
            _s["next"] = _next_window(_s.get("spec") or _s.get("every"), _START)


def _chart(window: int, busy: bool) -> dict:
    """The hour chart of the Report tab, as tests/ui/run.mjs draws it: 7 days x 24 hours, busy 09:00-21:00."""
    days = []
    today = time.localtime()
    midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
    for back in range(6, -1, -1):
        start = time.localtime(midnight - back * 86400 + 3600)
        start = time.mktime((start.tm_year, start.tm_mon, start.tm_mday, 0, 0, 0, 0, 0, -1))
        used = [((hr * 7 + back * 13) % 40) + 5 if busy and 9 <= hr < 21 else 0 for hr in range(24)]
        days.append({"start": start, "date": time.strftime("%m-%d", time.localtime(start)),
                     "dow": time.strftime("%a", time.localtime(start)), "used": used,
                     "tokens": [v * 90000 for v in used], "requests": used})
    return {"window": window, "has_usage": True, "days": days}


def _get(name: str, request: Request) -> dict:
    query = "&".join(f"{k}={v}" for k, v in request.query_params.multi_items() if k != "profile")
    key = f"/{name}?{query}"                    # Hermes Desktop adds &profile=<name> to every request
    if key not in FX:
        raise HTTPException(404, f"no fixture {key}")
    data = json.loads(json.dumps(FX[key]))
    if name == "report":
        data["chart"] = _chart(data.get("window") or 0, (data.get("snapshots") or 0) > 0)
    return data


@router.get("/status")
def status(request: Request):
    return _get("status", request)


@router.get("/summary")
def summary(request: Request):
    return _get("summary", request)


@router.get("/report")
def report(request: Request):
    return _get("report", request)


@router.get("/notify")
def notify(request: Request):
    return _get("notify", request)


@router.get("/activity")
def activity(request: Request):
    return _get("activity", request)


@router.post("/live")
def live():
    return {"ok": True, "ts": time.time(), "rows": [], "message": ""}


@router.post("/doctor")
def doctor():
    return {"checks": [{"level": "ok", "text": "credential_pool_strategies.anthropic is fill_first in every profile"},
                       {"level": "ok", "text": "session tracker active in every profile"},
                       {"level": "ok", "text": "balance timer active, last run 2 minutes ago"}], "empty": False}


@router.post("/action")
async def action(request: Request):
    body = await request.json()
    return {"ok": True, "rc": 0, "output": f"{body.get('action')} done"}


@router.post("/signin/start")
async def signin_start(request: Request):
    body = await request.json()
    return {"flow": "F1", "kind": "code", "url": "https://claude.ai/oauth/authorize?client_id=example",
            "user_code": None, "label": body.get("target"), "mode": body.get("mode"), "verify": True, "expires_in": 900}


@router.post("/signin/step")
def signin_step():
    return {"status": "pending"}


@router.post("/signin/cancel")
def signin_cancel():
    return {"ok": True}
