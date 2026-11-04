"""The weekly limit next to the 5-hour window, in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/weekly_sandbox.py
    rm -rf "$SB"

Anthropic's usage answer carries the 5-hour window (`five_hour`), the account-wide weekly limit
(`seven_day`) and weekly limits of one model family (`seven_day_opus`, `seven_day_sonnet`). The headline
percent is the fuller of the 5-hour window and the week, so balance never puts an account first that
is locked for days; the model-family limits are shown, never counted. The newest weekly reading per
account is kept in account-pool-limits.json for the page, `who`, alerts and the daily summary. One alert
per account when its week reaches 90% (`alert_week_above`), cleared when the week resets (Codex's
weekly window lands in the same file: tests/codex_sandbox.py). Every provider call is faked. Refuses to run against a Hermes
home under ~/.hermes.
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
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in  # the real Hermes home, also on Windows
                  [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])):
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
SENT = []
core._notify = lambda title, body, icon="dialog-warning": SENT.append((title, body)) or ["desktop"]
failures = []
ROOT = Path(HOME)
LIMITS = ROOT / "account-pool-limits.json"
ALERTS = ROOT / "account-pool-alerts.json"


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


def limits(provider="anthropic"):
    return (json.loads(LIMITS.read_text()) if LIMITS.exists() else {}).get(provider) or {}


def alerts():
    return json.loads(ALERTS.read_text()) if ALERTS.exists() else {}


def entry(label, provider="anthropic"):
    return next((e for e in load_pool(provider).entries() if e.label == label), None)


def status(provider="anthropic"):
    api._NET.clear()
    core._reset_run_state()
    return c.get(f"/x/status?provider={provider}").json()


def row_of(st, label):
    return next(r for r in st["rotation"] + st["parked"] if r["label"] == label)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# ── three Anthropic OAuth accounts with fake usage ───────────────────────────
P = "anthropic"
FAR = 4102444800000                         # token expiry far ahead: nothing is refreshed
LABELS = ["alice@example.com", "bob@example.com", "carol@example.com"]
pool = load_pool(P)
for i, label in enumerate(LABELS):
    pool.add_entry(PooledCredential(provider=P, id=f"wk{i}000", label=label, auth_type="oauth", priority=i,
                                    source="manual:hermes_pkce", access_token=f"fake-at-{i}",
                                    refresh_token=f"fake-rt-{i}", expires_at_ms=FAR))
TOKEN = {f"fake-at-{i}": lab for i, lab in enumerate(LABELS)}
ANSWER = {}                                 # label -> usage answer (dict) or HTTP status
now = time.time()
FIVE_RESET, WEEK_RESET = now + 2 * 3600, now + 3 * 86400


def answer(five, week=None, opus=None, sonnet=None, five_reset=FIVE_RESET, week_reset=WEEK_RESET):
    out = {"five_hour": {"utilization": five, "resets_at": iso(five_reset) if five_reset else None}}
    if week is not None:
        out["seven_day"] = {"utilization": week, "resets_at": iso(week_reset) if week_reset else None}
    if opus is not None:
        out["seven_day_opus"] = {"utilization": opus, "resets_at": iso(week_reset)}
    if sonnet is not None:
        out["seven_day_sonnet"] = {"utilization": sonnet, "resets_at": iso(week_reset)}
    return out


def fake_get(entry, path):
    got = ANSWER.get(TOKEN.get(entry.access_token), 500)
    if isinstance(got, int):
        raise urllib.error.HTTPError("https://api.anthropic.com" + path, got, "fake", {}, io.BytesIO(b"{}"))
    return got


ad = core.providers.get(P)
ad._get = fake_get
fake = SimpleNamespace(access_token="fake-at-0", label="alice@example.com")

# ── the adapter ───────────────────────────────────────────────────────────────
ANSWER["alice@example.com"] = answer(20.0)
u = ad.usage(fake)
check(u == (20.0, FIVE_RESET) or (len(u) == 2 and u[0] == 20.0 and abs(u[1] - FIVE_RESET) < 1)
      and ad.last_week is None and ad.last_models == (),
      "an answer with only the 5-hour window reads as before (no weekly, no detail)")

ANSWER["alice@example.com"] = answer(20.0, week=60.0, opus=75.0, sonnet=5.0)
pct, reset, detail = ad.usage(fake)
check(pct == 60.0 and abs(reset - WEEK_RESET) < 1, "the headline is the fuller limit: the week, with the week's reset")
check(detail == "5h 20% · week 60% · Opus week 75% · Sonnet week 5%",
      f"detail names every limit ({detail!r})")
check(ad.last_window[0] == 20.0 and abs(ad.last_window[1] - FIVE_RESET) < 1,
      "the 5-hour window is still known on its own (idle detection, wake, tokens of this window)")
check(ad.last_week[0] == 60.0 and [m[0] for m in ad.last_models] == ["Opus week", "Sonnet week"],
      "the weekly and the model-family limits are kept for the core")

ANSWER["alice@example.com"] = answer(40.0, week=40.0)
pct, reset, _ = ad.usage(fake)
check(pct == 40.0 and abs(reset - FIVE_RESET) < 1, "a tie keeps the 5-hour window and its reset")

ANSWER["alice@example.com"] = answer(10.0, week=None, opus=99.0)
pct, reset, detail = ad.usage(fake)
check(pct == 10.0 and "Opus week 99%" in detail and ad.last_week is None,
      "a full model-family limit is shown but never becomes the headline")

ANSWER["alice@example.com"] = {"five_hour": {"utilization": 10.0, "resets_at": iso(FIVE_RESET)},
                               "seven_day": {"utilization": None, "resets_at": None}, "extra_usage": None}
u = ad.usage(fake)
check(len(u) == 2 and u[0] == 10.0 and ad.last_week is None, "a weekly entry without a number is ignored")

ANSWER["alice@example.com"] = {"seven_day": {"utilization": 50.0, "resets_at": iso(WEEK_RESET)}}
check(ad.usage(fake) is None and ad.last_error == "no 5-hour data in the answer" and ad.last_week is None,
      "no 5-hour data still reads as unavailable (nothing half-read is kept)")

# ── usage and balance ─────────────────────────────────────────────────────────
ANSWER.update({"alice@example.com": answer(10.0, week=95.0, opus=97.0),
               "bob@example.com": answer(30.0, week=40.0),
               "carol@example.com": answer(50.0, week=20.0)})
rc, out = run("usage")
check(rc == 0 and "[anthropic] 5-hour + weekly usage" in out, "usage names both limits in its header")
line = next((x for x in out.splitlines() if "alice@example.com" in x), "")
check("95%" in line and "(5h 10% · week 95% · Opus week 97%)" in line,
      f"usage shows the weekly headline and every limit ({line.strip()!r})")
check(limits().get("alice@example.com", {}).get("week", [None])[0] == 95.0,
      "usage keeps the newest weekly reading in account-pool-limits.json")
check(oct(LIMITS.stat().st_mode & 0o777) == "0o600" if os.name != "nt" else True, "the file is private (600)")

SENT.clear()
rc, out = run("balance", threshold=90.0)
check(rc == 0 and "bench alice@example.com (95% weekly) until" in out,
      f"balance benches an account whose week is full, saying it is the weekly limit ({out.strip()[:200]!r})")
ae = entry("alice@example.com")
check(ae.last_status == "exhausted" and "weekly usage 95% >= 90%" in (ae.last_error_message or "")
      and abs((ae.last_error_reset_at or 0) - WEEK_RESET) < 2,
      "Hermes holds it until the week resets, with a reason naming the weekly limit")
order = [e.label for e in core._rotation(P)]
check(order[-1] == "alice@example.com" and order[:2] == ["bob@example.com", "carol@example.com"],
      f"the order puts it last ({order})")
rec = limits()["alice@example.com"]
check(rec["week"][0] == 95.0 and abs(rec["week"][1] - WEEK_RESET) < 2 and rec["models"]["Opus week"][0] == 97.0,
      "balance writes the weekly and model-family readings")
hist = [json.loads(x) for x in (ROOT / "account-pool-history.jsonl").read_text().splitlines()]
check(hist[-1]["usage"]["alice@example.com"] == 95.0 and hist[-1]["win"]["alice@example.com"][0] == 10.0,
      "history keeps the headline and the 5-hour window next to it")

# ── alerts ────────────────────────────────────────────────────────────────────
wk_alerts = [t for t, _ in SENT if "weekly limit" in t]
check(wk_alerts == ["Hermes: alice@example.com used 95% of its weekly limit"],
      f"one weekly alert for the account ({wk_alerts})")
check(any("resets" in b and "weekly limit" in b for t, b in SENT if "weekly" in t), "it says when the week resets")
check("anthropic:week:wk0000" in alerts(), "the alert is remembered")
SENT.clear()
run("balance", threshold=90.0)
check(not [t for t, _ in SENT if "weekly" in t], "the next run does not repeat it")

ANSWER["alice@example.com"] = 500                    # unreadable for a run: cached 5-hour value, alert kept
SENT.clear()
run("balance", threshold=90.0)
check(not SENT and "anthropic:week:wk0000" in alerts(), "a run that cannot read the account keeps the alert, sends nothing")

cfg = core._config()
cfg["alert_week_above"] = 97
core._atomic_json(core._config_path(), cfg)
ANSWER["alice@example.com"] = answer(10.0, week=95.0)
run("balance", threshold=90.0)
check("anthropic:week:wk0000" not in alerts(), "alert_week_above is honoured (95% < 97%: cleared)")
cfg["alert_week_above"] = 90
core._atomic_json(core._config_path(), cfg)
SENT.clear()
run("balance", threshold=90.0)
check([t for t, _ in SENT if "weekly" in t] == ["Hermes: alice@example.com used 95% of its weekly limit"],
      "back above the limit: alerted again")

# the week resets: the old reading is void, the alert clears, the account comes back
NEW_WEEK = now + 7 * 86400
ANSWER["alice@example.com"] = answer(10.0, week=0.0, week_reset=NEW_WEEK)
SENT.clear()
rc, out = run("balance", threshold=90.0)
check("anthropic:week:wk0000" not in alerts() and not SENT, "after the reset the alert clears quietly")
check("release alice@example.com (10%)" in out and entry("alice@example.com").last_status != "exhausted",
      "and balance releases the account")
check(core._week_of(P, "alice@example.com")["pct"] == 0.0, "the new week reads 0%")

data = json.loads(LIMITS.read_text())
data[P]["bob@example.com"]["week"] = [80.0, now - 60]      # a reading whose week has reset since
LIMITS.write_text(json.dumps(data))
check(core._week_of(P, "bob@example.com")["pct"] is None, "a reading whose week reset since reads as unknown")

# parked accounts: read and shown, never alerted
ANSWER["alice@example.com"] = answer(10.0, week=20.0)
ANSWER["carol@example.com"] = answer(50.0, week=96.0)
rc, out = run("park", "carol@example.com")
SENT.clear()
run("balance", threshold=90.0)
check(limits()["carol@example.com"]["week"][0] == 96.0 and not [t for t, _ in SENT if "carol" in t]
      and not any(k.startswith("anthropic:week:wk2") for k in alerts()),
      "a parked account's week is recorded but never alerted on")

# ── page, who, notify, summary ────────────────────────────────────────────────
ANSWER["bob@example.com"] = answer(30.0, week=92.0, sonnet=12.0)
run("balance", threshold=90.0)
st = status()
bob = row_of(st, "bob@example.com")
check(bob["week"] and bob["week"]["pct"] == 92.0 and abs(bob["week"]["reset"] - WEEK_RESET) < 2
      and bob["week"]["models"][0][:2] == ["Sonnet week", 12.0],
      "page: the row carries the weekly limit, its reset and the model-family limits")
check(bob["window"]["pct"] == 30.0 and not bob["window"]["idle"], "page: the 5-hour window keeps its own percent")
check(row_of(st, "carol@example.com")["week"]["pct"] == 96.0, "page: parked rows carry it too")
check(st.get("alert_week_above") == 90, "page: the alert limit is sent for the week tag colour")
kinds = [a for a in st.get("alerts", []) if a.get("kind") == "week"]
check(kinds and kinds[0]["label"] == "bob@example.com" and "92% of its weekly limit" in kinds[0]["text"],
      f"page: the open weekly alert is listed ({kinds})")
check(bob["tokens"] is not None, "page: tokens still computed")

rc, out = run("who")
line = next((x for x in out.splitlines() if "bob@example.com" in x), "")
check("week 92%, resets" in line, f"who shows the weekly limit per account ({line.strip()!r})")

rc, out = run("notify")
check("when an account's weekly limit reaches 90%" in out, "notify status names the weekly alert")
title, body = core._summary(P)
wline = next((x for x in body.splitlines() if x.startswith("Weekly limit:")), "")
check(wline.startswith("Weekly limit: bob 92% (resets ") and "carol" not in wline,
      f"the daily summary lists the fullest weeks of accounts in rotation ({wline!r})")

st_n = c.get("/x/notify?provider=anthropic")
check(st_n.status_code == 200 and st_n.json().get("alert_week_above") == 90,
      "page notify settings carry alert_week_above")

# a dry run reads but writes nothing
before = LIMITS.read_text()
ANSWER["bob@example.com"] = answer(30.0, week=93.0)
run("balance", threshold=90.0, dry_run=True)
check(LIMITS.read_text() == before, "balance --dry-run writes no weekly reading")

# an account gone for two weeks is dropped from the file
data = json.loads(LIMITS.read_text())
data[P]["gone@example.com"] = {"ts": now - 15 * 86400, "week": [10.0, now + 86400], "models": {}}
LIMITS.write_text(json.dumps(data))
run("balance", threshold=90.0)
check("gone@example.com" not in limits(), "a reading older than two weeks is dropped")

# ── load, pace and peak stay in 5-hour-window percent ────────────────────────
check(core._window_usage({"usage": {"a": 60.0, "b": 5.0, "c": 70.0}, "win": {"a": [12.0, None]}, "parked": ["c"]})
      == {"a": 12.0, "b": 5.0}, "the 5-hour value of a snapshot: from `win` when the week was the headline")
t0 = time.time()
recs = [{"ts": t0 - 1800, "usage": {"alice@example.com": 60.0, "bob@example.com": 5.0},
         "reset": {"alice@example.com": WEEK_RESET, "bob@example.com": FIVE_RESET},
         "win": {"alice@example.com": [10.0, FIVE_RESET]}},
        {"ts": t0 - 900, "usage": {"alice@example.com": 60.0, "bob@example.com": 5.0},
         "reset": {"alice@example.com": WEEK_RESET, "bob@example.com": FIVE_RESET},
         "win": {"alice@example.com": [20.0, FIVE_RESET]}},
        {"ts": t0 - 60, "usage": {"alice@example.com": 61.0, "bob@example.com": 5.0},
         "reset": {"alice@example.com": WEEK_RESET, "bob@example.com": FIVE_RESET},
         "win": {"alice@example.com": [30.0, FIVE_RESET]}}]
real_read = core._read_history
core._read_history = lambda *a, **k: [dict(r) for r in recs]
try:
    rep = core._report_data(P, 1)
    alice = next(a for a in rep["accounts"] if a["label"] == "alice@example.com")
    check(rep["window"] == "5-hour" and alice["used"] == 20.0 and alice["peak"] == 30.0,
          f"report: load and peak count the 5-hour window, not the week ({alice['used']}, {alice['peak']})")
    fc = core._forecast(P)
    check(fc["status"] == "ok" and abs(fc["pace"] - 20 / 29 * 60) < 0.2 and "of one 5-hour window per hour" in fc["text"],
          f"forecast: the pace is in 5-hour-window percent ({fc['text']!r})")
    recs[-1]["usage"].update({"alice@example.com": 95.0, "bob@example.com": 85.0})
    recs[-1]["reset"]["bob@example.com"] = FIVE_RESET + 600
    fc = core._forecast(P)
    check(fc["full_at"] and abs(fc["back_at"] - (FIVE_RESET + 600)) < 2,
          "forecast: a full week keeps the account full (the pool is full once bob fills; back when bob's window resets)")
    ch = core._chart_data(P, 2)
    check(ch["window"] == "5-hour" and abs(sum(sum(d["used"]) for d in ch["days"]) - (20.0 + 80.0)) < 0.01,
          "chart: quota used per hour is 5-hour-window percent (alice's window +20, bob +80; not alice's week)")
finally:
    core._read_history = real_read

print()
print(f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
