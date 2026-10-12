"""Parked accounts keep their usage, reset time and chart, in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/parked_usage_sandbox.py
    rm -rf "$SB"

A parked account's 5-hour window keeps running after it was parked, and other apps may still use it.
The balance timer reads it (no quota: a usage read is not a model request), records it under "parked"
in the history, and the page shows its reset time and sparkline. The pool's own numbers (order, alerts,
report, forecast, chart, daily summary) leave parked readings out. Every provider call is faked.
Refuses to run against a Hermes home under ~/.hermes.
"""
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
os.environ["XDG_CONFIG_HOME"] = str(Path(HOME) / "xdg")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

from agent.credential_pool import PooledCredential, load_pool  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

API = Path(__file__).resolve().parent.parent / "plugins" / "account-pool" / "dashboard" / "plugin_api.py"
spec = importlib.util.spec_from_file_location("hap_api", API)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
core = api.core
app = FastAPI()
app.include_router(api.router, prefix="/x")
c = TestClient(app)
core._timer_active = lambda: False
core._tty = lambda: False
failures = []
ROOT = Path(HOME)
HIST = ROOT / "account-pool-history.jsonl"
PARKED = ROOT / "account-pool-parked.json"


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def run(action, target=None, provider="anthropic", **kw):
    args = SimpleNamespace(provider=provider, action=action, target=target, until=None, threshold=None,
                           dry_run=False, hours=None, minutes=None, yes=False, key=False, every=None, chart=False,
                           only=None, timer=False, strategy=False, undo=False, device=False)
    for k, v in kw.items():
        setattr(args, k, v)
    core._reset_run_state()
    with core._capture() as buf:
        try:
            rc = core._dispatch(args)
        except SystemExit as x:
            rc = x.code if isinstance(x.code, int) else 1
            core._p(x.code)
    return rc, buf.getvalue()


def history():
    return [json.loads(x) for x in HIST.read_text().splitlines()] if HIST.exists() else []


def parked_file():
    return json.loads(PARKED.read_text())["parked"]


def write_parked(items):
    PARKED.write_text(json.dumps({"version": 1, "parked": items}))


def status():
    api._NET.clear()
    core._reset_run_state()
    return c.get("/x/status?provider=anthropic").json()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# ── three Anthropic OAuth accounts with fake usage ───────────────────────────
P = "anthropic"
FAR = 4102444800000                         # token expiry far ahead: nothing is refreshed
LABELS = ["alice@example.com", "bob@example.com", "carol@example.com"]
pool = load_pool(P)
for i, label in enumerate(LABELS):
    pool.add_entry(PooledCredential(provider=P, id=f"pk{i}000", label=label, auth_type="oauth", priority=i,
                                    source="manual:hermes_pkce", access_token=f"fake-at-{i}",
                                    refresh_token=f"fake-rt-{i}", expires_at_ms=FAR))
TOKEN = {f"fake-at-{i}": lab for i, lab in enumerate(LABELS)}
FIVE = {}                                   # label -> (utilization, resets_at epoch or None) or HTTP status
READS = []                                  # labels whose usage was read


def fake_get(entry, path):
    label = TOKEN.get(entry.access_token)
    READS.append(label)
    got = FIVE.get(label, 500)
    if isinstance(got, int):
        raise urllib.error.HTTPError("https://api.anthropic.com" + path, got, "fake", {}, io.BytesIO(b"{}"))
    util, reset = got
    return {"five_hour": {"utilization": util, "resets_at": iso(reset) if reset else None}}


ad = core.providers.get(P)
ad._get = fake_get
REFRESHED = []


def fake_refresh(record):
    REFRESHED.append(record.get("label"))
    new = f"fake-at-new-{len(REFRESHED)}"
    TOKEN[new] = record.get("label")
    return {"access_token": new, "refresh_token": f"fake-rt-new-{len(REFRESHED)}", "expires_at_ms": FAR}


ad.refresh_parked = fake_refresh

now = time.time()
CAROL_RESET = now + 2 * 3600
FIVE.update({"alice@example.com": (12.0, now + 3600), "bob@example.com": (30.0, now + 4000),
             "carol@example.com": (41.0, CAROL_RESET)})

# ── the timer reads parked accounts and marks them in the history ────────────
rc, out = run("park", "carol@example.com")
check(rc == 0 and [p["label"] for p in parked_file()] == ["carol@example.com"], "carol parked (setup)")

READS.clear()
rc, out = run("balance", threshold=90.0)
rec = history()[-1]
check(rc == 0 and "carol@example.com" in READS, "balance reads the parked account's usage too")
check(rec["usage"].get("carol@example.com") == 41.0 and abs(rec["reset"]["carol@example.com"] - CAROL_RESET) < 2,
      "its percent and reset time are recorded")
check(rec.get("parked") == ["carol@example.com"], "the record lists it under 'parked'")
check(rec["usage"].get("alice@example.com") == 12.0 and rec["usage"].get("bob@example.com") == 30.0,
      "the accounts in rotation are recorded as before")
check("carol" not in out and [e.label for e in sorted(load_pool(P).entries(), key=lambda e: e.priority)]
      == ["alice@example.com", "bob@example.com"], "a parked account never enters the order or the output")

FIVE["carol@example.com"] = (97.0, CAROL_RESET)
rc, out = run("balance", threshold=90.0)
check("bench" not in out and "carol" not in out, "a full parked account is not benched or reported")
check(not any("carol" in k for k in json.loads((ROOT / "account-pool-alerts.json").read_text() or "{}"))
      if (ROOT / "account-pool-alerts.json").exists() else True, "nor alerted on")
FIVE["carol@example.com"] = (41.0, CAROL_RESET)
run("balance", threshold=90.0)

READS.clear()
n = len(history())
rc, out = run("balance", threshold=90.0, dry_run=True)
check(len(history()) == n and "carol@example.com" not in READS, "a dry run reads and writes nothing for parked accounts")

# ── the page shows its reset, window and day ─────────────────────────────────
st = status()
row = next(p for p in st["parked"] if p["label"] == "carol@example.com")
check(row["usage"] and row["usage"]["pct"] == 41.0 and abs(row["usage"]["reset"] - CAROL_RESET) < 2,
      "page: the parked row has its usage and reset time from the timer")
check(row["window"] == {"idle": False, "reset": row["usage"]["reset"]}, "page: its 5-hour window is running")
check(len(row["spark"]) >= 2 and row["spark"][-1][1] == 41.0, "page: its sparkline continues while parked")
check(row["peak"] and row["peak"]["pct"] == 97.0, "page: the day's highest reading is there for the tooltip")
check(all("peak" in r for r in st["rotation"]) and st["rotation"][1]["peak"]["pct"] == 30.0,
      "page: rotation rows carry the day's highest reading too")
check(st["summary"]["parked"] == 1 if "summary" in st else True, "page: the summary still counts it as parked")

# the window ends while parked: the next run reads "not started"
FIVE["carol@example.com"] = (0.0, None)
run("balance", threshold=90.0)
row = next(p for p in status()["parked"] if p["label"] == "carol@example.com")
check(row["window"]["idle"] is True and row["usage"]["pct"] == 0.0, "page: a window that ended reads idle")
check(row["peak"]["pct"] == 97.0, "page: the earlier reading stays as the day's highest")

# ── refresh and dead sign-ins ────────────────────────────────────────────────
items = parked_file()
items[0]["expires_at_ms"] = int((time.time() - 60) * 1000)
write_parked(items)
FIVE["carol@example.com"] = (5.0, now + 3 * 3600)
REFRESHED.clear()
READS.clear()
run("balance", threshold=90.0)
item = parked_file()[0]
check(REFRESHED == ["carol@example.com"] and item["access_token"] == "fake-at-new-1" and item["expires_at_ms"] == FAR,
      "an expired parked token is refreshed and written back before the read")
check(history()[-1]["usage"].get("carol@example.com") == 5.0, "then its usage is recorded")

items = parked_file()
items[0]["_dead"] = "invalid_grant"
write_parked(items)
READS.clear()
run("balance", threshold=90.0)
check("carol@example.com" not in READS and "carol@example.com" not in history()[-1]["usage"],
      "a parked account whose sign-in died is not read")
items[0].pop("_dead")
write_parked(items)

FIVE["carol@example.com"] = 429
READS.clear()
rc, out = run("balance", threshold=90.0)
check(rc == 0 and "carol" not in out and "carol@example.com" not in history()[-1]["usage"],
      "a failed parked read is skipped quietly (no cached value re-recorded)")
FIVE["carol@example.com"] = (5.0, now + 3 * 3600)

# ── no rotation account readable: parked readings are still recorded ─────────
run("park", "alice@example.com")
rc, out = run("park", "bob@example.com")
check(rc == 1 and "last working" in out, "the last working account cannot be parked (unchanged guard)")
FIVE["bob@example.com"] = 403                # not transient: no cached value either
rc, out = run("balance", threshold=90.0)
rec = history()[-1]
check(rc == 0 and "usage unavailable for every account" in out and "bob@example.com" not in rec["usage"]
      and sorted(rec.get("parked") or []) == ["alice@example.com", "carol@example.com"],
      "when no account in rotation can be read, the parked ones are still recorded")
FIVE["bob@example.com"] = (30.0, now + 4000)
run("unpark", "alice@example.com")
check(len(load_pool(P).entries()) == 2, "alice back in rotation (setup)")

# ── live usage on the page reads parked windows by account ───────────────────
core._reset_run_state()
rows = core._usage_rows(P)
check(any(r["parked"] and r["usage"] for r in rows) and (P, "carol@example.com") in core._WINDOW,
      "live usage keeps the parked account's 5-hour window under its label")

# ── the pool's own numbers leave parked readings out ─────────────────────────
HIST.write_text("")
t0 = time.time() - 3000
for k in range(11):                         # 50 minutes: rotation at 95% (full), carol climbing while parked
    rec = {"ts": round(t0 + k * 300), "provider": P,
           "usage": {"alice@example.com": 95.0, "bob@example.com": 96.0, "carol@example.com": float(k * 8)},
           "reset": {"alice@example.com": now + 3600, "bob@example.com": now + 3600,
                     "carol@example.com": now + 9000},
           "parked": ["carol@example.com"]}
    with HIST.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
core._reset_run_state()
check(core._pool_usage(json.loads(HIST.read_text().splitlines()[-1])) == {"alice@example.com": 95.0,
                                                                          "bob@example.com": 96.0},
      "_pool_usage drops the parked labels")
check(core._pool_usage({"usage": {"x@example.com": 3.0}}) == {"x@example.com": 3.0}, "records without 'parked' are unchanged")
rep = core._report_data(P, 24)
check(not any(a["label"] == "carol@example.com" and a["used"] for a in rep["accounts"]) and rep["total"] == 0,
      "report: usage that rose while parked is not the pool's load")
check(rep["full_min"] > 0, "report: the rotation counts as full although a parked account is low")
fc = core._forecast(P)
check(fc["status"] == "idle" and fc["pace"] == 0, f"forecast: no pace from a parked account ({fc['status']}, {fc['pace']})")
ch = core._chart_data(P, days=1)
check(sum(sum(d["used"]) for d in ch["days"]) == 0, "chart: parked increases are not drawn as quota used")
check(core._quiet_day(P) is False, "daily summary: a full rotation is not a quiet day")
HIST.write_text("".join(json.dumps({"ts": round(t0 + k * 300), "provider": P,
                                    "usage": {"alice@example.com": 0.0, "carol@example.com": float(k * 8)},
                                    "reset": {"alice@example.com": None, "carol@example.com": now + 9000},
                                    "parked": ["carol@example.com"]}) + "\n" for k in range(11)))
core._reset_run_state()
check(core._quiet_day(P) is True, "daily summary: a day with only parked usage is quiet")

with HIST.open("a") as fh:                  # the same climb in rotation counts
    for k in range(3):
        fh.write(json.dumps({"ts": round(time.time() - 600 + k * 300), "provider": P,
                             "usage": {"alice@example.com": 10.0 + k * 20, "bob@example.com": 0.0},
                             "reset": {"alice@example.com": now + 3600, "bob@example.com": None}}) + "\n")
core._reset_run_state()
check(core._report_data(P, 24)["total"] > 0 and core._quiet_day(P) is False, "while in rotation the same climb counts")

blob = HIST.read_text() + "".join(p.read_text() for p in ROOT.glob("account-pool-*.json") if p.name != PARKED.name)
check(not any(x in blob for x in ("fake-at-", "fake-rt-")), "no token in the history, state or settings files")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
