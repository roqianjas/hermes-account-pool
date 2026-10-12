"""Tokens per profile and model, API prices, the hour chart, the daily summary and park schedules,
in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/features_sandbox.py
    rm -rf "$SB"

Fake API-key accounts and fake API calls; notifications are captured, so nothing is sent and no
request reaches a provider. Refuses to run against a Hermes home under ~/.hermes.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in  # the real Hermes home, also on Windows
                  [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

from agent.credential_pool import PooledCredential, load_pool  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tracker = load("hap_tracker", PLUGINS / "account-pool" / "tracker.py")
api = load("hap_api", PLUGINS / "account-pool" / "dashboard" / "plugin_api.py")
core = api.core
app = FastAPI()
app.include_router(api.router, prefix="/x")
c = TestClient(app)
failures = []
SENT = []
core._notify = lambda title, body, icon="dialog-warning": SENT.append((title, body, icon)) or ["desktop"]


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def run(handler, **kw):
    """A CLI handler with its output: (rc, text)."""
    args = SimpleNamespace(provider="anthropic", action=None, target=None, until=None, threshold=None, dry_run=False,
                           hours=None, minutes=None, yes=False, key=False, every=None, chart=False)
    for k, v in kw.items():
        setattr(args, k, v)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rc = handler(args)
        except SystemExit as x:
            rc = x.code if isinstance(x.code, int) else 1
            print(x.code)
    return rc, out.getvalue()


pool = load_pool("anthropic")
for i, label in enumerate(["alice@example.com", "bob@example.com", "carol@example.com"]):
    pool.add_entry(PooledCredential(provider="anthropic", id=f"fake{i}0", label=label, auth_type="api_key",
                                    priority=i, source="manual", access_token=f"fake-key-{i}"))
entries = {e.label: e for e in load_pool("anthropic").entries()}


class FakePool:
    provider = "anthropic"

    def __init__(self, entry):
        self.entry = entry

    def current(self):
        return self.entry


class FakeAgent:
    def __init__(self, label, session, model):
        self._credential_pool = FakePool(entries[label])
        self.session_id = session
        self.platform = "cli"
        self.model = model


def call(label, usage, profile, model, session):
    agent = FakeAgent(label, session, model)  # the tracker finds it on this frame
    tracker._root_and_profile = lambda: (Path(HOME), profile)
    tracker.on_api_request(session_id=session, platform="cli", model=model, provider="anthropic", usage=usage)
    return agent


U = {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 1000, "cache_write_tokens": 10}
now = time.time()

# ── tracker 1.3.0: per account, profile and model; a 1.1.0 file is folded in ─
path = Path(HOME) / "account-pool-tokens.json"
recent = str(int((now - 3600) // 900 * 900))
t0 = now - 7200
path.write_text(json.dumps({"bucket": 900, "since": t0,
                            "buckets": {"anthropic": {"alice@example.com": {recent: [1000, 0, 0, 0, 1]}}}}))
call("alice@example.com", U, "worker-1", "claude-opus-5-5", "w1")
call("alice@example.com", U, "worker-1", "anthropic/claude-opus-5-5", "w1")
call("carol@example.com", U, "worker-1", "claude-opus-4-6", "w1b")
call("bob@example.com", U, "default", "fake-model", "d1")
data = json.loads(path.read_text())
check(data.get("version") == 2 and "buckets" not in data and data["since"] == t0, "token file upgraded to version 2, start kept")
check(data["counts"]["anthropic"]["alice@example.com"]["?"]["?"][recent] == [1000, 0, 0, 0, 1],
      "tracker 1.1.0 buckets kept under profile and model '?'")
check(sum(v[4] for v in data["counts"]["anthropic"]["alice@example.com"]["worker-1"]["claude-opus-5-5"].values()) == 2,
      "the provider prefix of a model name is dropped")
old = str(int((now - 9 * 86400) // 900 * 900))
data["counts"]["anthropic"]["bob@example.com"]["default"]["fake-model"][old] = [1, 1, 1, 1, 1]
data["buckets"] = {"anthropic": {"carol@example.com": {old: [5, 5, 5, 5, 5]}}}   # a 1.1.0 tracker still running
path.write_text(json.dumps(data))
call("bob@example.com", dict.fromkeys(U, 0), "default", "fake-model", "d1")            # empty usage: no write
check(json.loads(path.read_text())["buckets"], "a call without tokens does not rewrite the file")
call("bob@example.com", dict(U, input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=1),
     "default", "fake-model", "d1")
data = json.loads(path.read_text())
check("buckets" not in data and old not in data["counts"]["anthropic"]["bob@example.com"]["default"]["fake-model"]
      and "carol@example.com" in data["counts"]["anthropic"] and "?" not in data["counts"]["anthropic"]["carol@example.com"],
      "late 1.1.0 buckets folded in, buckets older than 8 days dropped with their empty levels")
check((os.name == "nt" or oct(path.stat().st_mode & 0o777) == "0o600") and "fake-key" not in path.read_text(encoding="utf-8"),
      "token file mode 600 (no Unix modes on Windows), no credential")

# ── grouping and API list prices ─────────────────────────────────────────────
rows, since = core._token_rows("anthropic")
by_p = core._token_group("anthropic", rows, now - 86400, by="profile")
by_m = core._token_group("anthropic", rows, now - 86400, by="model")
total = core._token_group("anthropic", rows, now - 86400, by="all")["all"]
check(by_p["worker-1"]["requests"] == 3 and by_p["worker-1"]["accounts"] == 2 and by_p["default"]["requests"] == 2
      and by_p["?"]["total"] == 1000, "tokens per profile, with the number of accounts")
opus5 = (100 * 4 + 50 * 20 + 1000 * 0.2 + 10 * 5) / 1e6
opus46 = (100 * 5 + 50 * 25 + 1000 * 0.5 + 10 * 6.25) / 1e6
check(abs(by_m["claude-opus-5-5"]["cost"] - round(2 * opus5, 4)) < 1e-9 and abs(by_m["claude-opus-4-6"]["cost"] - round(opus46, 4)) < 1e-9,
      "API price per model from Hermes' price list")
check(by_m["fake-model"]["cost"] == 0 and by_m["fake-model"]["unpriced"] == 1161 and by_m["?"]["unpriced"] == 1000,
      "tokens of unknown models are counted as unpriced, not guessed")
check(total["unpriced"] == 2161 and abs(total["cost"] - round(2 * opus5 + opus46, 4)) < 1e-9, "pool total: price and unpriced tokens")
check(core._fmt_cost(total) == "$0.01+" and core._fmt_cost(core._empty_tokens()) == "-"
      and core._fmt_cost(dict(total, cost=0.0)) == "-", "API price formatting")
check(by_p["worker-1"]["model"] == "claude-opus-5-5", "the model a profile used most")

# report (CLI and page)
hist = Path(HOME) / "account-pool-history.jsonl"
with hist.open("w") as fh:
    for k, (a, b) in enumerate([(10, 5), (20, 5), (35, 6)]):
        fh.write(json.dumps({"ts": now - 3600 + k * 300, "provider": "anthropic",
                             "usage": {"alice@example.com": a, "bob@example.com": b}}) + "\n")
rc, text = run(core._cmd_report, hours=24.0)
check("API $" in text and "By profile (bot)" in text and "worker-1" in text and "(older tracker, no name)" in text
      and "By model" in text and "claude-opus-4-6" in text and "report --chart" in text, "`report` lists bots, models and API prices")
rep = c.get("/x/report?hours=24").json()
check([g["name"] for g in rep["by_profile"]][:1] == ["worker-1"] and rep["tokens_total"]["unpriced"] == 2161,
      "page report: by profile, by model, price")
ch = rep["chart"]
check(len(ch["days"]) == 7 and all(len(d["used"]) == len(d["tokens"]) == len(d["requests"]) == 24 for d in ch["days"]),
      "hour chart: 7 days x 24 hours")
check(sum(sum(d["tokens"]) for d in ch["days"]) == total["total"] and abs(sum(sum(d["used"]) for d in ch["days"]) - 26) < 1e-6,
      "hour chart adds up the tokens and the quota used")
today = datetime.now().strftime("%m-%d")
check(ch["days"][-1]["date"] == today, "the last chart row is today")
rc, text = run(core._cmd_report, chart=True)
check(rc == 0 and text.count(f" {today}  ") == 2 and "Darkest" in text and "tokens through Hermes" in text, "`report --chart`")
st = c.get("/x/status").json()
alice = next(r for r in st["rotation"] if r["label"] == "alice@example.com")
check(alice["tokens"]["day"]["cost"] > 0 and st["tokens"]["day"]["unpriced"] == 2161, "status: API price per account and in total")

# ── daily summary ────────────────────────────────────────────────────────────
title, body = core._summary("anthropic")
check(title == "Hermes anthropic: last 24 h" and "Tokens: " in body and "Bots: worker-1" in body and "at API list prices" in body
      and "Now: 3 in rotation, 0 parked; new sessions start on alice" in body, "summary text")
check("fake-key" not in body and "access_token" not in body, "no credential in the summary")
for bad in ("daily=7:5", "daily=25:00", "daily=soon"):
    check(run(core._cmd_notify, target=bad)[0] == 2, f"notify {bad} refused")
cfgp = core._config_path()
cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}
cfg.setdefault("notify", {})["daily"] = "00:00"
cfgp.write_text(json.dumps(cfg))
SENT.clear()
first, second = core._run_daily("anthropic"), core._run_daily("anthropic")
check(first == ["daily summary -> desktop"] and second == [] and len(SENT) == 1 and SENT[0][2] == "dialog-information",
      "daily summary sent once a day")
check(json.loads(core._state_path().read_text())["daily:anthropic"] == datetime.now().strftime("%Y-%m-%d"), "last sent day recorded")
state = json.loads(core._state_path().read_text())
state.pop("daily:anthropic")
core._state_path().write_text(json.dumps(state))
rc, text = run(core._cmd_notify, target="daily=00:00")
check(rc == 0 and "first one tomorrow" in text and core._run_daily("anthropic") == [], "turned on after its time: starts tomorrow")
check(c.get("/x/notify?provider=anthropic").json()["daily"] == "00:00", "page: daily summary time")
rc, text = run(core._cmd_notify, target="status")
check("daily summary: 00:00" in text, "notify status shows the daily summary")
SENT.clear()
rc, text = run(core._cmd_notify, target="summary")
check(rc == 0 and len(SENT) == 1 and "Hermes anthropic: last 24 h" in text, "notify summary sends it now")
run(core._cmd_notify, target="daily-off")
state = json.loads(core._state_path().read_text())
state.pop("daily:anthropic")
core._state_path().write_text(json.dumps(state))
check(core._run_daily("anthropic") == [] and c.get("/x/notify").json()["daily"] is None, "daily-off")

# ── park schedules ───────────────────────────────────────────────────────────
P = core._parse_every
check(P("mon-fri 09:00-17:00") == {"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "17:00"}, "parse mon-fri")
check(P("fri-mon 8.00-9.30")["days"] == [0, 4, 5, 6] and P("weekend 22:00-06:00")["days"] == [5, 6]
      and P("daily 1:00-2:00")["from"] == "01:00" and P("Tuesday,thu 07:00-08:00")["days"] == [1, 3], "parse ranges, names, aliases")
for bad in ("mon-fri", "xyz 09:00-10:00", "mon 24:00-25:00", "mon 09:00-09:00", ""):
    try:
        P(bad)
        check(False, f"--every {bad!r} refused")
    except SystemExit:
        check(True, f"--every {bad!r} refused")
check(core._every_text(P("mon-fri 09:00-17:00")) == "Mon-Fri 09:00-17:00" and core._every_text(P("sat,sun 10:00-14:00"))
      == "Sat, Sun 10:00-14:00" and core._every_text(P("daily 22:00-06:00")) == "Every day 22:00-06:00", "schedule text")
monday = datetime(2030, 1, 7, 12, 0).timestamp()                  # a Monday
s = P("mon 22:00-06:00")
check(core._schedule_window(s, monday) is None and core._schedule_window(s, monday + 11 * 3600) is not None
      and core._schedule_window(s, monday + 11 * 3600)[1] == datetime(2030, 1, 8, 6, 0).timestamp(), "a window past midnight")
check(core._schedule_window(s, datetime(2030, 1, 9, 3, 0).timestamp()) is None, "a window does not open on other days")
check(core._schedule_window(s, monday, ahead=True)[0] == datetime(2030, 1, 7, 22, 0).timestamp(), "next window")

n = datetime.now()
span = f"{(n - timedelta(hours=1)):%H:%M}-{(n + timedelta(hours=1)):%H:%M}"
rc, text = run(core._cmd_schedule)
check(rc == 0 and "no park schedules" in text, "schedule: none yet")
check(run(core._cmd_schedule, target="bob@example.com")[0] == 2, "schedule without --every refused")
check(run(core._cmd_schedule, target="nobody@example.com", every=f"daily {span}")[0] == 1, "schedule of an unknown account refused")
rc, text = run(core._cmd_schedule, target="bob@example.com", every=f"daily {span}")
check(rc == 0 and "Schedule saved" in text and "current window has started" in text, "schedule saved")
check(core._run_schedules("anthropic", dry=True) == [f"schedule: park bob@example.com until {(n + timedelta(hours=1)):%H:%M}"]
      and not core._find_parked("anthropic", "bob@example.com"), "dry run parks nothing")
acts = core._run_schedules("anthropic")
parked = core._find_parked("anthropic", "bob@example.com")
check(len(acts) == 1 and parked and parked.get("_by") == "schedule" and abs(parked["_until"] - (n + timedelta(hours=1)).replace(second=0, microsecond=0).timestamp()) < 1,
      "the timer parks it at the start of the window, until its end")
check(core._run_schedules("anthropic") == [], "a window is applied once")
run(core._cmd_unpark, target="bob@example.com")
check(core._run_schedules("anthropic") == [] and not core._find_parked("anthropic", "bob@example.com"),
      "unparked by hand inside the window: stays in rotation")
row = next(r for r in c.get("/x/status").json()["schedules"] if r["label"] == "bob@example.com")
check(row["in_window"] and not row["parked"] and row["found"] and row["every"].startswith("Every day"), "status: schedule row")
rc, text = run(core._cmd_schedule)
check("in its window but in rotation" in text, "schedule list: the state now")
state = json.loads(core._state_path().read_text())
state["schedule"] = {k: v - 86400 for k, v in state["schedule"].items()}              # the next day's window
core._state_path().write_text(json.dumps(state))
check(len(core._run_schedules("anthropic")) == 1 and core._find_parked("anthropic", "bob@example.com"), "the next window parks it again")
rc, text = run(core._cmd_list)
check("(schedule)" in text and "park schedules (1)" in text, "list shows schedules")
rc, text = run(core._cmd_unschedule, target="BOB@example.com")
check(rc == 0 and "stays parked until" in text and core._schedules("anthropic") == [], "unschedule (any case)")
check(run(core._cmd_unschedule, target="bob@example.com")[0] == 1, "unschedule of a missing schedule refused")
run(core._cmd_unpark, target="bob@example.com")

# the last working account is never parked; the schedule tries again on the next run
run(core._cmd_park, target="alice@example.com")
run(core._cmd_park, target="bob@example.com")
run(core._cmd_schedule, target="carol@example.com", every=f"daily {span}")
acts = core._run_schedules("anthropic")
check(len(acts) == 1 and "could not park carol" in acts[0] and "last working" in acts[0], "the last working account is not parked")
check(len(core._run_schedules("anthropic")) == 1, "a refused park is tried again on the next run")
run(core._cmd_unpark, target="alice@example.com")
run(core._cmd_unpark, target="bob@example.com")

# balance runs schedules and the daily summary
cfg = json.loads(cfgp.read_text())
cfg["notify"]["daily"] = "00:00"
cfgp.write_text(json.dumps(cfg))
SENT.clear()
rc, text = run(core._cmd_balance, threshold=90.0)
check("schedule: parked carol@example.com" in text and "daily summary -> desktop" in text and len(SENT) == 1,
      "balance applies schedules and sends the daily summary")
run(core._cmd_unpark, target="carol@example.com")
run(core._cmd_notify, target="daily-off")

# page actions
code, out = c.post("/x/action", json={"action": "schedule", "provider": "anthropic", "target": "alice@example.com"}).status_code, None
check(code == 400, "page: schedule without every refused")
r = c.post("/x/action", json={"action": "schedule", "provider": "anthropic", "target": "fake00", "every": "sat,sun 10:00-14:00"}).json()
check(r["ok"] and any(s["label"] == "alice@example.com" and s["every"] == "Sat, Sun 10:00-14:00" for s in core._schedule_rows("anthropic")),
      "page: schedule by id")
r = c.post("/x/action", json={"action": "unschedule", "provider": "anthropic", "target": "alice@example.com"}).json()
check(r["ok"] and not any(s["label"] == "alice@example.com" for s in core._schedule_rows("anthropic")), "page: unschedule")

# a schedule left behind by a removed account is flagged
cfg = json.loads(cfgp.read_text())
cfg["schedules"]["anthropic"].append(dict(P("mon 09:00-10:00"), label="gone@example.com", id="gone"))
cfgp.write_text(json.dumps(cfg))
check(any(lvl == "warn" and "gone@example.com" in t for lvl, t in core._doctor_checks("anthropic")), "doctor flags a schedule without account")
blob = json.dumps([c.get("/x/status").json(), c.get("/x/report").json(), json.loads(core._state_path().read_text())])
check("fake-key" not in blob and "access_token" not in blob, "no credential in status, report or state")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
