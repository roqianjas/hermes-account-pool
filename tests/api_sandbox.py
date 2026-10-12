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
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in  # the real Hermes home, also on Windows
                  [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])):
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
cls.signin_start = lambda self, method=None: {"kind": "code", "url": "https://example.invalid/", "state": {}}
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

# ── openai-codex sign-in from the page: browser (loopback) and device code ──
import socket  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

from hermes_cli import auth_codex  # noqa: E402

cx = core.providers.get("openai-codex")
CX = type(cx)
CX.callback_port = 0                      # a free port: the real 1455 stays out of the test
CX._exchange = lambda self, code, redirect_uri, verifier: {"access_token": f"cx-at-{code}", "refresh_token": "cx-rt"}
st = c.get("/x/status?provider=openai-codex").json()
check(st["web_signin"] and st["signin_methods"] == ["browser", "device"], "codex: page sign-in, browser first")
check(c.get("/x/status").json()["signin_methods"] == ["code"], "anthropic: pasted code only")
check(post("/signin/start", {"provider": "openai-codex", "mode": "add", "target": "x@example.com",
                             "method": "sms"})[0] == 400, "codex: unknown sign-in method refused")


def cx_start(mode, target, method="browser"):
    code, s = post("/signin/start", {"provider": "openai-codex", "mode": mode, "target": target, "method": method})
    assert code == 200, s
    return s


def callback(url, **q):
    redirect = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["redirect_uri"][0]
    try:
        with urllib.request.urlopen(redirect + "?" + urllib.parse.urlencode(q), timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as x:
        return x.code, x.read().decode()


def cx_state(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]


def step(flow, code=""):
    return post("/signin/step", {"flow": flow, "code": code})[1]


def port_free(url):
    port = urllib.parse.urlparse(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["redirect_uri"][0]).port
    with socket.socket() as so:
        so.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)      # as the listener itself binds
        try:
            so.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


s = cx_start("add", "cara@example.com")
q = urllib.parse.parse_qs(urllib.parse.urlparse(s["url"]).query)
check(s["kind"] == "browser" and s["listening"] and s["url"].startswith("https://auth.openai.com/oauth/authorize?")
      and q["client_id"] == [auth_codex.CODEX_OAUTH_CLIENT_ID] and q["code_challenge_method"] == ["S256"]
      and q["redirect_uri"][0].startswith("http://localhost:") and q["redirect_uri"][0].endswith("/auth/callback")
      and "offline_access" in q["scope"][0], "codex browser: authorize link with PKCE and the loopback redirect")
check("verifier" not in json.dumps(s), "codex browser: PKCE verifier stays on the server")
check(step(s["flow"]) == {"status": "pending"}, "codex browser: pending until the browser comes back")
code, page = callback(s["url"], code="zz", state="forged")
check(code == 400 and "Not this sign-in" in page and step(s["flow"])["status"] == "pending",
      "codex browser: a callback with another state is refused and ignored")
TOK["cx-at-c1"] = "cara@example.com"
code, page = callback(s["url"], code="c1", state=cx_state(s["url"]))
check(code == 200 and "Signed in to OpenAI Codex" in page, "codex browser: the callback page says signed in")
out = step(s["flow"])
pool_cx = core._pool("openai-codex").entries()
check(out["status"] == "done" and [e.label for e in pool_cx] == ["cara@example.com"]
      and pool_cx[0].source.endswith("loopback_pkce") and pool_cx[0].access_token == "cx-at-c1",
      "codex browser: added, verified, saved like Hermes' own browser sign-in")
check(step(s["flow"])["final"] and port_free(s["url"]), "codex browser: flow gone, listener closed")

s = cx_start("add", "dan@example.com")
TOK["cx-at-c2"] = "eve@example.com"
callback(s["url"], code="c2", state=cx_state(s["url"]))
out = step(s["flow"])
check(out["status"] == "rejected" and [e.label for e in core._pool("openai-codex").entries()] == ["cara@example.com"],
      "codex browser: a sign-in as another account is discarded")

s = cx_start("relogin", "cara@example.com")
redirect = urllib.parse.parse_qs(urllib.parse.urlparse(s["url"]).query)["redirect_uri"][0]
r = step(s["flow"], "https://example.invalid/whatever")
check(r["status"] == "error" and not r["final"] and "whole address" in r["message"], "codex paste: not an address")
r = step(s["flow"], f"{redirect}?code=c3&state=forged")
check(r["status"] == "error" and not r["final"] and "another sign-in" in r["message"], "codex paste: state checked")
TOK["cx-at-c3"] = "cara@example.com"
old_id = core._pool("openai-codex").entries()[0].id
r = step(s["flow"], f"{redirect}?code=c3&scope=openid&state={cx_state(s['url'])}")
new = core._pool("openai-codex").entries()
check(r["status"] == "done" and [e.label for e in new] == ["cara@example.com"] and new[0].id != old_id
      and new[0].access_token == "cx-at-c3", "codex paste: the pasted address signs in again, same label, new id")

s = cx_start("add", "fay@example.com")
callback(s["url"], error="access_denied", error_description="User cancelled", state=cx_state(s["url"]))
r = step(s["flow"])
check(r["status"] == "error" and r["final"] and "User cancelled" in r["message"] and port_free(s["url"]),
      "codex browser: a refused sign-in ends the flow and frees the port")

s = cx_start("add", "fay@example.com")
post("/signin/cancel", {"flow": s["flow"]})
check(port_free(s["url"]) and step(s["flow"])["final"], "codex browser: cancel frees the port")
s1 = cx_start("add", "fay@example.com")
s2 = cx_start("add", "gus@example.com")
check(step(s1["flow"])["final"] and port_free(s1["url"]) and step(s2["flow"])["status"] == "pending",
      "codex browser: a new browser sign-in replaces an older one (one listener)")
post("/signin/cancel", {"flow": s2["flow"]})

with socket.socket() as busy:
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    CX.callback_port = busy.getsockname()[1]
    s = cx_start("add", "hal@example.com")
    check(s["listening"] is False and f"localhost%3A{CX.callback_port}" in s["url"],
          "codex browser: port taken, the page falls back to the pasted address")
    TOK["cx-at-c4"] = "hal@example.com"
    r = step(s["flow"], f"http://localhost:{CX.callback_port}/auth/callback?code=c4&state={cx_state(s['url'])}")
    check(r["status"] == "done", "codex browser: pasted address works without a listener")
    CX.callback_port = 0

answers = []
auth_codex._codex_request_device_code = lambda issuer, client_id: {
    "device_auth_id": "dev-1", "user_code": "WXYZ-1234", "interval": 5}


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **k):
        answers.append(url)
        status = 403 if len(answers) == 1 else 200
        return type("R", (), {"status_code": status, "json": lambda self: {"authorization_code": "ac", "code_verifier": "cv"}})()


auth_codex._codex_http_client = FakeClient
auth_codex._codex_exchange_authorization_code = lambda issuer, client_id, body: {
    "access_token": "cx-at-dev", "refresh_token": "cx-rt-dev"}
TOK["cx-at-dev"] = "ivy@example.com"
s = cx_start("add", "ivy@example.com", "device")
check(s["kind"] == "device" and s["user_code"] == "WXYZ-1234" and s["url"] == "https://auth.openai.com/codex/device",
      "codex device: code and page")
flow_state = api._FLOWS[s["flow"]]["state"]
check(step(s["flow"]) == {"status": "pending"}, "codex device: pending while not confirmed")
check(step(s["flow"]) == {"status": "pending"} and len(answers) == 1, "codex device: no check before the interval")
flow_state["last"] = 0
r = step(s["flow"])
dev = [e for e in core._pool("openai-codex").entries() if e.label == "ivy@example.com"]
check(r["status"] == "done" and dev and dev[0].source.endswith("device_code"), "codex device: confirmed, added")
auth = json.loads((Path(HOME) / "auth.json").read_text())
check(sorted(e["label"] for e in auth["credential_pool"]["openai-codex"]) == ["cara@example.com", "hal@example.com",
                                                                            "ivy@example.com"],
      "codex: only the accepted sign-ins saved")

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
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "strateg" in t]
check(doc == [("fail", "strategy is not fill_first: worker-1=Round_Robin (balance order is ignored there). "
                       "Fix: hermes account anthropic strategy fill_first"),
              ("warn", "unknown strategy value: worker-2=bogus (Hermes uses fill_first). "
                       "Fix: hermes account anthropic strategy fill_first")],
      "doctor: round_robin fails, an unknown value only warns (Hermes reads it as fill_first)")

# ── changing the strategy from the page (Hermes' own config writer) ─────────
import hashlib  # noqa: E402
real = [p for p in [Path.home() / ".hermes" / "config.yaml", *sorted((Path.home() / ".hermes" / "profiles").glob("*/config.yaml"))]
        if p.exists()]
real_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in real}
(w / "config.yaml").write_text("# kept comment\ncredential_pool_strategies:\n  anthropic: Round_Robin\n")


def strat(name):
    return dict(core._strategies("anthropic")).get(name)


check(post("/action", {"action": "strategy", "provider": "anthropic"})[0] == 400, "strategy without a value refused")
r = act("strategy", "sideways")
check(not r["ok"] and r["rc"] == 2 and "not a strategy" in r["output"], "unknown strategy refused")
r = act("strategy", "fill_first", only=["nobody"])
check(not r["ok"] and "No profile named nobody" in r["output"], "unknown profile refused")
r = act("strategy", "fill_first", only=["worker-1"])
check(r["ok"] and "fill_first in worker-1 (was Round_Robin)" in r["output"] and strat("worker-1") == "fill_first"
      and strat("worker-2") == "bogus", "fill_first for one profile; the others untouched")
check((w / "config.yaml").read_text().startswith("# kept comment"), "Hermes' writer keeps the rest of config.yaml")
check(not c.get("/x/status").json()["rotation_mode"]["other"], "status: no profile off fill_first any more")
r = act("strategy", "fill_first", only="worker-1")
check(r["ok"] and "Nothing to change" in r["output"], "setting the same value again changes nothing")
r = act("strategy", "least_used")
check(r["ok"] and all(strat(n) == "least_used" for n in ("default", "worker-1", "worker-2")) and "WARNING" in r["output"]
      and "strategy fill_first" in r["output"], "page sets every profile without a prompt, with the warning and the way back")
mode = c.get("/x/status").json()["rotation_mode"]
check(mode["default"] == "least_used" and len(mode["other"]) == 3, "status follows the new strategy")
check(act("strategy", "fill_first")["ok"] and not c.get("/x/status").json()["rotation_mode"]["other"], "back to fill_first everywhere")
check(real_before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in real}, "the real Hermes configs were not touched")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
