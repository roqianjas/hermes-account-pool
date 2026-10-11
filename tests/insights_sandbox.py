"""The tracker check, tokens per session, bot alerts, the activity log and the forecast, in a throwaway
Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/insights_sandbox.py
    rm -rf "$SB"

Fake API-key accounts, fake session records and fake API calls; notifications are captured, so nothing
is sent and no request reaches a provider. Refuses to run against a Hermes home under ~/.hermes.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
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


tracker = load("hap_tracker", PLUGINS / "account-pool-tracker" / "__init__.py")
api = load("hap_api", PLUGINS / "account-pool" / "dashboard" / "plugin_api.py")
core = api.core
app = FastAPI()
app.include_router(api.router, prefix="/x")
c = TestClient(app)
failures = []
SENT = []
core._notify = lambda title, body, icon="dialog-warning": SENT.append((title, body, icon)) or ["desktop"]
core._has_usage = lambda provider: False            # doctor: no usage probe
core._timer_info = lambda: {"active": True, "result": "success", "running": False, "last": "now", "next": "soon"}


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def run(handler, **kw):
    """A CLI handler with its output: (rc, text)."""
    args = SimpleNamespace(provider="anthropic", action=None, target=None, until=None, threshold=None, dry_run=False,
                           hours=None, minutes=None, yes=False, key=False, every=None, chart=False, only=None)
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


def call(label, usage, profile, model, session, platform="cli"):
    agent = FakeAgent(label, session, model)  # noqa: F841  (the tracker finds it on this frame)
    tracker._root_and_profile = lambda: (Path(HOME), profile)
    tracker._last.clear()
    tracker._on_api_request(session_id=session, platform=platform, model=model, provider="anthropic", usage=usage)


U = {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 1000, "cache_write_tokens": 10}
now = time.time()
SESS = Path(HOME) / "account-pool-sessions.json"
TOK = Path(HOME) / "account-pool-tokens.json"

# ── the tracker records its version, its process and the Kanban task ────────
os.environ["HERMES_KANBAN_TASK"] = "t_fake01"
call("alice@example.com", U, "worker-1", "claude-opus-5-5", "w1")
os.environ.pop("HERMES_KANBAN_TASK")
call("bob@example.com", U, "default", "claude-opus-5-5", "d1", platform="desktop")
recs = json.loads(SESS.read_text())["sessions"]
w1, d1 = recs["worker-1:w1"], recs["default:d1"]
check(w1["tracker"] == tracker.VERSION and w1["pid"] == os.getpid() and w1["task"] == "t_fake01" and "task" not in d1,
      "session record: tracker version, process id, Kanban task when there is one")
version, installed = core._tracker_installed()
check(version == tracker.VERSION and installed and installed <= time.time(), "installed tracker version read from plugin.yaml")
check(f'version: {tracker.VERSION}' in (PLUGINS / "account-pool-tracker" / "plugin.yaml").read_text(),
      "tracker VERSION matches its plugin.yaml")

# ── processes that still run an older tracker ────────────────────────────────
core._tracker_installed = lambda: (tracker.VERSION, now - 3600)
gone = subprocess.Popen([sys.executable, "-c", "pass"])
gone.wait()
fake_gw = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "gateway", "run"])
fake_serve = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--profile", "x", "serve"])
time.sleep(0.3)
check(core._process_kind(fake_gw.pid) == "gateway" and core._process_kind(fake_serve.pid) == "desktop"
      and core._process_kind(os.getpid()) == "session" and core._process_kind(gone.pid) is None
      and core._process_kind(None) is None, "process kind: gateway, desktop, session, ended")


def rec(profile, platform, seen, **kw):
    return dict({"profile": profile, "session_id": f"{profile}-{platform}", "platform": platform, "provider": "anthropic",
                 "model": "m", "account": "alice@example.com", "account_id": "fake00", "first_seen": seen,
                 "last_seen": seen}, **kw)


SESS.write_text(json.dumps({"version": 1, "sessions": {
    "a": rec("worker-1", "cli", now - 60, tracker="1.3.9", pid=os.getpid()),
    "b": rec("worker-2", "telegram", now - 120),                                   # tracker <= 1.3.0: no version, no pid
    "c": rec("default", "desktop", now - 30),
    "d": rec("worker-3", "cli", now - 30, tracker=tracker.VERSION, pid=os.getpid()),  # up to date
    "e": rec("worker-4", "cli", now - 30, tracker="1.3.9", pid=gone.pid),            # its process has ended
    "f": rec("worker-5", "cli", now - 3600 + 60),                                  # before the update
    "g": rec("worker-6", "telegram", now - 2400),                                  # not seen for 40 min
    "h": rec("worker-7", "cli", now - 30, tracker="1.3.9", pid=fake_gw.pid),
    "i": rec("worker-1", "cli", now - 20, tracker="1.3.9", pid=os.getpid(), session_id="w9"),
    "j": dict(rec("worker-8", "cli", now - 30), provider="openai-codex"),
}}))
tr = core._tracker_status("anthropic")
kinds = [(g["kind"], g["profiles"]) for g in tr["stale"]]
check(kinds == [("gateway", ["worker-7"]), ("gateway", ["worker-2"]), ("desktop", ["default"]), ("session", ["worker-1"])],
      "stale trackers: gateway first, then Desktop, then sessions; current, ended, old and other-provider records skipped")
check(tr["stale"][3]["tracker"] == "1.3.9" and tr["stale"][1]["tracker"] == "older than 1.4.0" and tr["stale"][3]["pid"] == os.getpid()
      and tr["stale"][1]["pid"] is None,
      "the old version and the process id when the record has them")
check(tr["stale"][0]["fix"].startswith("hermes gateway restart") and tr["stale"][2]["fix"] == "restart Hermes Desktop"
      and "when it ends" in tr["stale"][3]["fix"], "a fix per kind of process")
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "not loaded yet" in t]
lvl, t = doc[0] if len(doc) == 1 else ("", "")
check(lvl == "warn" and t.startswith(f"session tracker {tracker.VERSION} is not loaded yet by: the gateway (worker-7, pid {fake_gw.pid}; tracker 1.3.9)")
      and "the gateway (worker-2; tracker older than 1.4.0)" in t and "Hermes Desktop (default; tracker older" in t
      and f"a cli session (worker-1, pid {os.getpid()}; tracker 1.3.9)" in t
      and t.count("hermes gateway restart") == 1 and "restart Hermes Desktop" in t,
      "doctor names each process once, with one fix per kind")
check(c.get("/x/status").json()["tracker"]["stale"][0]["kind"] == "gateway", "status: tracker check for the page")
fake_gw.kill()
fake_serve.kill()

# tokens without a bot name: a tracker 1.2.0 or older still writing
data = json.loads(TOK.read_text())
slot = str(int((now - 600) // 900 * 900))
data["counts"]["anthropic"]["alice@example.com"]["?"] = {"?": {slot: [10, 10, 10, 10, 1]}}
TOK.write_text(json.dumps(data))
SESS.write_text(json.dumps({"version": 1, "sessions": {"d": rec("worker-3", "cli", now - 30, tracker=tracker.VERSION, pid=os.getpid())}}))
tr = core._tracker_status("anthropic")
check(tr["unnamed_since"] == int(slot) and not tr["stale"], "unnamed tokens of the last half hour found")
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "tracker" in t]
check(any(lvl == "warn" and t.startswith("tokens without a bot name until") for lvl, t in doc), "doctor: unnamed tokens warn")
with (Path(HOME) / "account-pool-history.jsonl").open("w") as fh:
    for k, u in enumerate((10, 20)):
        fh.write(json.dumps({"ts": now - 900 + k * 300, "provider": "anthropic", "usage": {"alice@example.com": u}}) + "\n")
core._has_usage = lambda provider: True
rc, text = run(core._cmd_report, hours=24.0)
core._has_usage = lambda provider: False
check("(older tracker, no name)" in text, "report names the unnamed tokens")
old = str(int((now - 7200) // 900 * 900))
data["counts"]["anthropic"]["alice@example.com"]["?"] = {"?": {old: [10, 10, 10, 10, 1]}}
TOK.write_text(json.dumps(data))
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "tracker" in t]
check(core._tracker_status("anthropic")["unnamed_since"] is None
      and ("ok", f"running sessions count with tracker {tracker.VERSION}") in doc, "older unnamed tokens: no warning, all current")

blob = json.dumps([c.get("/x/status").json(), json.loads(SESS.read_text())])
check("fake-key" not in blob and "access_token" not in blob, "no credential in status or session records")

# ── tokens per session (tracker 1.5.0) ───────────────────────────────────────
TOK.unlink()
SESS.unlink()
(Path(HOME) / "profiles" / "worker-1").mkdir(parents=True, exist_ok=True)
(Path(HOME) / "profiles" / "worker-1" / "config.yaml").write_text("model:\n  default: x\n")


def state_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("create table if not exists sessions (id text primary key, source text, title text, started_at real, ended_at real)")
    con.executemany("insert or replace into sessions values (?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


state_db(Path(HOME) / "profiles" / "worker-1" / "state.db",
         [("w1", "kanban", "Shipping: admin page for limits", now - 3000, None), ("w2", "cron", "Nightly digest", now - 2000, now - 1000)])
state_db(Path(HOME) / "state.db", [("d1", "desktop", "Plan the release", now - 3000, None)])
os.environ["HERMES_KANBAN_TASK"] = "t_fake01"
for _ in range(3):
    call("alice@example.com", U, "worker-1", "claude-opus-5-5", "w1")
os.environ.pop("HERMES_KANBAN_TASK")
call("bob@example.com", U, "worker-1", "claude-opus-5-5", "w2")
call("bob@example.com", dict(U, output_tokens=5000), "default", "claude-opus-5-5", "d1", platform="desktop")
call("carol@example.com", U, "worker-1", "fake-model", "w3")
data = json.loads(TOK.read_text())
w1 = data["sessions"]["anthropic"]["worker-1"]["w1"]["claude-opus-5-5"]
check(sum(v[4] for v in w1.values()) == 3 and sum(v[0] for v in w1.values()) == 300 and data["sessions_since"] <= time.time(),
      "tracker: tokens per profile, session and model; counted-since recorded")
check(sum(v[4] for p in data["counts"]["anthropic"].values() for m in p.values() for b in m.values() for v in b.values()) == 6,
      "the per-account counts are unchanged")
old = str(int((now - 9 * 86400) // 900 * 900))
data["sessions"]["anthropic"]["worker-1"]["gone"] = {"m": {old: [1, 1, 1, 1, 1]}}
TOK.write_text(json.dumps(data))
call("alice@example.com", U, "worker-1", "claude-opus-5-5", "w1")
check("gone" not in json.loads(TOK.read_text())["sessions"]["anthropic"]["worker-1"], "session buckets older than 8 days dropped")

sd = core._sessions_data("anthropic", 24)
order = [(r["profile"], r["session"]) for r in sd["sessions"]]
check(order[:2] == [("default", "d1"), ("worker-1", "w1")] and sd["count"] == 4, "sessions ranked by API price")
r1 = next(r for r in sd["sessions"] if r["session"] == "w1")
check(r1["title"] == "Shipping: admin page for limits" and r1["source"] == "kanban" and r1["task"] == "t_fake01"
      and r1["named"] and r1["accounts"] == ["alice@example.com"] and r1["tokens"]["requests"] == 4, "title and source from state.db, task and account from the tracker")
r3 = next(r for r in sd["sessions"] if r["session"] == "w3")
check(not r3["named"] and r3["title"] == "session w3" and r3["tokens"]["cost"] == 0 and r3["tokens"]["unpriced"] > 0,
      "a session without a title row, an unpriced model")
check(abs(sd["total"]["cost"] - sum(r["tokens"]["cost"] for r in sd["sessions"])) < 1e-6 and sd["total"]["requests"] == 7, "sessions total")
one = core._sessions_data("anthropic", 24, top=1)
check(len(one["sessions"]) == 1 and one["rest"]["count"] == 3, "top N and the rest")
rc, text = run(core._cmd_sessions, hours=24.0)
check(rc == 0 and "Plan the release" in text and "Shipping: admin page for limits (t_fake01)" in text and "Total:" in text,
      "`sessions` lists titles and tasks")
rep = c.get("/x/report?hours=24").json()
check(rep.get("sessions", {}).get("sessions", [{}])[0].get("session") == "d1", "page report: sessions")
rc, text = run(core._dispatch, action="sessions", target=None, hours=-1.0)
check(rc == 2, "sessions --hours must be positive")

# ── a bot that uses far more than usual ──────────────────────────────────────
price = core._model_price("anthropic", "claude-opus-5-5")
per_dollar = int(1e6 / price[0])                   # input tokens worth $1


def bucket(ts):
    return str(int(ts // 900 * 900))


data = json.loads(TOK.read_text())
cnt = data["counts"]["anthropic"]
cnt["alice@example.com"] = {
    "worker-1": {"claude-opus-5-5": {**{bucket(now - (2 + k) * 86400): [per_dollar, 0, 0, 0, 20] for k in range(5)},
                                     bucket(now - 600): [20 * per_dollar, 0, 0, 0, 100]}},
    "worker-2": {"claude-opus-5-5": {bucket(now - 600): [16 * per_dollar, 0, 0, 0, 50]}},
    "worker-3": {"claude-opus-5-5": {**{bucket(now - (2 + k) * 86400): [10 * per_dollar, 0, 0, 0, 50] for k in range(5)},
                                     bucket(now - 600): [20 * per_dollar, 0, 0, 0, 100]}},
    "worker-4": {"fake-model": {bucket(now - 600): [1000, 0, 0, 0, 400]}},
    "?": {"?": {bucket(now - 600): [99 * per_dollar, 0, 0, 0, 900]}},
}
cnt.pop("bob@example.com", None)
cnt.pop("carol@example.com", None)
data["sessions"]["anthropic"]["worker-1"]["w1"]["claude-opus-5-5"][bucket(now - 600)] = [20 * per_dollar, 0, 0, 0, 100]
TOK.write_text(json.dumps(data))
sp = {r["profile"]: r for r in core._bot_spikes("anthropic")}
check(set(sp) == {"worker-1", "worker-2", "worker-4"}, "spikes: 20x usual, no usual but above the floor, many requests; not 2x usual, not unnamed")
check(sp["worker-1"]["by"] == "cost" and abs(sp["worker-1"]["usual_cost"] - 1.0) < 0.01 and sp["worker-2"]["usual_cost"] is None
      and sp["worker-4"]["by"] == "requests", "spike: by price or by requests, with the usual hour")
title, body = core._spike_text("anthropic", sp["worker-1"])
check(title == "Hermes: worker-1 is using far more than usual" and "20x its usual $1.00 per active hour" in body
      and re.search(r"Busiest session: Shipping: admin page for limits \(kanban, task t_fake01, 10[0-4] requests\)\.", body) and "sessions --hours 1" in body, "bot alert text")
SENT.clear()
pool = core._pool("anthropic")
acts = core._run_alerts("anthropic", pool, [])
check(len([t for t, _, _ in SENT if "far more than usual" in t]) == 3 and len(acts) == 3, "balance alerts once per bot")
SENT.clear()
check(core._run_alerts("anthropic", pool, []) == [] and not SENT, "no repeat while it lasts")
st = c.get("/x/status").json()
bots = [a for a in st["alerts"] if a["kind"] == "bot"]
check(len(bots) == 3 and any("worker-1 is using far more than usual: $20.00" in a["text"] and "(20x its usual hour)" in a["text"] for a in bots),
      "page: bot alerts with their numbers")
rc, text = run(core._dispatch, action="notify", target="bots-off")
check(rc == 0 and "Bot alerts off." in text and core._run_alerts("anthropic", pool, []) == [], "bots-off")
check(not [k for k in json.loads(core._alerts_path().read_text()) if ":bot:" in k], "bots-off clears the bot alerts")
rc, text = run(core._dispatch, action="notify", target="bots=30")
check(rc == 0 and "$30 at API prices" in text and {r["profile"] for r in core._bot_spikes("anthropic")} == {"worker-4"},
      "bots=30 raises the floor and turns them on")
check(run(core._dispatch, action="notify", target="bots=abc")[0] == 2 and run(core._dispatch, action="notify", target="bots=0")[0] == 2,
      "bots= needs a positive amount")
n = c.get("/x/notify").json()
check(n["bots"]["on"] and n["bots"]["usd"] == 30 and n["bots"]["requests"] == 300, "page: bot alert settings")
rc, text = run(core._cmd_notify, target="status")
check("bot alerts: on (a bot's last hour >= $30" in text, "notify status shows the bot alerts")
run(core._dispatch, action="notify", target="bots=15")

# ── activity log ─────────────────────────────────────────────────────────────
ACT = core._activity_path()
rc, text = run(core._dispatch, action="park", target="alice@example.com")
r = c.post("/x/action", json={"action": "unpark", "provider": "anthropic", "target": "alice@example.com"}).json()
run(core._dispatch, action="notify", target="status")
run(core._dispatch, action="notify", target="desktop-off")
run(core._dispatch, action="notify", target="desktop-on")
core._in_timer = lambda: True
run(core._cmd_balance, threshold=90.0)
core._in_timer = lambda: False
ev = core._read_activity("anthropic", 0)
kinds = [(e["by"], e["kind"]) for e in ev]
check(("cli", "park") in kinds and ("page", "unpark") in kinds and ("cli", "notify") in kinds and kinds.count(("cli", "notify")) == 5,
      "logged: park (cli), unpark (page), alert settings; not notify status")
check(any(e["by"] == "cli" and e["text"].startswith("Bot alerts on") for e in ev) and any(e["text"] == "desktop alerts off." for e in ev),
      "the result line of each command is logged")
check(r["ok"] and any(e["by"] == "page" and e["text"].startswith("Unparked [anthropic]: alice@example.com") for e in ev), "page actions are logged as page")
check(oct(ACT.stat().st_mode & 0o777) == "0o600" and "fake-key" not in ACT.read_text(), "activity log mode 600, no credential")
check(any(e["by"] == "timer" and e["kind"] == "alert" for e in ev) or not [e for e in ev if e["kind"] == "alert"],
      "balance actions in the timer are logged as timer")
SENT.clear()
cfgj = json.loads(core._config_path().read_text())
core._atomic_json(core._alerts_path(), {})
core._in_timer = lambda: True
run(core._cmd_balance, threshold=90.0)
core._in_timer = lambda: False
ev = core._read_activity("anthropic", 0)
check(any(e["by"] == "timer" and e["kind"] == "alert" and "far more than usual" in e["text"] for e in ev), "balance alerts logged as timer")
rc, text = run(core._cmd_log, hours=24.0)
check(rc == 0 and "timer  alert" in text and "cli    park" in text and "page   unpark" in text, "`log` lists the events")
a = c.get("/x/activity?hours=24").json()
check(a["count"] == len(ev) and a["events"][0]["ts"] >= a["events"][-1]["ts"], "page: activity, newest first")
check(c.get("/x/activity?hours=0").status_code == 400, "page: activity hours checked")
n0 = len(core._read_activity("anthropic", 0))
core._log_actions("anthropic", ["order: alice > bob", "bench bob@example.com (91%) until 10:40",
                                "schedule: parked carol@example.com until 17:00 (Mon-Fri 09:00-17:00)"], False)
core._log_actions("anthropic", ["bench x (99%) until 11:00"], True)
new = core._read_activity("anthropic", 0)[n0:]
check([(e["kind"], e["text"][:5]) for e in new] == [("balance", "bench"), ("schedule", "sched")], "balance: changes logged, not the order, not a dry run")
core.ACTIVITY_MAX_BYTES = 3000
with ACT.open("a") as fh:
    for k in range(40):
        fh.write(json.dumps({"ts": now - 40 * 86400, "provider": "anthropic", "by": "cli", "kind": "park", "text": "x" * 50}) + "\n")
core._log("anthropic", "park", "after the trim")
lines = ACT.read_text().splitlines()
check(ACT.stat().st_size <= 3000 and lines[-1].find("after the trim") > 0 and not any(json.loads(l)["ts"] < now - 31 * 86400 for l in lines),
      "the log is trimmed: older than 30 days dropped")
core.ACTIVITY_MAX_BYTES = 1_000_000
saved = core._activity_path
core._activity_path = lambda: Path(HOME)                       # a directory: writing fails
core._log("anthropic", "park", "x")
core._activity_path = saved
check(True, "a failing log write does not raise")

# ── forecast ─────────────────────────────────────────────────────────────────
core._has_usage = lambda provider: True
HIST = Path(HOME) / "account-pool-history.jsonl"


def history(series, resets, end=None):
    end = end or now
    with HIST.open("w") as fh:
        for k in range(13):
            fh.write(json.dumps({"ts": end - 3600 + k * 300, "provider": "anthropic",
                                 "usage": {lab: f(k) for lab, f in series.items()}, "reset": resets}) + "\n")


resets = {"alice@example.com": now + 3 * 3600, "bob@example.com": now + 4 * 3600, "carol@example.com": now + 2 * 3600}
history({"alice@example.com": lambda k: 50 + 2.5 * k, "bob@example.com": lambda k: 85, "carol@example.com": lambda k: 88}, resets)
fc = core._forecast("anthropic", now=now)
check(fc["status"] == "ok" and fc["pace"] == 30.0 and fc["accounts"] == 3, "forecast: pace of the last hour, accounts in rotation")
check(fc["full_at"] and abs(fc["full_at"] - (now + 34 * 60)) <= 120 and abs(fc["back_at"] - resets["carol@example.com"]) < 1,
      "forecast: every account at 90% after the headroom is used (~34 min), back at the first reset")
check("every account is at 90% or more around" in fc["text"] and "when the first one resets" in fc["text"], "forecast text")
history({"alice@example.com": lambda k: 10 + 0.5 * k, "bob@example.com": lambda k: 5, "carol@example.com": lambda k: 5}, resets)
fc = core._forecast("anthropic", now=now)
check(fc["status"] == "ok" and fc["full_at"] is None and "last beyond the next 5 hours" in fc["text"], "forecast: enough headroom")
history({"alice@example.com": lambda k: 59 + 2.5 * k, "bob@example.com": lambda k: 89, "carol@example.com": lambda k: 89},
        dict.fromkeys(resets, now + 120))
fc = core._forecast("anthropic", now=now)
check(fc["full_at"] is None, "forecast: windows that reset give the headroom back")
history({"alice@example.com": lambda k: 40, "bob@example.com": lambda k: 40, "carol@example.com": lambda k: 40}, resets)
check(core._forecast("anthropic", now=now)["status"] == "idle", "forecast: idle")
history({"alice@example.com": lambda k: 40 + k}, resets, end=now - 3600)
check(core._forecast("anthropic", now=now)["status"] == "no-data", "forecast: no recent history")
history({"alice@example.com": lambda k: 50 + 2.5 * k, "bob@example.com": lambda k: 85, "carol@example.com": lambda k: 88}, resets)
st = c.get("/x/status").json()
check(st["forecast"] and st["forecast"]["status"] == "ok" and st["forecast"]["full_at"], "status: forecast for the page")
title, body = core._summary("anthropic")
check("Forecast: At the last hour's pace" in body and "Top session: " in body, "summary: forecast and the top session")
rc, text = run(core._cmd_report, hours=24.0)
check("Forecast: At the last hour's pace" in text, "report: forecast")
core._has_usage = lambda provider: False

blob = json.dumps([c.get("/x/status").json(), c.get("/x/report").json(), c.get("/x/activity").json(), json.loads(TOK.read_text())])
check("fake-key" not in blob and "access_token" not in blob, "no credential in status, report, activity or tokens")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
