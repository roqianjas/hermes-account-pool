"""Wake (start an idle account's 5-hour window) and email masking, in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/wake_privacy_sandbox.py
    rm -rf "$SB"

Covers the command, the balance timer's automatic wake, the page routes, Anthropic's request through
Hermes' own client and Codex's request on the Responses endpoint. Every provider call is faked, so no
request leaves the computer. Refuses to run against a Hermes home under ~/.hermes.
"""
import base64
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
os.environ["XDG_CONFIG_HOME"] = str(Path(HOME) / "xdg")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

import agent.anthropic_adapter as anthropic_adapter  # noqa: E402
from agent.credential_pool import PooledCredential, load_pool  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from hermes_cli import codex_models  # noqa: E402
from hermes_cli import models as hermes_models  # noqa: E402

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


def post(path, body):
    api._NET.clear()
    r = c.post("/x" + path, json=body)
    return r.status_code, r.json()


def state():
    p = ROOT / "account-pool-state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def activity():
    p = ROOT / "account-pool-activity.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ── masking rule ─────────────────────────────────────────────────────────────
m = core._mask_email
check(m("alice@example.com") == "al•••e@e•••.com", "mask: first two and last letter, domain initial and TLD")
check(m("ann@example.com") == "a•••@e•••.com" and m("bobo@example.com") == "b•••@e•••.com",
      "mask: a short name keeps only its first letter")
check(m("bob.smith@mail.example.com") == "bo•••h@m•••.com", "mask: a subdomain is hidden too")
text = "moved from alice@example.com to bob.smith@mail.example.com (ann@example.com)"
masked = core._mask(text)
check("@example.com" not in masked and core._mask(masked) == masked, "mask: every email in a text, idempotent")
check(core._mask("no email here, user@localhost") == "no email here, user@localhost", "mask: only real emails")

# ── accounts: Anthropic OAuth with fake usage and a fake Hermes client ───────
P = "anthropic"
FAR = 4102444800000                         # token expiry far ahead: nothing is refreshed
pool = load_pool(P)
for i, (label, status) in enumerate([("alice@example.com", None), ("bob@example.com", None),
                                     ("carol@example.com", None), ("dave@example.com", "dead")]):
    pool.add_entry(PooledCredential(provider=P, id=f"an{i}000", label=label, auth_type="oauth", priority=i,
                                    source="manual:hermes_pkce", access_token=f"fake-at-{i}",
                                    refresh_token=f"fake-rt-{i}", expires_at_ms=FAR, last_status=status))
pool.add_entry(PooledCredential(provider=P, id="an9000", label="erin@example.com", auth_type="api_key", priority=4,
                                source="manual", access_token="fake-key-9"))
TOKEN = {f"fake-at-{i}": lab for i, lab in enumerate(["alice@example.com", "bob@example.com", "carol@example.com",
                                                       "dave@example.com"])}


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


FIVE = {}                                   # label -> (utilization, resets_at epoch or None) or HTTP status


def fake_get(entry, path):
    got = FIVE.get(TOKEN.get(entry.access_token), 500)
    if isinstance(got, int):
        raise urllib.error.HTTPError("https://api.anthropic.com" + path, got, "fake", {}, io.BytesIO(b"{}"))
    util, reset = got
    return {"five_hour": {"utilization": util, "resets_at": iso(reset) if reset else None}}


ad = core.providers.get(P)
ad._get = fake_get
SENT = []                                   # (label, create kwargs)
FAIL = {}                                   # label -> exception to raise


class FakeClient:
    def __init__(self, token):
        self.token = token
        self.messages = self

    def create(self, **kw):
        label = TOKEN.get(self.token)
        if label in FAIL:
            raise FAIL[label]
        SENT.append((label, kw))
        return SimpleNamespace(content=[])


anthropic_adapter.build_anthropic_client = lambda token, base_url=None, timeout=None, **kw: FakeClient(token)


class RateLimited(Exception):
    status_code = 429
    body = {"error": {"message": "rate_limit_error"}}


now = time.time()
FIVE.update({"alice@example.com": (0.0, None), "bob@example.com": (20.0, now + 7200),
             "carol@example.com": (0.0, None)})

# ── wake status and settings ─────────────────────────────────────────────────
rc, out = run("wake", "status")
check(rc == 0 and "automatic: off" in out and "claude-haiku-4-5 (default)" in out, "wake status: off, default model")
rc, out = run("wake", "model=claude-haiku-4-5-20251001")
check(rc == 0 and "claude-haiku-4-5-20251001" in out and core._wake_cfg(P)["model"] == "claude-haiku-4-5-20251001",
      "wake model=<id> saved")
rc, out = run("wake", "model=bad model!")
check(rc == 2 and "model= takes a model id" in out, "a bad model id is refused")
rc, out = run("wake", "model=default")
check(rc == 0 and core._wake_cfg(P)["model"] == "", "wake model=default goes back to the adapter's model")
rc, out = run("wake", "auto-on", dry_run=True)
check(rc == 2 and not core._wake_cfg(P)["auto"], "--dry-run does not apply to settings")

# ── the model list (Hermes' /v1/models fetcher, faked) ───────────────────────
MLIST = {"ids": ["claude-opus-4-5-20251101", "claude-haiku-4-5", "claude-haiku-4-5-20251001"], "fail": set()}
MCALLS = []


def fake_models(timeout=5.0, *, base_url=None, api_key=None):
    MCALLS.append((api_key, timeout))
    if api_key in MLIST["fail"]:
        raise urllib.error.URLError("offline")
    return list(MLIST["ids"]) if MLIST["ids"] else None


hermes_models._fetch_anthropic_models = fake_models
rc, out = run("wake", "models")
check(rc == 0 and "claude-opus-4-5-20251101" in out and "  claude-haiku-4-5  (default)" in out
      and "the account's own list, read now" in out, "wake models: the account's list, the default marked")
check(MCALLS == [("fake-at-0", 10)], "wake models: read once, through the first signed-in account in rotation")
check(state().get(f"models:{P}", {}).get("ids") == MLIST["ids"], "wake models: the live list is saved")
MCALLS.clear()
MLIST["fail"] = {"fake-at-0"}
rc, out = run("wake", "models")
check(rc == 0 and [k for k, _ in MCALLS] == ["fake-at-0", "fake-at-1"] and "read now" in out,
      "wake models: a second account when the first one's request fails")
MLIST["fail"], MLIST["ids"] = set(), None
rc, out = run("wake", "models")
check(rc == 0 and "saved " in out and "the provider returned no model list" in out and "claude-opus-4-5-20251101" in out,
      "wake models: the saved list when the live one cannot be read, said why")
saved_models = state()[f"models:{P}"]
st = state()
st.pop(f"models:{P}")
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
rc, out = run("wake", "models")
check(rc == 1 and "no model list" in out and "claude-haiku-4-5 (default)" in out, "wake models: no list at all, said so")
st = state()
st[f"models:{P}"] = saved_models
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
MLIST["ids"] = ["claude-opus-4-5-20251101", "claude-haiku-4-5", "claude-haiku-4-5-20251001"]
rc, out = run("wake", "model=claude-made-up-1")
check(rc == 0 and core._wake_cfg(P)["model"] == "claude-made-up-1" and "is not in the account's model list" in out,
      "model=<id> outside the saved list: saved, with a note (no request)")
rc, out = run("wake", "models")
check("  claude-made-up-1" not in out and "(default)" not in out and "Now: claude-made-up-1." in out,
      "wake models: no default mark while a model is set")
run("wake", "model=default")
api._MODELS.clear()
MCALLS.clear()
got = c.get("/x/wake/models").json()
check(got["source"] == "saved" and got["models"] == MLIST["ids"] and got["default"] == "claude-haiku-4-5" and not MCALLS,
      "route: a list read in the last hours comes from the state file, no request")
st = state()
st[f"models:{P}"]["ts"] -= core.MODELS_MAX_AGE + 60
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
got = c.get("/x/wake/models").json()
check(got["source"] == "live" and len(MCALLS) == 1, "route: an older list is read again")
st = state()
st.pop(f"models:{P}")
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
MLIST["ids"] = None
MCALLS.clear()
got = c.get("/x/wake/models").json()
again = c.get("/x/wake/models").json()
check(got["models"] == [] and got["error"] and again == got and len(MCALLS) == 2,
      "route: a failed read gives an empty list and why; not tried again within a minute")
check(c.get("/x/wake/models?provider=openrouter").json()["error"].startswith("Wake is not available"),
      "route: a provider without wake says so")
MLIST["ids"] = ["claude-opus-4-5-20251101", "claude-haiku-4-5", "claude-haiku-4-5-20251001"]
api._MODELS.clear()

# ── wake by hand ─────────────────────────────────────────────────────────────
rc, out = run("wake", dry_run=True)
check(rc == 0 and "would wake alice@example.com" in out and "would wake carol@example.com" in out
      and "skip bob@example.com: window running" in out and not SENT, "dry run: idle accounts only, nothing sent")
check("skip dave@example.com: needs a new sign-in" in out and "skip erin@example.com: an API key" in out,
      "dry run: a dead login and an API key are left alone, said why")
rc, out = run("wake")
woke = [lab for lab, _ in SENT]
check(rc == 0 and woke == ["alice@example.com", "carol@example.com"] and "2 woken" in out, "wake: the idle accounts")
kw = SENT[0][1]
check(kw["model"] == "claude-haiku-4-5" and kw["max_tokens"] == 1 and kw["system"][0]["text"].startswith(
      "You are Claude Code") and kw["messages"] == [{"role": "user", "content": "hi"}],
      "wake request: Haiku, one output token, Claude Code identity, through Hermes' client")
st = state()
check(st.get(f"wake:{P}:an0000", {}).get("ok") and st.get(f"wake:{P}:an2000", {}).get("model") == "claude-haiku-4-5",
      "the wakes are remembered per account")
check(sum(1 for a in activity() if a["kind"] == "wake" and a["text"].startswith("woke ")) == 2,
      "the activity log has one line per wake")

SENT.clear()
rc, out = run("wake", "bob@example.com")
check(rc == 0 and not SENT and "window running, resets" in out, "a named account with a running window is left alone")
FIVE["carol@example.com"] = 500
rc, out = run("wake", "carol@example.com")
check(rc == 0 and [lab for lab, _ in SENT] == ["carol@example.com"], "a named account with unknown usage is woken")
SENT.clear()
rc, out = run("wake")
check("skip carol@example.com: usage unknown" in out and "carol@example.com" not in [lab for lab, _ in SENT],
      "without a name, unknown usage is not woken")
FIVE["carol@example.com"] = (0.0, None)
FAIL["alice@example.com"] = RateLimited()
SENT.clear()
rc, out = run("wake", "alice@example.com")
check(rc == 1 and "wake failed for alice@example.com: rate-limited" in out
      and state()[f"wake:{P}:an0000"]["ok"] is False, "a failed wake: said why, exit code 1, remembered")
FAIL.clear()
rc, out = run("park", "carol@example.com")
rc, out = run("wake", "carol@example.com")
check(rc != 0 and "is parked" in out, "a parked account is not woken")
run("unpark", "carol@example.com")
rc, out = run("wake", "nobody@example.com")
check(rc != 0 and "list" in out, "an unknown target is refused")

# ── automatic wake in the balance run ────────────────────────────────────────
rc, out = run("wake", "auto-on")
check(rc == 0 and "Automatic wake on" in out and "balance timer is not active" in out and core._wake_cfg(P)["auto"],
      "auto-on saved, with the warning that the timer is off")
st = state()
for k in [k for k in st if k.startswith("wake:")]:
    st.pop(k)
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
SENT.clear()
rc, out = run("balance")
woke = sorted(lab for lab, _ in SENT)
check(rc == 0 and woke == ["alice@example.com", "carol@example.com"] and "woke alice@example.com" in out,
      "balance wakes the idle accounts in rotation")
check("bob@example.com" not in woke and "dave@example.com" not in woke and "skip" not in out,
      "balance leaves running, dead and API-key accounts alone, quietly")
check(any(a["kind"] == "wake" and a["by"] == "cli" for a in activity()), "balance's wakes are logged as wake")
SENT.clear()
rc, out = run("balance")
check(not SENT, "the next run does not wake them again within the hour")
st = state()
st[f"wake:{P}:an0000"]["ts"] -= 2 * 3600
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
FIVE["carol@example.com"] = (0.0, time.time() + 4 * 3600)       # carol's window runs now
SENT.clear()
rc, out = run("balance")
check([lab for lab, _ in SENT] == ["alice@example.com"], "an hour later a window that is still idle is woken again")
SENT.clear()
rc, out = run("balance", dry_run=True)
check(not SENT, "balance --dry-run sends no wake")
rc, out = run("doctor")
check("automatic wake is on, but the balance timer is off" in out, "doctor: automatic wake needs the timer")
rc, out = run("wake", "status")
check("automatic: on" in out and "alice@example.com" in out and "woken" in out, "wake status lists the accounts")

# ── the window rule ──────────────────────────────────────────────────────────
t = time.time()
idle = core._window_idle
check(idle(None) is None and idle((0, None, 18000)) is True and idle((40, t - 5, 18000)) is True,
      "window: no reset time, or a reset in the past, is not running")
check(idle((0, t + 18000, 18000), ts=t) is True and idle((0, t + 17000, 18000), ts=t) is False
      and idle((3, t + 18000, 18000), ts=t) is False, "window: a full untouched 5 h (Codex idle) is not running")

# ── page routes ──────────────────────────────────────────────────────────────
st = c.get("/x/status").json()
check(st["wake"]["available"] and st["wake"]["auto"] and st["wake"]["model_text"] == "claude-haiku-4-5 (default)",
      "status: wake settings")
row = {r["label"]: r for r in st["rotation"]}
check(row["alice@example.com"]["woke"]["ok"] and row["bob@example.com"]["window"]["idle"] is False,
      "status: per account the window and the last wake")
code, r = post("/wake/settings", {"provider": P, "auto": False, "model": "claude-haiku-4-5-20251001"})
check(code == 200 and r["ok"] and r["wake"] == {"auto": False, "model": "claude-haiku-4-5-20251001"},
      "route: settings saved")
check(post("/wake/settings", {"provider": P, "auto": "yes"})[0] == 400 and post("/wake/settings", {"provider": P})[0] == 400,
      "route: settings validated")
post("/wake/settings", {"provider": P, "model": ""})
SENT.clear()
FIVE["carol@example.com"] = (0.0, None)
code, r = post("/wake", {"provider": P, "targets": ["an2000"]})
check(code == 200 and r["ok"] and [lab for lab, _ in SENT] == ["carol@example.com"], "route: wake the picked account")
api._NET[P] = time.time()
r = c.post("/x/wake", json={"provider": P}).json()
check(r["rc"] == 2 and "less than a minute" in r["output"], "route: one usage read a minute, shared with balance")
check(post("/wake", {"provider": P, "targets": "an2000"})[0] == 400
      and post("/wake", {"provider": P, "targets": ["a,b"]})[0] == 400, "route: targets validated")
check(post("/wake", {"provider": "openrouter"})[1]["rc"] == 2, "route: a provider without wake says so")

# ── email masking ────────────────────────────────────────────────────────────
rc, out = run("privacy")
check(rc == 0 and "Email masking: off" in out, "privacy status")
rc, out = run("privacy", "on")
check(rc == 0 and json.loads((ROOT / "account-pool.json").read_text())["mask_emails"] is True, "privacy on saved")
rc, out = run("list")
check("al•••e@e•••.com" in out and "alice@example.com" not in out and "@example.com" not in out,
      "list: emails masked")
check(core._short("alice@example.com") == "al•••e" and core._short("worker-1") == "worker-1",
      "the name before @ is masked too (balance order, daily summary)")
rc, out = run("park", "alice@example.com")
check(rc == 0 and "al•••e@e•••.com" in out and "alice@example.com" not in out, "a full email still works as target")
log = [a["text"] for a in activity()]
check(any("alice@example.com" in x and x.startswith("Parked") for x in log)
      and any(x.startswith("Email masking on") for x in log), "the activity log keeps the real text")
run("unpark", "alice@example.com")
SHOWN = []
real_run, real_which = core.subprocess.run, core.shutil.which
core.shutil.which = lambda name: "/usr/bin/" + name
core.subprocess.run = lambda cmd, **kw: SHOWN.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr="")
sent = core._notify("bob@example.com needs sign-in", "Sign in again: bob@example.com")
core.subprocess.run, core.shutil.which = real_run, real_which
check("desktop" in sent and SHOWN and not any("bob@example.com" in str(a) for a in SHOWN[0])
      and "bo•••@e•••.com" not in str(SHOWN[0]) and "b•••@e•••.com" in str(SHOWN[0]), "alerts: emails masked")
st = c.get("/x/status").json()
check(st["privacy"] is True and c.get("/x/summary").json()["privacy"] is True
      and st["rotation"][0]["label"].endswith("@example.com"),
      "routes: privacy flag on; the data keeps real labels (the page masks what it shows)")
code, r = post("/action", {"action": "park", "provider": P, "target": "an1000"})
check(r["ok"] and "bob@example.com" not in r["output"] and "b•••@e•••.com" in r["output"],
      "page action output is masked")
post("/action", {"action": "unpark", "provider": P, "target": "an1000"})
code, r = post("/privacy", {"provider": P, "on": False})
check(code == 200 and r["ok"] and r["privacy"] is False and c.get("/x/status").json()["privacy"] is False,
      "route: privacy off")
check(post("/privacy", {"provider": P, "on": "yes"})[0] == 400, "route: privacy validated")
rc, out = run("list")
check("alice@example.com" in out, "masking off: emails in full again")
rc, out = run("privacy", "maybe")
check(rc == 2, "privacy accepts on, off, status")

# ── Codex: idle window read, the wake request on the Responses endpoint ──────
C = "openai-codex"


def jwt(email, acct="acct-1"):
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return (f"{part({'alg': 'none'})}.{part({'exp': int(time.time() + 3600), 'https://api.openai.com/profile': {'email': email}, 'https://api.openai.com/auth': {'chatgpt_account_id': acct}})}.sig")


CTOK = {"ann@example.com": jwt("ann@example.com"), "ben@example.com": jwt("ben@example.com")}
cpool = load_pool(C)
for i, lab in enumerate(CTOK):
    cpool.add_entry(PooledCredential(provider=C, id=f"cx{i}000", label=lab, auth_type="oauth", priority=i,
                                     source="manual:loopback_pkce", access_token=CTOK[lab], refresh_token=f"rt-{i}",
                                     base_url="https://chatgpt.com/backend-api/codex"))
CUSAGE = {}
CREQ = []
CANSWER = []                                # queued answers for the Responses endpoint


class Answer:
    def __init__(self, body=None, lines=None):
        self.body, self.lines = body, lines or []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.body).encode()

    def __iter__(self):
        return iter(x.encode() + b"\n" for x in self.lines)


def sse(*events):
    return Answer(lines=[x for ev in events for x in (f"event: {ev['type']}", "data: " + json.dumps(ev), "")])


def fake_urlopen(req, timeout=None):
    headers = {k.lower(): v for k, v in req.header_items()}
    email = next((lab for lab, tok in CTOK.items() if headers.get("authorization", "")[7:] == tok), None)
    if "wham/usage" in req.full_url:
        return Answer(CUSAGE[email])
    if req.full_url.endswith("/codex/responses"):
        CREQ.append((email, headers, json.loads(req.data)))
        got = CANSWER.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    raise AssertionError(f"unexpected request to {req.full_url}")


urllib.request.urlopen = fake_urlopen
CMODELS = {"curated": False, "base": []}


class CuratedFallbackModels(list):          # the type Hermes returns when the live list failed
    pass


def fake_codex_ids(access_token=None, base_url=None):
    CMODELS["base"].append(base_url)
    ids = ["gpt-6-sol", "gpt-6-luna", "gpt-6-luna-900k", "gpt-5.3-codex-spark"]
    return CuratedFallbackModels(ids) if CMODELS["curated"] else ids


codex_models.get_codex_model_ids = fake_codex_ids
rc, out = run("wake", "models", provider=C)
check(rc == 0 and "  gpt-6-luna  (default)" in out and "gpt-6-sol" in out and "900k" not in out and "spark" not in out,
      "codex wake models: the account's list without -900k and spark, the smallest marked")
check(CMODELS["base"] and CMODELS["base"][-1] == "https://chatgpt.com/backend-api/codex"
      and state().get(f"models:{C}", {}).get("ids") == ["gpt-6-sol", "gpt-6-luna"], "codex: read on the account's own host, saved")
CMODELS["curated"] = True
st = state()
st.pop(f"models:{C}")
(ROOT / "account-pool-state.json").write_text(json.dumps(st))
rc, out = run("wake", "models", provider=C)
check(rc == 0 and "Hermes' built-in list" in out and f"models:{C}" not in state(),
      "codex: Hermes' offline list is shown as such and not saved as the account's")
CMODELS["curated"] = False


def window(pct, after, length=18000):
    return {"used_percent": pct, "limit_window_seconds": length, "reset_after_seconds": after}


CUSAGE["ann@example.com"] = {"rate_limit": {"primary_window": window(0, 18000), "secondary_window": window(30, 400000, 604800)}}
CUSAGE["ben@example.com"] = {"rate_limit": {"primary_window": window(12, 9000), "secondary_window": window(5, 400000, 604800)}}
rc, out = run("wake", provider=C, dry_run=True)
check(rc == 0 and "would wake ann@example.com" in out and "skip ben@example.com: window running" in out,
      "codex: an untouched 5 h window is idle, even when the weekly one is fuller")
rc, out = run("balance", provider=C)
rec = [json.loads(x) for x in (ROOT / "account-pool-history.jsonl").read_text().splitlines()
       if json.loads(x)["provider"] == C][-1]
check(rec["usage"]["ann@example.com"] == 30 and rec["win"]["ann@example.com"][0] == 0 and "ben@example.com" not in rec["win"],
      "codex history keeps the 5-hour window when the weekly one is the headline")
st = c.get(f"/x/status?provider={C}").json()
row = {r["label"]: r for r in st["rotation"]}
check(row["ann@example.com"]["window"]["idle"] is True and row["ben@example.com"]["window"]["idle"] is False,
      "codex: the page reads the idle window from history")
err = urllib.error.HTTPError("https://chatgpt.com/backend-api/codex/responses", 400, "bad", {},
                             io.BytesIO(json.dumps({"detail": "Unsupported parameter: reasoning.effort"}).encode()))
CANSWER[:] = [err, sse({"type": "response.created"}, {"type": "response.completed", "response": {}})]
rc, out = run("wake", provider=C)
check(rc == 0 and "woke ann@example.com (gpt-6-luna)" in out and len(CREQ) == 2, "codex wake: the smallest model")
first, second = CREQ[0][2], CREQ[1][2]
check(first["stream"] is True and first["store"] is False and first["reasoning"] == {"effort": "low"}
      and "reasoning" not in second and second["input"][0]["content"][0]["text"] == "hi",
      "codex wake: a streamed one-word request, asked again without reasoning when refused")
h = CREQ[0][1]
check(h.get("chatgpt-account-id") == "acct-1" and h.get("accept") == "text/event-stream"
      and h.get("originator") == "codex_cli_rs", "codex wake: Codex CLI headers with the ChatGPT account id")
CREQ.clear()
CANSWER[:] = [sse({"type": "response.failed", "response": {"error": {"message": "model is not supported"}}})]
rc, out = run("wake", "ann@example.com", provider=C)
check(rc == 1 and "wake failed for ann@example.com: the request failed: model is not supported" in out,
      "codex wake: a failed answer is reported")
CANSWER[:] = [Answer(lines=["data: {\"type\": \"response.created\"}"])]
rc, out = run("wake", "ann@example.com", provider=C)
check(rc == 1 and "ended before the request completed" in out, "codex wake: a cut answer is a failure")
CANSWER[:] = [sse({"type": "response.completed", "response": {}})]
run("wake", "model=gpt-6-sol", provider=C)
CREQ.clear()
rc, out = run("wake", "ann@example.com", provider=C)
check(rc == 0 and CREQ[0][2]["model"] == "gpt-6-sol", "codex wake: the model set with model=<id>")

blob = "".join(p.read_text() for p in ROOT.glob("account-pool*") if p.suffix in (".json", ".jsonl")
               and p.name != "account-pool-parked.json")
check(blob and not any(x in blob for x in ("fake-at-", "fake-rt-", CTOK["ann@example.com"], "refresh_token")),
      "no token in the settings, state, history or activity files")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
