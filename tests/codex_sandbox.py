"""openai-codex in a throwaway Hermes home: identity, check, live usage, park/unpark, parked-token refresh,
balance, remove, doctor, the timer's `all balance` and the daily summary, with fake tokens and a fake usage
endpoint, so no request reaches OpenAI.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/codex_sandbox.py
    rm -rf "$SB"

The page's Codex sign-in (browser and device code) is tested in api_sandbox.py, the terminal's in
setup_sandbox.py. Refuses to run against a Hermes home under ~/.hermes.
"""
import base64
import contextlib
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
os.environ["XDG_CONFIG_HOME"] = str(Path(HOME) / "xdg")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

from agent.credential_pool import PooledCredential, load_pool  # noqa: E402
from hermes_cli import auth_codex  # noqa: E402

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
spec = importlib.util.spec_from_file_location("hap_core", PLUGINS / "account-pool" / "__init__.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
P = "openai-codex"
failures = []
SENT = []
core._notify = lambda title, body, icon="dialog-warning": SENT.append((title, body)) or ["desktop"]
core._timer_active = lambda: False
core._tty = lambda: False


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def run(handler, **kw):
    args = SimpleNamespace(provider=P, action=None, target=None, until=None, threshold=None, dry_run=False,
                           hours=None, minutes=None, yes=True, key=False, every=None, chart=False, only=None,
                           timer=False, strategy=False, undo=False, device=False)
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


def jwt(email, exp_in=3600, acct="acct-1"):
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    claims = {"exp": int(time.time() + exp_in), "https://api.openai.com/profile": {"email": email},
              "https://api.openai.com/auth": {"chatgpt_account_id": acct}}
    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


# ── fake usage endpoint ──────────────────────────────────────────────────────
USAGE = {}           # access token -> answer (dict) or HTTP status (int)
SEEN = []


class Answer:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def fake_urlopen(req, timeout=None):
    headers = {k.lower(): v for k, v in req.header_items()}
    SEEN.append((req.full_url, headers))
    if "wham/usage" not in req.full_url:
        raise AssertionError(f"unexpected request to {req.full_url}")
    got = USAGE.get(headers.get("authorization", "")[7:], 500)
    if isinstance(got, int):
        raise urllib.error.HTTPError(req.full_url, got, "fake", {}, io.BytesIO(b"{}"))
    return Answer(got)


urllib.request.urlopen = fake_urlopen


def rl(primary, secondary=None, reached=False):
    now = time.time()
    out = {"rate_limit": {"allowed": not reached, "limit_reached": reached,
                          "primary_window": {"used_percent": primary, "limit_window_seconds": 18000,
                                             "reset_after_seconds": 3600}}}
    if secondary is not None:
        out["rate_limit"]["secondary_window"] = {"used_percent": secondary, "limit_window_seconds": 604800,
                                                 "reset_at": now + 86400}
    return out


def entries():
    return [(e.label, e.id) for e in sorted(load_pool(P).entries(), key=lambda e: e.priority)]


pool = load_pool(P)
TOK = {}
for i, label in enumerate(["ann@example.com", "ben@example.com", "cy@example.com"]):
    TOK[label] = jwt(label)
    pool.add_entry(PooledCredential(provider=P, id=f"cx{i}000", label=label, auth_type="oauth", priority=i,
                                    source="manual:loopback_pkce", access_token=TOK[label],
                                    refresh_token=f"rt-{i}", base_url="https://chatgpt.com/backend-api/codex",
                                    last_refresh="2026-01-01T00:00:00Z"))

# ── identity and check ───────────────────────────────────────────────────────
ad = core.providers.get(P)
check(ad.has_identity and ad.has_usage and ad.identity(SimpleNamespace(access_token=TOK["ben@example.com"]))
      == "ben@example.com", "identity: the email in the ChatGPT token")
rc, text = run(core._cmd_list)
check(rc == 0 and "in rotation (3)" in text and "ann@example.com" in text, "list")
rc, text = run(core._cmd_check)
check(rc == 0 and "All accounts in rotation are healthy." in text and "account : ben@example.com" in text,
      "check: every login matches its label")

# ── live usage ───────────────────────────────────────────────────────────────
USAGE[TOK["ann@example.com"]] = rl(30, 60)
USAGE[TOK["ben@example.com"]] = rl(10, 5, reached=True)
USAGE[TOK["cy@example.com"]] = {"rate_limit": {}}
rc, text = run(core._cmd_usage)
line = {lab: next((ln for ln in text.splitlines() if lab in ln), "") for lab in TOK}
check(rc == 0 and "60%" in line["ann@example.com"] and "5h 30% · week 60%" in line["ann@example.com"],
      "usage: the fuller window counts, both shown")
check("100%" in line["ben@example.com"], "usage: limit reached reads as 100%")
check("n/a" in line["cy@example.com"] and "no limit data" in line["cy@example.com"], "usage: no limit data, said why")
h = next(hd for url, hd in SEEN if url.endswith("/wham/usage"))
check(h.get("chatgpt-account-id") == "acct-1" and h.get("originator") == "codex_cli_rs"
      and h.get("authorization", "").startswith("Bearer "), "usage: Codex CLI headers with the ChatGPT account id")
USAGE[TOK["cy@example.com"]] = 401
rc, text = run(core._cmd_usage)
cy = next((ln for ln in text.splitlines() if "cy@example.com" in ln), "")
check("n/a" in cy and "401" in cy, "usage: a refused token is reported, not hidden")

# ── park / unpark keep the whole login ───────────────────────────────────────
before = {e.label: e.to_dict() for e in load_pool(P).entries()}
rc, text = run(core._cmd_park, target="ben@example.com")
check(rc == 0 and [lab for lab, _ in entries()] == ["ann@example.com", "cy@example.com"], "park")
parked = [p for p in core._read_parked() if p["_provider"] == P]
check(len(parked) == 1 and parked[0]["refresh_token"] == "rt-1" and parked[0]["source"] == "manual:loopback_pkce"
      and parked[0]["base_url"].endswith("/codex"), "parked record keeps refresh token, source and base URL")
rc, text = run(core._cmd_list)
check("parked (1)" in text and "ben@example.com" in text, "list shows the parked account")
rc, text = run(core._cmd_unpark, target="ben@example.com")
back = {e.label: e.to_dict() for e in load_pool(P).entries()}["ben@example.com"]
check(rc == 0 and all(back.get(k) == before["ben@example.com"].get(k)
                      for k in ("access_token", "refresh_token", "source", "base_url", "auth_type", "label")),
      "unpark restores the same login")

# ── parked account with an expired token: refreshed, or marked for a new sign-in ──
expired = jwt("cy@example.com", exp_in=-600)
pool = load_pool(P)
idx, cur, _ = pool.resolve_target("cy@example.com")
pool.remove_index(idx)
d = cur.to_dict()
d["access_token"] = expired
pool.add_entry(PooledCredential.from_dict(P, d))
rc, text = run(core._cmd_park, target="cy@example.com")
check(rc == 0, "park an account whose token expired")
REFRESH = []
fresh = jwt("cy@example.com")


def fake_refresh(access_token, refresh_token, timeout_seconds=20.0):
    REFRESH.append(refresh_token)
    if refresh_token == "dead-rt":
        raise RuntimeError("invalid_grant: refresh token already used")
    return {"access_token": fresh, "refresh_token": "rt-2b", "last_refresh": "2026-02-02T00:00:00Z"}


auth_codex.refresh_codex_oauth_pure = fake_refresh
USAGE[fresh] = rl(20, 40)
rc, text = run(core._cmd_usage)
rec = next(p for p in core._read_parked() if p.get("label") == "cy@example.com")
check(REFRESH == ["rt-2"] and rec["access_token"] == fresh and rec["refresh_token"] == "rt-2b"
      and rec.get("last_refresh") == "2026-02-02T00:00:00Z", "parked token refreshed once, rotated pair saved")
cy = next((ln for ln in text.splitlines() if "cy@example.com" in ln), "")
check("PARKED" in cy and "40%" in cy, "usage of the parked account read with the new token")
rc, text = run(core._cmd_usage)
check(REFRESH == ["rt-2"], "a fresh parked token is not refreshed again")
items = core._read_parked()
for p in items:
    if p.get("label") == "cy@example.com":
        p["access_token"], p["refresh_token"] = expired, "dead-rt"
core._write_parked(items)
rc, text = run(core._cmd_usage)
cy = next((ln for ln in text.splitlines() if "cy@example.com" in ln), "")
check("sign-in expired" in cy and f"hermes account {P} remove cy@example.com" in cy,
      "a dead parked login says how to fix it")
rc, text = run(core._cmd_unpark, target="cy@example.com")
rc, text = run(core._cmd_remove, target="cy@example.com")
check(rc == 0 and "cy@example.com" not in json.dumps(entries()) and not core._read_parked(), "remove")

# ── guards, balance, doctor ──────────────────────────────────────────────────
run(core._cmd_park, target="ann@example.com")
rc, text = run(core._cmd_park, target="ben@example.com")
check(rc != 0 and "last working" in text, "the last working account cannot be parked")
run(core._cmd_unpark, target="ann@example.com")
USAGE[TOK["ann@example.com"]] = rl(70, 80)
USAGE[TOK["ben@example.com"]] = rl(5, 10)
rc, text = run(core._cmd_balance, threshold=90.0)
check(rc == 0 and [lab for lab, _ in entries()] == ["ben@example.com", "ann@example.com"],
      "balance puts the least-used Codex account first")
rc, text = run(core._cmd_doctor)
print(text)
check("2 accounts in rotation" in text and "usage endpoint reachable" in text, "doctor for openai-codex")
# ── `hermes account all balance` (what the timer runs): every provider with accounts ──
load_pool("openrouter").add_entry(PooledCredential(provider="openrouter", id="or0001", label="ops@example.com",
                                                   auth_type="api_key", priority=0, source="manual",
                                                   access_token="FAKE-or"))
USAGE[TOK["ann@example.com"]] = rl(5, 10)
USAGE[TOK["ben@example.com"]] = rl(70, 80)
rc, text = run(core._dispatch, provider="all", action="balance", yes=False)
check(rc == 0 and "[openai-codex] balance" in text and "[openrouter] balance" in text
      and [lab for lab, _ in entries()] == ["ann@example.com", "ben@example.com"],
      "all balance: every provider with accounts, Codex reordered by usage")
rc, text = run(core._dispatch, provider="all", action="usage", yes=False)
check(rc == 2 and "works with balance only" in text, "all with another action is refused")
real_balance = core._cmd_balance


def failing_balance(a):
    if a.provider == P:
        raise RuntimeError("boom")
    return real_balance(a)


core._cmd_balance = failing_balance
rc, text = run(core._dispatch, provider="all", action="balance", yes=False)
core._cmd_balance = real_balance
check(rc == 1 and "[openai-codex] balance failed: RuntimeError: boom" in text and "[openrouter] balance" in text,
      "one provider failing does not stop the others; the exit code says it failed")

# ── daily summary: only for a provider with something to report ─────────────
run(core._cmd_notify, target="daily=00:00")
STATE_FILE = Path(HOME) / "account-pool-state.json"
st = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
STATE_FILE.write_text(json.dumps({k: v for k, v in st.items() if not k.startswith("daily:")}))   # not sent today yet
SENT.clear()
quiet, busy = core._run_daily("openrouter"), core._run_daily(P)
state = json.loads(STATE_FILE.read_text())
today = time.strftime("%Y-%m-%d")
check(quiet == [] and state.get("daily:openrouter") == today and not any("openrouter" in t for t, _ in SENT),
      "daily summary skipped for a provider with nothing to report, and not retried that day")
check(busy and any(t.startswith(f"Hermes {P}") for t, _ in SENT), "daily summary sent for a provider with usage")

blob = "".join(p.read_text() for p in Path(HOME).glob("account-pool-*")
               if p.suffix in (".json", ".jsonl") and p.name != "account-pool-parked.json")
check(blob and not any(t in blob for t in (TOK["ann@example.com"], TOK["ben@example.com"], "rt-0", "refresh_token")),
      "no token in the history, alert or state files (only auth.json and the parked file hold logins)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
