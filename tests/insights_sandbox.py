"""The session tracker check, in a throwaway Hermes home.

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

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
