"""`hermes account <provider> setup` (profiles, session tracking, the retired tracker, timer) and the
no-terminal refusals, in a throwaway Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/setup_sandbox.py
    rm -rf "$SB"

systemd is not isolated by HERMES_HOME, so `systemctl` is replaced by a recorder and the unit files go to
$SB/xdg (XDG_CONFIG_HOME). `hermes plugins remove` is replaced by what it does (delete the folder, forget
the name), so no second Hermes starts. Refuses to run against a Hermes home under ~/.hermes.
"""
import builtins
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in  # the real Hermes home, also on Windows
                  [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
SB = Path(HOME)
os.environ["XDG_CONFIG_HOME"] = str(SB / "xdg")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

try:                                     # Hermes 0.21.6+ ships hermes_yaml and no PyYAML
    from hermes_yaml import safe_dump as yaml_dump, safe_load as yaml_load  # noqa: E402
except ImportError:
    from yaml import safe_dump as yaml_dump, safe_load as yaml_load  # noqa: E402
from agent.credential_pool import PooledCredential, load_pool  # noqa: E402

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
spec = importlib.util.spec_from_file_location("hap_core", PLUGINS / "account-pool" / "__init__.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

failures = []
CALLS = []
HERMES = []
STATE = {"active": False}


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def fake_systemctl(*args):
    CALLS.append(args)
    if args[:2] == ("enable", "--now"):
        STATE["active"] = True
    if args[:2] == ("disable", "--now"):
        STATE["active"] = False


def fake_hermes(profile, *args):
    HERMES.append((profile, args))
    assert args[:2] == ("plugins", "remove"), args
    home = SB if profile == "default" else SB / "profiles" / profile
    shutil.rmtree(home / "plugins" / args[2])
    core._set_enabled(home, args[2], False)


core._systemctl = fake_systemctl
core._run_hermes = fake_hermes
core._timer_active = lambda: STATE["active"]
core._timer_stuck = lambda info=None: bool(info.get("stuck")) if info is not None else STATE.get("stuck", False)
core._tty = lambda: False


def run(handler, provider="anthropic", **kw):
    args = SimpleNamespace(provider=provider, action=None, target=None, until=None, threshold=None, dry_run=False,
                           hours=None, minutes=None, yes=False, key=False, every=None, chart=False, only=None,
                           timer=False, strategy=False, undo=False)
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


def cfg(name):
    home = SB if name == "default" else SB / "profiles" / name
    return yaml_load((home / "config.yaml").read_text(encoding="utf-8")) or {}


def enabled(name):
    return (cfg(name).get("plugins") or {}).get("enabled") or []


def write_cfg(home, data):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml_dump(data), encoding="utf-8")


# an install from before 4.0: the separate account-pool-tracker plugin, enabled in default and linked into w1
write_cfg(SB, {"plugins": {"enabled": ["account-pool", "account-pool-tracker"]}})
write_cfg(SB / "profiles" / "w1", {"model": {"default": "x"}, "plugins": {"enabled": ["account-pool-tracker"]}})
write_cfg(SB / "profiles" / "w2", {"plugins": {"disabled": ["account-pool"]}})
write_cfg(SB / "profiles" / "w3", {"plugins": {"enabled": ["foo"], "disabled": ["account-pool-tracker"]},
                                   "credential_pool_strategies": {"anthropic": "round_robin"}})
OLD_TRACKER = SB / "plugins" / "account-pool-tracker"
OLD_TRACKER.mkdir(parents=True)
(OLD_TRACKER / "plugin.yaml").write_text("name: account-pool-tracker\nversion: 1.5.1\n", encoding="utf-8")
(OLD_TRACKER / "__init__.py").write_text("VERSION = '1.5.1'\n", encoding="utf-8")
old_link = SB / "profiles" / "w1" / "plugins" / "account-pool-tracker"
old_link.parent.mkdir(parents=True)
old_link.symlink_to(OLD_TRACKER, target_is_directory=True)
link = {n: SB / "profiles" / n / "plugins" / "account-pool" for n in ("w1", "w2", "w3")}
UNITS = SB / "xdg" / "systemd" / "user"

# ── the plan, without a terminal and without --yes: nothing changes ─────────
rc, text = run(core._cmd_setup)
check(rc == 1 and "Changes:" in text and "no terminal to answer, so no" in text and "Nothing changed." in text,
      "setup shows the plan; without a terminal and without --yes it changes nothing")
check("list account-pool in plugins.enabled of w1" in text and "of w3" in text and "of w2" not in text
      and "skipped, in plugins.disabled: w2" in text, "page backend: listed where missing, a profile that disabled it is skipped")
check("link account-pool into w1" in text and "link account-pool into w3" in text and "into w2" not in text
      and "active in 1 of 4 profile(s); not in w2" in text,
      "session tracking: account-pool linked into each profile, not where it is disabled")
check("remove the retired account-pool-tracker from w1" in text and "from w3" not in text
      and "remove the retired account-pool-tracker plugin from the default profile" in text,
      "the retired tracker: its link in w1 and the plugin in default are planned for removal")
check("add --timer to balance anthropic (and every other provider with accounts) every 5 minutes" in text
      and "not fill_first in w3; add --strategy to set it" in text, "timer and strategy are only offered")
check(enabled("w1") == ["account-pool-tracker"] and not link["w1"].exists() and old_link.is_symlink()
      and OLD_TRACKER.is_dir() and not CALLS and not HERMES, "nothing was written")

# ── --yes applies it ─────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, yes=True)
check(rc == 0 and text.count("  done: ") == 6 and "FAILED" not in text, "setup --yes applies every step")
check(enabled("w1") == ["account-pool"] and enabled("w3") == ["foo", "account-pool"] and enabled("w2") == []
      and enabled("default") == ["account-pool"],
      "plugins.enabled per profile, other entries kept, w2 still without account-pool, the old tracker unlisted")
check(all(link[n].is_symlink() and link[n].resolve() == core.PLUGIN_DIR for n in ("w1", "w3"))
      and not link["w2"].exists(), "the account-pool links point at the default copy")
check(not old_link.is_symlink() and not old_link.exists() and not OLD_TRACKER.exists()
      and HERMES == [("default", ("plugins", "remove", "account-pool-tracker"))],
      "the retired tracker is gone: its link in w1 and, through `hermes plugins remove`, the default copy")
check((cfg("w3").get("plugins") or {}).get("disabled") == ["account-pool-tracker"],
      "plugins.disabled is left as it was")
check(cfg("w3")["credential_pool_strategies"]["anthropic"] == "round_robin" and not CALLS,
      "without --strategy / --timer neither the strategy nor systemd is touched")
acts = core._read_activity("anthropic", 0)
check(len([a for a in acts if a["kind"] == "setup"]) == 6 and all(a["by"] == "cli" for a in acts),
      "each step is in the activity log")
rc, text = run(core._cmd_setup, yes=True)
check(rc == 0 and "Nothing to change." in text and "active in 3 of 4 profile(s); not in w2" in text,
      "a second run changes nothing")

# ── which hermes the unit runs: the one the user installed, not Hermes' internal launcher ──
import tempfile  # noqa: E402
OUT = Path(tempfile.mkdtemp(dir=SB.parent, prefix="hap-bin-"))
for d in (SB / "launcher", OUT):
    d.mkdir(exist_ok=True)
    (d / "hermes").write_text("#!/bin/sh\n")
    (d / "hermes").chmod(0o755)
real_path = os.environ["PATH"]
os.environ["PATH"] = f"{SB / 'launcher'}{os.pathsep}{OUT}{os.pathsep}{real_path}"
check(core._hermes_bin() == str(OUT / "hermes"), "the timer runs the hermes outside the Hermes home, even when the internal one is first on PATH")
os.environ["PATH"] = real_path
shutil.rmtree(OUT)
shutil.rmtree(SB / "launcher")

# ── --timer ──────────────────────────────────────────────────────────────────
POOL = ["anthropic"]                      # the providers with accounts, as _pool_providers() reads them
real_pool_providers = core._pool_providers
core._pool_providers = lambda: list(POOL)
BIN = core._hermes_bin()
rc, text = run(core._cmd_setup, timer=True, yes=True)
svc = (UNITS / "hermes-account-balance.service").read_text()
check(rc == 0 and f"ExecStart={BIN} account all balance\n" in svc and svc.count("ExecStart=") == 1
      and f"Environment=HERMES_HOME={SB}" in svc and (UNITS / "hermes-account-balance.timer").exists(),
      "--timer writes one service line that balances every provider with accounts (HERMES_HOME of a custom home), and the timer")
check("every provider with accounts, now: anthropic" in text and "included by themselves" in text,
      "the plan says which providers that is now and that later ones are included")
check(CALLS == [("daemon-reload",), ("enable", "--now", "hermes-account-balance.timer"),
                ("start", "--no-block", "hermes-account-balance.service")], "--timer reloads, enables and starts once")
tmr = (UNITS / "hermes-account-balance.timer").read_text()
check("OnStartupSec=2min" in tmr and "OnUnitActiveSec=5min" in tmr and "Persistent" not in tmr and "OnBootSec" not in tmr,
      "a new timer runs 2 minutes after login, then every 5 minutes, without Persistent= (it skipped runs after a late login)")
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text and "runs every provider with accounts (now: anthropic), active" in text,
      "--timer again: nothing to change")
POOL.append("openai-codex")
check(core._timer_providers() == ["anthropic", "openai-codex"], "a provider that gets accounts is in the timer without another setup")
rc, text = run(core._cmd_setup, provider="openai-codex", timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text and "(now: anthropic, openai-codex)" in text,
      "--timer for that provider: nothing to change")
STATE["active"] = False
CALLS.clear()
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "start the balance timer" in text and ("enable", "--now", "hermes-account-balance.timer") in CALLS
      and core._timer_follows_pool(), "an installed but stopped timer is started, still for every provider")
# a unit from 3.10.2 or older: one line per provider
OLD = (f"[Unit]\nDescription=Hermes account pool: balance anthropic accounts by live usage\n\n[Service]\nType=oneshot\n"
       f"Environment=HERMES_HOME={SB}\nExecStart={BIN} account anthropic balance --threshold 85\nTimeoutStartSec=120\n")
(UNITS / "hermes-account-balance.service").write_text(OLD)
(UNITS / "hermes-account-balance.timer").write_text(
    (UNITS / "hermes-account-balance.timer").read_text().replace("OnUnitActiveSec=5min", "OnUnitActiveSec=10min"))
check(core._timer_providers() == ["anthropic"] and not core._timer_follows_pool(), "an older unit runs only its own lines")
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text and "runs anthropic, active" in text,
      "--timer for a provider an older unit already runs: left alone")
rc, text = run(core._cmd_setup, provider="openai-codex", timer=True, yes=True)
svc = (UNITS / "hermes-account-balance.service").read_text()
check(rc == 0 and "switch the balance timer from anthropic to every provider with accounts" in text
      and svc.count("ExecStart=") == 1 and f"ExecStart={BIN} account all balance --threshold 85\n" in svc
      and "TimeoutStartSec=600" in svc, "--timer for a provider it lacks switches an older unit to every provider")
check("OnUnitActiveSec=10min" in (UNITS / "hermes-account-balance.timer").read_text(),
      "hand edits survive: the options of the ExecStart line and the timer's interval")

# a timer file from 4.0.1 or older (OnBootSec + Persistent=true) never ran again after a late login
TIMER = UNITS / "hermes-account-balance.timer"
STALE = ("[Unit]\nDescription=Run hermes account balance every 5 minutes\n\n[Timer]\nOnBootSec=2min\n"
         "OnUnitActiveSec=10min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
HEALED = STALE.replace("OnBootSec=", "OnStartupSec=").replace("Persistent=true\n", "")
TIMER.write_text(STALE)
check(core._timer_file_stale() and not core._timer_file_stale(HEALED), "a 4.0.1 timer file is recognised, a repaired one is not")
rc, text = run(core._cmd_setup, yes=True)
check(rc == 0 and "it can stop after a late login, add --timer to repair it" in text and TIMER.read_text() == STALE,
      "setup without --timer only says so")
CALLS.clear()
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "repair the balance timer" in text and TIMER.read_text() == HEALED,
      "--timer repairs it: OnStartupSec=, no Persistent=, the hand-set interval and every other line kept")
check(CALLS == [("daemon-reload",), ("enable", "--now", "hermes-account-balance.timer"),
                ("start", "--no-block", "hermes-account-balance.service")], "the repair reloads systemd and starts one run")
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text, "repaired: nothing to change")
CAL = "[Unit]\nDescription=mine\n\n[Timer]\nOnCalendar=*:0/5\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
TIMER.write_text(CAL)
check(not core._timer_file_stale() and not core._heal_timer_file() and TIMER.read_text() == CAL,
      "a hand-written OnCalendar= timer with Persistent= is left alone")
TIMER.write_text(HEALED)
STATE["stuck"] = True
CALLS.clear()
rc, text = run(core._cmd_setup, timer=True, yes=True)
STATE["stuck"] = False
check(rc == 0 and "repair the balance timer" in text and ("start", "--no-block", "hermes-account-balance.service") in CALLS,
      "a stuck timer (active, no next run) gets the repair and one run now from --timer")
# the timer's own run repairs a stale file once
TIMER.write_text(STALE)
real_every, real_proc = core._balance_every, list(core._TIMER_PROC)
core._balance_every = lambda args: 0
core._TIMER_PROC[:] = [True]
CALLS.clear()
rc, text = run(core._cmd_balance_all)
check(rc == 0 and CALLS == [("daemon-reload",)] and "timer: updated hermes-account-balance.timer" in text
      and TIMER.read_text() == HEALED, "a timer run repairs a stale timer file and reloads systemd")
CALLS.clear()
rc, text = run(core._cmd_balance_all)
check(rc == 0 and CALLS == [] and "timer:" not in text, "only once")
core._TIMER_PROC[:] = []
TIMER.write_text(STALE)
rc, text = run(core._cmd_balance_all)
check(rc == 0 and CALLS == [] and TIMER.read_text() == STALE, "a manual `all balance` outside the timer touches no unit file")
core._balance_every, core._TIMER_PROC[:] = real_every, real_proc
TIMER.write_text(HEALED)
# doctor names the stuck state
real_info = core._timer_info
core._timer_info = lambda: {"active": True, "running": False, "result": "success", "last": "Tue 2026-10-13 22:08:29",
                            "next": "", "next_ts": None, "last_ts": None, "stuck": True}
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "timer" in t]
check(any(lvl == "fail" and "has no next run" in t and "setup --timer" in t for lvl, t in doc),
      "doctor: an active timer with no next run is a failure with the fix")
TIMER.write_text(STALE)
core._timer_info = lambda: {"active": True, "running": False, "result": "success", "last": "now",
                            "next": "10:05", "next_ts": 1.0, "last_ts": 1.0, "stuck": False}
doc = [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "timer" in t]
check(any(lvl == "warn" and "from account-pool 4.0.1 or older" in t for lvl, t in doc), "doctor: a stale timer file is a warning")
core._timer_info = real_info
TIMER.write_text(HEALED)

# ── --strategy ───────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, strategy=True, yes=True)
check(rc == 0 and cfg("w3")["credential_pool_strategies"]["anthropic"] == "fill_first"
      and "fill_first in w3" in text, "--strategy sets fill_first where it is not")

# ── options ──────────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, undo=True, timer=True)
check(rc == 2 and "--undo cannot be combined" in text, "--undo with --timer is refused")
rc, text = run(core._dispatch, action="list", timer=True)
check(rc == 2 and "--timer only applies to: setup" in text, "--timer on another action is refused")
rc, text = run(core._dispatch, provider="all", action="list")
check(rc == 2 and "'all' works with balance only" in text, "`all` with another action is refused")
check("hermes account all balance" in core.HELP, "help names `all balance`")
check("setup" in core.HELP and "--undo" in core.HELP, "help lists setup")

# ── --undo ───────────────────────────────────────────────────────────────────
CALLS.clear()
rc, text = run(core._cmd_setup, provider="openai-codex", undo=True, yes=True)
svc = (UNITS / "hermes-account-balance.service").read_text()
check(rc == 0 and list(core._timer_lines()) == ["anthropic"] and ("daemon-reload",) in CALLS
      and "it then runs anthropic only" in text and "account anthropic balance --threshold 85\n" in svc,
      "undo for one provider keeps the timer for the others, one line each, options kept")
(SB / "account-pool-parking.json").write_text(json.dumps({"version": 4, "parked": [
    {"_provider": "anthropic", "id": "pk0001", "label": "dave@example.com"}]}))
rc, text = run(core._cmd_setup, undo=True, yes=True)
(SB / "account-pool-parking.json").unlink()
check(rc == 0 and not any(link[n].exists() or link[n].is_symlink() for n in link)
      and core.PLUGIN_DIR.is_dir(), "undo removes the account-pool links, never what they point at")
check(enabled("w1") == [] and enabled("w3") == ["foo"] and enabled("w2") == []
      and (cfg("w3").get("plugins") or {}).get("disabled") == ["account-pool-tracker"],
      "undo takes account-pool off plugins.enabled, adds nothing to disabled")
check(not (UNITS / "hermes-account-balance.service").exists() and not (UNITS / "hermes-account-balance.timer").exists()
      and ("disable", "--now", "hermes-account-balance.timer") in CALLS, "undo removes the timer when no provider is left")
check(enabled("default") == ["account-pool"] and "Kept:" in text, "account-pool in the default profile stays")
check("1 anthropic account(s) are parked and stay out of rotation: dave@example.com" in text
      and "up to 30 days" in text, "undo names the parked accounts and how long Hermes holds them")
rc, text = run(core._cmd_setup, undo=True, yes=True)
check(rc == 0 and "Nothing to change." in text, "undo twice: nothing to change")
core._pool_providers = real_pool_providers

# ── no systemd ───────────────────────────────────────────────────────────────
real_which = core.shutil.which
core.shutil.which = lambda name, *a, **k: None if name == "systemctl" else real_which(name, *a, **k)
try:
    rc, text = run(core._cmd_setup, timer=True)
finally:
    core.shutil.which = real_which
check("systemd not found: run `hermes account all balance`" in text and "install the balance timer" not in text,
      "--timer without systemd says so and plans nothing for it")

# ── anything waiting for a person refuses without a terminal ───────────────
pool = load_pool("anthropic")
pool.add_entry(PooledCredential(provider="anthropic", id="oa0001", label="alice@example.com", auth_type="oauth",
                                priority=0, source="manual", access_token="fake-token"))
pool.add_entry(PooledCredential(provider="anthropic", id="ak0002", label="bob@example.com", auth_type="api_key",
                                priority=1, source="manual", access_token="fake-key"))


def no_signin(*a, **k):
    raise AssertionError("a sign-in started without a terminal")


core._signin = no_signin
core._add_key_in_process = no_signin
rc, text = run(core._cmd_add, target="carol@example.com", yes=True)
check(rc == 1 and "add needs a terminal: the authorization code is pasted there" in text
      and "hermes account anthropic add carol@example.com" in text, "add --yes without a terminal: refused, no sign-in")
rc, text = run(core._cmd_add, target="carol@example.com", yes=True, key=True)
check(rc == 1 and "the API key is typed" in text and "add carol@example.com --key" in text, "add --key without a terminal: refused")
rc, text = run(core._cmd_relogin, target="alice@example.com", yes=True)
check(rc == 1 and "relogin needs a terminal" in text, "relogin --yes without a terminal: refused")
rc, text = run(core._cmd_add, provider="openai-codex", target="cara@example.com", yes=True)
check(rc == 1 and "add needs a terminal: the sign-in link is shown there" in text
      and "hermes account openai-codex add cara@example.com" in text, "codex add without a terminal: refused")
rc, text = run(core._cmd_add, target="dora@example.com", yes=True, device=True)
check(rc == 1 and "--device is only for openai-codex" in text, "--device refused for anthropic")
rc, text = run(core._cmd_remove, target="bob@example.com")
check(rc == 1 and "no terminal to answer, so no" in text and len(load_pool("anthropic").entries()) == 2,
      "remove without --yes and without a terminal: answered no at once")
core._tty = lambda: True
real_input = builtins.input
builtins.input = lambda prompt="": "y"
try:
    check(core._confirm("Delete it?", False) is True, "with a terminal the prompt is asked")

    # codex add / relogin from the terminal: Hermes' browser sign-in by default, --device on request
    CMDS = []
    SIGNED = {}

    def fake_signin(cmd, provider, before):
        CMDS.append(cmd)
        label = cmd[cmd.index("--label") + 1]
        tok = f"cx-{len(CMDS)}"
        SIGNED[tok] = label
        load_pool(provider).add_entry(PooledCredential(
            provider=provider, id=f"cx{len(CMDS):04d}", label=label, auth_type="oauth", priority=0,
            source="manual:loopback_pkce", access_token=tok, refresh_token="rt"))
        return 0

    core._signin = fake_signin
    core._identity = lambda provider, entry: SIGNED.get(entry.access_token)
    core._has_usage = lambda provider: False
    rc, text = run(core._cmd_add, provider="openai-codex", target="cara@example.com", yes=True)
    check(rc == 0 and CMDS[-1][-4:] == ["--label", "cara@example.com", "--browser", "--no-browser"]
          and "ON THIS COMPUTER" in text and "paste the code" not in text,
          "codex add: Hermes' browser sign-in, link printed, no pasted code")
    rc, text = run(core._cmd_add, provider="openai-codex", target="dan@example.com", yes=True, device=True)
    check(rc == 0 and CMDS[-1][-2:] == ["--label", "dan@example.com"] and "codex/device" in text,
          "codex add --device: the device code sign-in")
    rc, text = run(core._cmd_relogin, provider="openai-codex", target="cara@example.com", yes=True)
    labels = [e.label for e in sorted(load_pool("openai-codex").entries(), key=lambda e: e.priority)]
    check(rc == 0 and "--browser" in CMDS[-1] and labels == ["cara@example.com", "dan@example.com"],
          "codex relogin: browser sign-in, same label and position")
    real_spec = core._codex_browser_signin
    core._codex_browser_signin = lambda: False
    rc, text = run(core._cmd_add, provider="openai-codex", target="eve@example.com", yes=True)
    check(rc == 0 and "--browser" not in CMDS[-1] and "codex/device" in text,
          "codex add on a Hermes without the browser sign-in: device code")
    core._codex_browser_signin = real_spec
    print(f"info - this Hermes has the Codex browser sign-in: {core._codex_browser_signin()}")
finally:
    builtins.input = real_input

# A fresh Hermes 0.21.6+ install has no PyYAML (Hermes reads YAML with hermes_yaml): setup and doctor's profile
# checks must not need it. sys.modules[name] = None makes `import yaml` raise ImportError.
saved_yaml = sys.modules.get("yaml")
sys.modules["yaml"] = None
try:
    core._tty = lambda: False                # any Continue? prompt is answered no at once
    lists = core._plugin_lists(SB)
    check(lists[0] == [str(x) for x in enabled("default")] and lists[0], "config.yaml is read without PyYAML")
    check(isinstance(core._strategies("anthropic"), list), "strategies are read without PyYAML")
    rc, text = run(core._cmd_setup, provider="anthropic", yes=False, timer=False, strategy=False, undo=False)
    check(rc in (0, 1) and "Traceback" not in text and "yaml" not in text.lower(), "setup runs without PyYAML")
finally:
    if saved_yaml is None:
        sys.modules.pop("yaml", None)
    else:
        sys.modules["yaml"] = saved_yaml

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
