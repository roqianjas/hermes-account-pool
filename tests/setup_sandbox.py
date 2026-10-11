"""`hermes account <provider> setup` (profiles, tracker, timer) and the no-terminal refusals, in a throwaway
Hermes home.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/setup_sandbox.py
    rm -rf "$SB"

systemd is not isolated by HERMES_HOME, so `systemctl` is replaced by a recorder and the unit files go to
$SB/xdg (XDG_CONFIG_HOME). `hermes plugins enable` is replaced by the same config write it makes, so no
second Hermes starts. Refuses to run against a Hermes home under ~/.hermes.
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
if not HOME or Path(HOME).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
SB = Path(HOME)
os.environ["XDG_CONFIG_HOME"] = str(SB / "xdg")
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

import yaml  # noqa: E402
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
    assert args[:2] == ("plugins", "enable"), args
    home = SB if profile == "default" else SB / "profiles" / profile
    enabled, disabled = core._plugin_lists(home)
    if args[2] in disabled:
        core._set_config_value(home, "plugins.disabled", json.dumps([n for n in disabled if n != args[2]]))
    core._set_enabled(home, args[2], True)


core._systemctl = fake_systemctl
core._run_hermes = fake_hermes
core._timer_active = lambda: STATE["active"]
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
    return yaml.safe_load((home / "config.yaml").read_text()) or {}


def enabled(name):
    return (cfg(name).get("plugins") or {}).get("enabled") or []


def write_cfg(home, data):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump(data))


write_cfg(SB, {"plugins": {"enabled": ["account-pool"]}})
write_cfg(SB / "profiles" / "w1", {"model": {"default": "x"}})
write_cfg(SB / "profiles" / "w2", {"plugins": {"disabled": ["account-pool"]}})
write_cfg(SB / "profiles" / "w3", {"plugins": {"enabled": ["foo"], "disabled": ["account-pool-tracker"]},
                                   "credential_pool_strategies": {"anthropic": "round_robin"}})
TRACKER = SB / "plugins" / "account-pool-tracker"
shutil.copytree(PLUGINS / "account-pool-tracker", TRACKER, ignore=shutil.ignore_patterns("__pycache__"))
link = {n: SB / "profiles" / n / "plugins" / "account-pool-tracker" for n in ("w1", "w2", "w3")}
UNITS = SB / "xdg" / "systemd" / "user"

# ── the plan, without a terminal and without --yes: nothing changes ─────────
rc, text = run(core._cmd_setup)
check(rc == 1 and "Changes:" in text and "no terminal to answer, so no" in text and "Nothing changed." in text,
      "setup shows the plan; without a terminal and without --yes it changes nothing")
check("list account-pool in plugins.enabled of w1" in text and "of w3" in text and "of w2" not in text
      and "skipped, in plugins.disabled: w2" in text, "page backend: listed where missing, a profile that disabled it is skipped")
check("enable the session tracker in the default profile" in text and "link the session tracker into w1" in text
      and "enable the session tracker in w3 (it is in plugins.disabled there now)" in text,
      "tracker: default enable, link per profile, a disabled one is named")
check("add --timer to run `hermes account anthropic balance` every 5 minutes" in text
      and "not fill_first in w3; add --strategy to set it" in text, "timer and strategy are only offered")
check(enabled("w1") == [] and not link["w1"].exists() and not CALLS and not HERMES, "nothing was written")

# ── --yes applies it ─────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, yes=True)
check(rc == 0 and text.count("  done: ") == 9 and "FAILED" not in text, "setup --yes applies every step")
check(enabled("w1") == ["account-pool", "account-pool-tracker"] and enabled("w3") == ["foo", "account-pool", "account-pool-tracker"]
      and enabled("w2") == ["account-pool-tracker"] and "account-pool-tracker" in enabled("default"),
      "plugins.enabled per profile, other entries kept, w2 still without account-pool")
check(all(link[n].is_symlink() and link[n].resolve() == TRACKER.resolve() for n in link), "tracker links point at the default copy")
check((cfg("w3").get("plugins") or {}).get("disabled") == [], "enabling the tracker in w3 took it off plugins.disabled")
check(cfg("w3")["credential_pool_strategies"]["anthropic"] == "round_robin" and not CALLS,
      "without --strategy / --timer neither the strategy nor systemd is touched")
acts = core._read_activity("anthropic", 0)
check(len([a for a in acts if a["kind"] == "setup"]) == 9 and all(a["by"] == "cli" for a in acts),
      "each step is in the activity log")
rc, text = run(core._cmd_setup, yes=True)
check(rc == 0 and "Nothing to change." in text and "active in 4 of 4 profile(s)" in text, "a second run changes nothing")

# ── --timer ──────────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, timer=True, yes=True)
svc = (UNITS / "hermes-account-balance.service").read_text()
check(rc == 0 and f"ExecStart={core._hermes_bin()} account anthropic balance" in svc
      and f"Environment=HERMES_HOME={SB}" in svc and (UNITS / "hermes-account-balance.timer").exists(),
      "--timer writes the service (with HERMES_HOME of a custom home) and the timer")
check(CALLS == [("daemon-reload",), ("enable", "--now", "hermes-account-balance.timer"),
                ("start", "--no-block", "hermes-account-balance.service")], "--timer reloads, enables and starts once")
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text and "runs anthropic, active" in text, "--timer again: nothing to change")
STATE["active"] = False
CALLS.clear()
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "start the balance timer" in text and ("enable", "--now", "hermes-account-balance.timer") in CALLS,
      "an installed but stopped timer is started")
svc = (UNITS / "hermes-account-balance.service").read_text()
(UNITS / "hermes-account-balance.service").write_text(svc.replace("anthropic balance", "anthropic balance --threshold 85"))
(UNITS / "hermes-account-balance.timer").write_text(
    (UNITS / "hermes-account-balance.timer").read_text().replace("OnUnitActiveSec=5min", "OnUnitActiveSec=10min"))
rc, text = run(core._cmd_setup, provider="openai-codex", timer=True, yes=True)
svc = (UNITS / "hermes-account-balance.service").read_text()
check(rc == 0 and core._timer_providers() == ["anthropic", "openai-codex"] and "TimeoutStartSec=240" in svc,
      "a second provider adds its own ExecStart line after the first")
check("anthropic balance --threshold 85" in svc and "OnUnitActiveSec=10min" in (UNITS / "hermes-account-balance.timer").read_text(),
      "hand edits survive: the options of an ExecStart line and the timer's interval")

# ── --strategy ───────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, strategy=True, yes=True)
check(rc == 0 and cfg("w3")["credential_pool_strategies"]["anthropic"] == "fill_first"
      and "fill_first in w3" in text, "--strategy sets fill_first where it is not")

# ── options ──────────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, undo=True, timer=True)
check(rc == 2 and "--undo cannot be combined" in text, "--undo with --timer is refused")
rc, text = run(core._dispatch, action="list", timer=True)
check(rc == 2 and "--timer only applies to: setup" in text, "--timer on another action is refused")
check("setup" in core.HELP and "--undo" in core.HELP, "help lists setup")

# ── --undo ───────────────────────────────────────────────────────────────────
CALLS.clear()
rc, text = run(core._cmd_setup, provider="openai-codex", undo=True, yes=True)
check(rc == 0 and core._timer_providers() == ["anthropic"] and ("daemon-reload",) in CALLS
      and "it keeps running anthropic" in text, "undo for one provider keeps the timer for the other")
(SB / "account-pool-parked.json").write_text(json.dumps({"parked": [{"_provider": "anthropic", "id": "pk0001",
                                                                       "label": "dave@example.com"}]}))
rc, text = run(core._cmd_setup, undo=True, yes=True)
(SB / "account-pool-parked.json").unlink()
check(rc == 0 and not any(link[n].exists() or link[n].is_symlink() for n in link), "undo removes the tracker links")
check(enabled("w1") == [] and enabled("w3") == ["foo"] and enabled("w2") == []
      and (cfg("w3").get("plugins") or {}).get("disabled") == [], "undo takes both names off plugins.enabled, adds nothing to disabled")
check(not (UNITS / "hermes-account-balance.service").exists() and not (UNITS / "hermes-account-balance.timer").exists()
      and ("disable", "--now", "hermes-account-balance.timer") in CALLS, "undo removes the timer when no provider is left")
check("account-pool-tracker" in enabled("default") and TRACKER.is_dir() and "Kept:" in text,
      "the plugins in the default profile stay")
check("1 anthropic account(s) are parked and stay out of rotation: dave@example.com" in text,
      "undo names the parked accounts that would stay out of rotation")
rc, text = run(core._cmd_setup, undo=True, yes=True)
check(rc == 0 and "Nothing to change." in text, "undo twice: nothing to change")

# ── no tracker installed ─────────────────────────────────────────────────────
shutil.move(str(TRACKER), str(SB / "tracker.off"))
rc, text = run(core._cmd_setup)
check("not installed" in text and "hermes plugins install account-pool-tracker" in text
      and "link the session tracker" not in text, "without the tracker: install hint, no tracker steps")
shutil.move(str(SB / "tracker.off"), str(TRACKER))

# ── no systemd ───────────────────────────────────────────────────────────────
real_which = core.shutil.which
core.shutil.which = lambda name, *a, **k: None if name == "systemctl" else real_which(name, *a, **k)
try:
    rc, text = run(core._cmd_setup, timer=True)
finally:
    core.shutil.which = real_which
check("systemd not found: run `hermes account anthropic balance`" in text and "install the balance timer" not in text,
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

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
