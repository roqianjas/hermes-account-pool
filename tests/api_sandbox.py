"""Backend test of the Hermes Desktop page (dashboard/plugin_api.py) in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/api_sandbox.py
    rm -rf "$SB"

Uses fake API-key accounts and a fake sign-in, so no request reaches a provider. Refuses to run
against a Hermes home under ~/.hermes (see CONTRIBUTING.md: such a home can read the real pool).
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

from agent.credential_pool import PooledCredential, load_pool  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

API = Path(__file__).resolve().parent.parent / "plugins" / "account-pool" / "dashboard" / "plugin_api.py"
spec = importlib.util.spec_from_file_location("hap_api", API)
assert spec and spec.loader
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
core = api.core
app = FastAPI()
app.include_router(api.router, prefix="/x")
c = TestClient(app)
failures = []


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def post(path, body):
    r = c.post("/x" + path, json=body)
    return r.status_code, r.json()


def act(action, target=None, **kw):
    return post("/action", dict(action=action, provider="anthropic", target=target, **kw))[1]


def labels():
    st = c.get("/x/status").json()
    return [r["label"] for r in st["rotation"]], [r["label"] for r in st["parked"]]


# ── fake API-key accounts: park, unpark, remove, guards, rate limits ─────────
pool = load_pool("anthropic")
for i, label in enumerate(["alice@example.com", "bob@example.com", "carol@example.com"]):
    pool.add_entry(PooledCredential(provider="anthropic", id=f"fake{i}0", label=label, auth_type="api_key",
                                    priority=i, source="manual", access_token=f"fake-key-{i}"))

check(labels() == (["alice@example.com", "bob@example.com", "carol@example.com"], []), "status lists 3 accounts")
blob = json.dumps([c.get("/x/status").json(), c.get("/x/summary").json()])
check(not any(s in blob for s in ("fake-key", "access_token", "refresh_token")), "no token in status or summary")
check(c.get("/x/status?provider=nope").status_code == 400, "unknown provider refused")
check(act("park", "bob@example.com", until="+2h")["ok"], "park with --until")
check(labels()[1] == ["bob@example.com"] and c.get("/x/status").json()["parked"][0]["until"], "parked with a return time")
check(not act("park", "bob@example.com")["ok"], "park twice refused")
check("Cannot read --until" in act("park", "alice@example.com", until="25:99")["output"], "bad --until refused")
check(act("unpark", "bob@example.com")["ok"] and "bob@example.com" in labels()[0], "unpark")
check(act("remove", "carol@example.com")["ok"] and "carol@example.com" not in labels()[0], "remove")
check(act("park", "alice@example.com")["ok"], "park alice")
check("last working" in act("park", "bob@example.com")["output"], "last working account cannot be parked")
check("last working" in act("remove", "bob@example.com")["output"], "last working account cannot be removed")
check(act("remove", "alice@example.com")["ok"] and labels() == (["bob@example.com"], []), "remove a parked account")
check(act("balance")["ok"], "balance runs")
check(act("balance")["rc"] == 2, "second balance within a minute refused")
check(post("/action", {"action": "add", "provider": "anthropic"})[0] == 400, "unknown action refused")
first, second = post("/live", {"provider": "anthropic"})[1], post("/live", {"provider": "anthropic"})[1]
check(first["ok"] and not second["ok"] and second["retry_after"] > 100, "live usage at most once per 2 minutes")
check(any(ch["level"] == "ok" for ch in post("/doctor", {"provider": "anthropic"})[1]["checks"]), "doctor answers")
check(c.get("/x/report?hours=0").status_code == 400, "report hours validated")

# ── sign-in start guards (real start: builds a URL, no request) ──────────────
code, s = post("/signin/start", {"provider": "anthropic", "mode": "add", "target": "dave@example.com"})
check(code == 200 and s["kind"] == "code" and s["url"].startswith("https://claude.ai/oauth/authorize?"), "sign-in link")
check("verifier" not in json.dumps(s), "PKCE verifier stays on the server")
check(post("/signin/step", {"flow": s["flow"], "code": ""})[1]["status"] == "error", "empty code refused")
check("another sign-in" in post("/signin/step", {"flow": s["flow"], "code": "abc#x"})[1]["message"], "state checked")
post("/signin/cancel", {"flow": s["flow"]})
check("expired" in post("/signin/step", {"flow": s["flow"], "code": "abc#x"})[1]["message"], "cancel drops the flow")
check(post("/signin/start", {"provider": "anthropic", "mode": "add", "target": "bob@example.com"})[0] == 400,
      "add of an account in rotation refused")
check(post("/signin/start", {"provider": "anthropic", "mode": "add", "target": "dave"})[0] == 400, "add needs an email")
check("API key" in post("/signin/start", {"provider": "anthropic", "mode": "relogin",
                                          "target": "bob@example.com"})[1]["detail"], "relogin of an API key refused")

# ── save path with a fake sign-in: verification, duplicates, relogin swap ────
TOK = {}
cls = type(core.providers.get("anthropic"))
cls.signin_start = lambda self: {"kind": "code", "url": "https://example.invalid/", "state": {}}
cls.signin_step = lambda self, state, code="": {"access_token": f"fake-at-{code}", "refresh_token": "fake-rt",
                                                  "expires_at_ms": 4102444800000}
core._identity = lambda provider, entry: TOK.get(entry.access_token)
core._has_usage = lambda provider: False


def signin(mode, target, ident, code):
    TOK[f"fake-at-{code}"] = ident
    r = c.post("/x/signin/start", json={"provider": "anthropic", "mode": mode, "target": target})
    if r.status_code != 200:
        return "refused", r.json()["detail"]
    flow = r.json()["flow"]
    out = c.post("/x/signin/step", json={"flow": flow, "code": code}).json()
    again = c.post("/x/signin/step", json={"flow": flow, "code": code}).json()
    check(again["status"] == "error", f"flow {code} cannot be finished twice")
    return out["status"], out.get("output", "")


def entries():
    return [(e.label, e.id) for e in sorted(core._pool("anthropic").entries(), key=lambda e: e.priority)]


check(signin("add", "dave@example.com", "dave@example.com", "a1")[0] == "done", "add verified account")
check(signin("add", "erin@example.com", "zoe@example.com", "a2")[0] == "rejected", "add as another account discarded")
check(signin("add", "frank@example.com", "dave@example.com", "a3")[0] == "rejected", "second sign-in of a pooled account discarded")
check(signin("add", "gina@example.com", None, "a4")[0] == "done", "add without identity kept with a warning")
before = entries()
check(signin("relogin", "dave@example.com", "erin@example.com", "r1")[0] == "rejected" and entries() == before,
      "relogin as another account leaves the pool unchanged")
check(signin("relogin", "dave@example.com", "dave@example.com", "r2")[0] == "done", "relogin")
after = entries()
check([l for l, _ in after] == [l for l, _ in before] and after != before, "relogin keeps label and position, new id")
auth = json.loads((Path(HOME) / "auth.json").read_text())
toks = [e.get("access_token") for e in auth["credential_pool"]["anthropic"]]
check("fake-at-r2" in toks and "fake-at-r1" not in toks and "fake-at-a2" not in toks, "only accepted sign-ins saved")

# ── rotation mode: Hermes' credential_pool_strategies per profile ──────────
mode = c.get("/x/status").json()["rotation_mode"]
check(mode["default"] == "fill_first" and not mode["other"], "rotation mode: fill_first when unset")
w = Path(HOME) / "profiles" / "worker-1"
w.mkdir(parents=True)
(w / "config.yaml").write_text("credential_pool_strategies:\n  anthropic: Round_Robin\n")
(Path(HOME) / "profiles" / "worker-2").mkdir()
(Path(HOME) / "profiles" / "worker-2" / "config.yaml").write_text("credential_pool_strategies:\n  anthropic: bogus\n")
mode = c.get("/x/status").json()["rotation_mode"]
check([(r["profile"], r["strategy"]) for r in mode["other"]] == [("worker-1", "round_robin")],
      "rotation mode: a round_robin profile is reported, an unknown value counts as fill_first (as in Hermes)")
doc = [t for _, t in core._doctor_checks("anthropic") if t.startswith("strategy")]
check(doc == ["strategy is not fill_first: worker-1=Round_Robin, worker-2=bogus (balance order is ignored there). "
              "Fix: hermes -p <profile> config set credential_pool_strategies.anthropic fill_first"],
      "doctor strategy line unchanged")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
