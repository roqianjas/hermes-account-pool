"""Token counting and session tracking: the session tracker's files, `report`, and the Accounts page backend.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/tokens_sandbox.py
    rm -rf "$SB"

Feeds the tracker's post_api_request hook the same keyword arguments Hermes passes, with a fake
agent and fake API-key accounts, so no request reaches a provider. Refuses to run against a
Hermes home under ~/.hermes (see CONTRIBUTING.md).
"""
import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import time
from pathlib import Path

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


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


pool = load_pool("anthropic")
for i, label in enumerate(["alice@example.com", "bob@example.com"]):
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
    def __init__(self, label, session):
        self._credential_pool = FakePool(entries[label])
        self.session_id = session
        self.platform = "cli"
        self.model = "fake-model"


def call(label, usage, provider="anthropic", session="s1"):
    agent = FakeAgent(label, session)  # noqa: F841  (the tracker finds it on this frame)
    tracker._on_api_request(session_id=session, platform="cli", model="fake-model", provider=provider, usage=usage)


U = {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 1000, "cache_write_tokens": 10,
     "reasoning_tokens": 5, "prompt_tokens": 1110, "total_tokens": 1160}
call("alice@example.com", U)
call("alice@example.com", U)
call("bob@example.com", dict(U, input_tokens=7, output_tokens=3, cache_read_tokens=0, cache_write_tokens=0), session="s2")
call("bob@example.com", U, provider="openai-codex", session="s2")           # a fallback: not this pool's account
call("bob@example.com", None, session="s2")                                   # no usage in the response
call("bob@example.com", dict.fromkeys(U, 0), session="s2")                    # empty usage
call("bob@example.com", {"input_tokens": "<redacted>"}, session="s2")         # junk must not raise

path = Path(HOME) / "account-pool-tokens.json"
check(path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600, "token file written with mode 600")
raw = path.read_text()
check(not any(s in raw for s in ("fake-key", "access_token", "refresh_token")), "no credential in the token file")
buckets, since = core._token_buckets("anthropic")
day = {label: core._token_sum(rows, time.time() - 86400) for label, rows in buckets.items()}
check(day["alice@example.com"]["total"] == 2320 and day["alice@example.com"]["requests"] == 2,
      "two calls on alice: 2 x 1160 tokens, 2 requests")
check(day["bob@example.com"] == {"input": 7, "output": 3, "cache_read": 0, "cache_write": 0, "requests": 1, "total": 10},
      "bob: one counted call; fallback, empty and junk usage not counted")
check(since and abs(since - time.time()) < 60, "counting start recorded")
sessions = json.loads((Path(HOME) / "account-pool-sessions.json").read_text())["sessions"]
check({v["account"] for v in sessions.values()} == {"alice@example.com", "bob@example.com"}, "session tracking unchanged")

# old buckets are dropped
data = json.loads(raw)
old = str(int((time.time() - 9 * 86400) // 900 * 900))
data["counts"]["anthropic"]["alice@example.com"]["default"]["fake-model"][old] = [1, 1, 1, 1, 1]
data["counts"].setdefault("openai-codex", {})["gone@example.com"] = {"default": {"fake-model": {old: [1, 1, 1, 1, 1]}}}
path.write_text(json.dumps(data))
call("alice@example.com", U)
data = json.loads(path.read_text())
check(old not in data["counts"]["anthropic"]["alice@example.com"]["default"]["fake-model"] and "openai-codex" not in data["counts"],
      "buckets older than 8 days dropped, empty accounts and providers removed")

# backend: per-account tokens on the Accounts page
st = c.get("/x/status").json()
rows = {r["label"]: r for r in st["rotation"]}
check(rows["alice@example.com"]["tokens"]["day"]["total"] == 3480 and rows["bob@example.com"]["tokens"]["day"]["total"] == 10,
      "status: tokens of the last 24 h per account")
check(st["tokens"]["day"]["total"] == 3490 and st["tokens"]["day"]["requests"] == 4, "status: pool total")
check(rows["alice@example.com"]["tokens"]["window"] is None, "no window total without a known reset time")
check(not any(s in json.dumps(st) for s in ("fake-key", "access_token", "refresh_token")), "no token in status")

# window total: buckets from the start of the current 5-hour window on
now = time.time()
rows_a = {now - 6 * 3600: [1000, 0, 0, 0, 1], now - 3600: [10, 20, 30, 40, 2]}
reset = now + 4 * 3600                                  # window started 1 h ago
win = core._token_sum(rows_a, reset - 5 * 3600 - core.TOKEN_BUCKET + 1)
check(win["total"] == 100 and win["requests"] == 2, "window total leaves out calls before the window")

# report: history from the balance timer + tokens
hist = Path(HOME) / "account-pool-history.jsonl"
with hist.open("w") as fh:
    for k, (a, b) in enumerate([(10, 5), (20, 5), (35, 6)]):
        fh.write(json.dumps({"ts": now - 3600 + k * 300, "provider": "anthropic",
                             "usage": {"alice@example.com": a, "bob@example.com": b}}) + "\n")
rep = c.get("/x/report?hours=24").json()
acc = {a["label"]: a for a in rep["accounts"]}
check(rep["tokens_total"]["total"] == 3490 and acc["alice@example.com"]["tokens"]["total"] == 3480,
      "report: tokens per account and in total")
out = io.StringIO()
with contextlib.redirect_stdout(out):
    core._cmd_report(type("A", (), {"provider": "anthropic", "hours": 24.0, "json": False})())
text = out.getvalue()
check("3.5k" in text and "Tokens through Hermes:" in text and "4 requests" in text, "`report` prints the tokens")
check(core._fmt_tokens(999) == "999" and core._fmt_tokens(1234) == "1.2k" and core._fmt_tokens(2_500_000) == "2.5M",
      "compact token numbers")

# session tracking: when a session started on its account, and a move to another account
first = json.loads((Path(HOME) / "account-pool-sessions.json").read_text())["sessions"]["default:s1"]
check(first.get("account_since") == first["first_seen"], "a new session is on its account since it started")
time.sleep(1.1)
call("bob@example.com", U, session="s1")
moved = json.loads((Path(HOME) / "account-pool-sessions.json").read_text())["sessions"]["default:s1"]
check(moved["account"] == "bob@example.com" and moved["previous_account"] == "alice@example.com"
      and moved["account_since"] > first["first_seen"] and moved["first_seen"] == first["first_seen"],
      "a session that moves gets a new account_since and keeps its first_seen")
row = next(s for r in c.get("/x/status").json()["rotation"] if r["label"] == "bob@example.com"
           for s in r["sessions"] if s["session"] == "s1")
check(row["since"] == moved["account_since"] and row["moved_from"] == "alice@example.com", "status: session since and moved from")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
