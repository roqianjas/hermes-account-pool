"""The Windows code paths, run on any system: the balance timer as a Task Scheduler task, Windows
notifications, junctions that link account-pool into a profile (session tracking), the hermes command, process detection, doctor.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/windows_sandbox.py
    rm -rf "$SB"

`core.WINDOWS` is switched on and every Windows tool goes through `winsys.run`, which is replaced by a fake
Task Scheduler that keeps the registered task's XML. On a real Windows machine the same file runs against
the real Task Scheduler when HAP_REAL_WINDOWS=1 (see .github/workflows/windows.yml).
Refuses to run against a Hermes home under ~/.hermes.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET     # parses only XML this test or Task Scheduler wrote
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

HOME = os.environ.get("HERMES_HOME", "")
REAL_HOMES = [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in REAL_HOMES):
    sys.exit("Set HERMES_HOME to a sandbox outside the real Hermes home first (see the docstring).")
SB = Path(HOME)
REAL = os.environ.get("HAP_REAL_WINDOWS") == "1" and os.name == "nt"
sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))

try:                                     # Hermes 0.21.6+ ships hermes_yaml and no PyYAML
    from hermes_yaml import safe_dump as yaml_dump, safe_load as yaml_load  # noqa: E402
except ImportError:
    from yaml import safe_dump as yaml_dump, safe_load as yaml_load  # noqa: E402

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
spec = importlib.util.spec_from_file_location("hap_core", PLUGINS / "account-pool" / "__init__.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
ws = core.winsys

failures = []


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


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


# ── a fake Task Scheduler ────────────────────────────────────────────────────
TASKS = {}            # name -> XML text
SCHT = []             # every schtasks call


def fake_run(args, timeout=60):
    SCHT.append(list(args))
    verb, name = args[1], args[args.index("/TN") + 1] if "/TN" in args else None
    if verb == "/Create":
        if FAIL_CREATE and "/RU" in args:
            return 1, "ERROR: Access is denied."
        xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", xml))          # Task Scheduler rejects bad XML
        TASKS[name] = xml
        return 0, f'SUCCESS: The scheduled task "{name}" has successfully been created.'
    if verb == "/Query":
        if name not in TASKS:
            return 1, "ERROR: The system cannot find the file specified."
        return 0, TASKS[name]
    if verb == "/Run":
        return (0, "SUCCESS") if name in TASKS else (1, "ERROR: The system cannot find the file specified.")
    if verb == "/Delete":
        if name not in TASKS:
            return 1, "ERROR: The system cannot find the file specified."
        del TASKS[name]
        return 0, "SUCCESS"
    return 1, f"unexpected {args}"


FAIL_CREATE = False
if not REAL:
    ws.run = fake_run
    core.WINDOWS = True
if not REAL:
    os.environ["USERNAME"] = "you"
    os.environ["USERDOMAIN"] = "DESKTOP-1"


def write_cfg(home, data):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml_dump(data), encoding="utf-8")


def fake_hermes(profile, *args):
    raise AssertionError(f"setup started a second Hermes: {profile} {args}")


core._run_hermes = fake_hermes
core._tty = lambda: False
core._pool_providers = lambda: ["anthropic"]

if importlib.util.find_spec("hermes_cli") is None:
    # A bare Windows Python without Hermes (e.g. a quick check of the Windows paths alone): write config
    # values straight to the YAML and give doctor an empty pool. With Hermes installed, its own writer runs.
    print("info - Hermes not importable: config writes and the pool are stubbed")

    def bare_set_config_value(home, key, value):
        path = Path(home) / "config.yaml"
        data = (yaml_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
        node = data
        *parents, last = key.split(".")
        for k in parents:
            node = node.setdefault(k, {})
        node[last] = json.loads(value) if value[:1] in "[{" else value
        path.write_text(yaml_dump(data), encoding="utf-8")

    core._set_config_value = bare_set_config_value
    core._pool = lambda provider: SimpleNamespace(entries=lambda: [])

# ── winsys: paths in balance.cmd ─────────────────────────────────────────────
saved_env = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "USERPROFILE")}
os.environ["LOCALAPPDATA"] = r"C:\Users\José\AppData\Local"
os.environ["USERPROFILE"] = r"C:\Users\José"
check(ws.cmd_path(r"C:\Users\José\AppData\Local\hermes\bin\hermes.exe") == r"%LOCALAPPDATA%\hermes\bin\hermes.exe",
      "balance.cmd names the user's folders through %LOCALAPPDATA%, so a non-ASCII user name stays out of it")
check(ws.cmd_path(r"c:\users\josé\appdata\local\hermes\bin\hermes.exe").startswith("%LOCALAPPDATA%"),
      "the folder match ignores case, as Windows does")
check(ws.cmd_path(r"D:\tools\100%\hermes.exe") == r"D:\tools\100%%\hermes.exe", "a % elsewhere is doubled for cmd")
check(ws.cmd_path(r"C:\Users\José\hermes\bin\hermes.exe") == r"%USERPROFILE%\hermes\bin\hermes.exe",
      "a folder under the user profile goes through %USERPROFILE%")
for k, v in saved_env.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

# ── winsys: balance.cmd and balance.vbs ──────────────────────────────────────
FILES = SB / "files-test"
d = ws.write_files(FILES, [ws.command(r"C:\h\bin\hermes.exe", "all", " --threshold 85")], r"D:\custom home",
                   "Hermes account pool: balance every provider's accounts by live usage")
cmd = (d / "balance.cmd").read_bytes()
vbs = (d / "balance.vbs").read_text(encoding="ascii")
check(b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b""), "balance.cmd has Windows line ends only")
text = cmd.decode("utf-8")
check('"C:\\h\\bin\\hermes.exe" account all balance --threshold 85 >>balance.log 2>&1' in text
      and 'set "HERMES_ACCOUNT_POOL_TIMER=1"' in text and 'set "HERMES_HOME=D:\\custom home"' in text
      and 'cd /d "%~dp0"' in text and text.rstrip().endswith("exit /b %ERRORLEVEL%") and "chcp" not in text,
      "balance.cmd: the command with its options and log redirect, the timer flag, a custom HERMES_HOME")
check(ws.read_lines(FILES) == {"all": '"C:\\h\\bin\\hermes.exe" account all balance --threshold 85'},
      "the lines read back without the redirect; the rem line saying 'account pool: balance' is not a line")
check('WScript.Quit sh.Run("cmd.exe /d /c balance.cmd", 0, True)' in vbs and "sh.CurrentDirectory = dir" in vbs
      and "1048576" in vbs and ":" not in vbs.split("CurrentDirectory")[1].split("\n")[0],
      "balance.vbs runs balance.cmd from its own folder, hidden, waits, keeps the log under 1 MB, names no path")
ws.write_files(FILES, [ws.command(r"E:\Ünïcode\hermes.exe", "anthropic"), ws.command(r"E:\Ünïcode\hermes.exe", "openai-codex")],
               None, "x")
text = (FILES / "account-pool-timer" / "balance.cmd").read_bytes().decode("utf-8")
check(text.startswith("@chcp 65001 >nul\r\n") and "HERMES_HOME" not in text
      and list(ws.read_lines(FILES)) == ["anthropic", "openai-codex"],
      "a non-ASCII path outside the user folders switches cmd to UTF-8; one line per provider, in order")
shutil.rmtree(FILES)

# ── winsys: the task XML ─────────────────────────────────────────────────────
xml = ws.task_xml(Path(r"C:\Users\R&D\hermes\account-pool-timer\balance.vbs"), "a <b> & c",
                  start=datetime(2026, 1, 2, 3, 4, 5))
tree = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", xml))
ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
get = lambda p: tree.find(p, ns).text  # noqa: E731
check(get("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval") == "PT5M"
      and get("t:Triggers/t:TimeTrigger/t:StartBoundary") == "2026-01-02T03:04:05"
      and get("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
      and get("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege",
      "task XML: every 5 minutes, while the user is signed in, no admin rights")
check(get("t:Settings/t:StartWhenAvailable") == "true" and get("t:Settings/t:DisallowStartIfOnBatteries") == "false"
      and get("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew" and get("t:Settings/t:ExecutionTimeLimit") == "PT10M",
      "task XML: missed runs caught up, on battery too, one at a time, stopped after 10 minutes")
check(get("t:Actions/t:Exec/t:Command") == "wscript.exe"
      and get("t:Actions/t:Exec/t:Arguments") == '//B //Nologo "C:\\Users\\R&D\\hermes\\account-pool-timer\\balance.vbs"'
      and get("t:RegistrationInfo/t:Description") == "a <b> & c",
      "task XML: wscript runs balance.vbs; & and < in paths and text are escaped")
TASKS["probe"] = xml
saved_name = ws.TASK_NAME
ws.TASK_NAME = "probe"
q = ws.query_task() if not REAL else None
ws.TASK_NAME = saved_name
if not REAL:
    check(q and q["enabled"] and q["interval"] == 300 and q["start"] == datetime(2026, 1, 2, 3, 4, 5).timestamp()
          and "balance.vbs" in q["command"], "the registered task reads back: enabled, interval, start, command")
    TASKS["probe"] = xml.replace("<Enabled>true</Enabled>\n    <Hidden>", "<Enabled>false</Enabled>\n    <Hidden>")
    ws.TASK_NAME = "probe"
    check(ws.query_task()["enabled"] is False, "a task switched off in Task Scheduler reads as not enabled")
    ws.TASK_NAME = saved_name
    del TASKS["probe"]
start = datetime(2026, 1, 2, 3, 0, 0).timestamp()
check(ws.next_run({"start": start, "interval": 300}, start + 301) == start + 600
      and ws.next_run({"start": start, "interval": 300}, start - 50) == start
      and ws.next_run({"start": start, "interval": 300}, start + 300) == start + 600,
      "next run: the first start plus whole intervals")

# ── the hermes command the task runs ─────────────────────────────────────────
if not REAL:
    lad = SB / "lad"
    (lad / "hermes" / "bin").mkdir(parents=True)
    (lad / "hermes" / "bin" / "hermes.exe").write_text("")
    os.environ["LOCALAPPDATA"] = str(lad)
    check(core._hermes_bin() == str(lad / "hermes" / "bin" / "hermes.exe"),
          "Windows: the timer runs the hermes.exe the installer published in %LOCALAPPDATA%\\hermes\\bin")
    (SB / "bin").mkdir()
    (SB / "bin" / "hermes.exe").write_text("")
    check(core._hermes_bin() == str(SB / "bin" / "hermes.exe"), "a custom Hermes home's own bin\\hermes.exe comes first")
    shutil.rmtree(SB / "bin")
BIN = core._hermes_bin()

# ── setup --timer on Windows ─────────────────────────────────────────────────
write_cfg(SB, {"plugins": {"enabled": ["account-pool"]}})
write_cfg(SB / "profiles" / "w1", {"model": {"default": "x"}})
TARGET = core.PLUGIN_DIR
if REAL:   # the real task runs the real hermes.exe in this home: it needs the plugin there
    shutil.copytree(PLUGINS / "account-pool", SB / "plugins" / "account-pool", ignore=shutil.ignore_patterns("__pycache__"))
LINK = SB / "profiles" / "w1" / "plugins" / "account-pool"
JUNCTIONS = []
if not REAL:
    # A symlink needs Developer Mode on Windows: refuse it as Windows does and take the junction.
    real_symlink_to = Path.symlink_to

    def no_symlink(self, target, target_is_directory=False):
        raise OSError(1314, "A required privilege is not held by the client")

    def fake_junction(link, target):
        JUNCTIONS.append((Path(link), Path(target)))
        os.symlink(target, link)                      # stands in for the junction on this system

    Path.symlink_to = no_symlink
    ws.junction = fake_junction
    ws.is_junction = lambda p: any(Path(p) == j for j, _ in JUNCTIONS)
    ws.unlink_dir_link = lambda p: (JUNCTIONS.remove(next(x for x in JUNCTIONS if x[0] == Path(p))), os.unlink(p))
rc, text = run(core._cmd_setup, timer=True, yes=True)
root_dir = SB / "account-pool-timer"
if rc != 0 or "FAILED" in text:
    print(text)
check(rc == 0 and "FAILED" not in text, "setup --timer --yes on Windows")
check('a Task Scheduler task "Hermes Account Balance"' in text and str(root_dir) in text and "systemd" not in text,
      "the plan names the Task Scheduler task and its folder, not systemd")
check(LINK.exists() and LINK.resolve() == TARGET.resolve() and (REAL or JUNCTIONS == [(LINK, TARGET)]),
      "account-pool is linked into the profile; without symlink rights through a junction")
lines = core._timer_lines()
check(list(lines) == ["all"] and lines["all"] == f'"{ws.cmd_path(BIN)}" account all balance',
      "balance.cmd runs `hermes account all balance` with the published hermes.exe")
check(("HERMES_HOME" in (root_dir / "balance.cmd").read_text(encoding="utf-8")) == (not core._default_root()),
      "a custom Hermes home is set in balance.cmd")
if not REAL:
    creates = [c for c in SCHT if c[1] == "/Create"]
    check(len(creates) == 1 and creates[0][4] == "Hermes Account Balance" and creates[0][-4:] == ["/RU", "DESKTOP-1\\you", "/NP", "/IT"]
          and [c[1] for c in SCHT if c[1] in ("/Create", "/Run")] == ["/Create", "/Run"],
          "the task is created for the signed-in user, then started once")
    check(not list(root_dir.glob("*.xml")), "the task XML file is removed after registering")
check(core._timer_active(), "the timer reads as active")
if REAL:
    # setup started the task once: wait for that run of balance.cmd -> hermes.exe -> this plugin to finish
    deadline = time.time() + 240
    rec = {}
    while time.time() < deadline:
        rec = core._load_json(core._timer_run_path(), {}) or {}
        if rec.get("end"):
            break
        time.sleep(3)
    log = ws.log_path(SB)
    print("info - last-run.json:", rec)
    print("info - balance.log:", log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.exists() else "(none)")
    check(rec.get("end") and rec.get("rc") == 0, "Task Scheduler ran balance.cmd: hermes account all balance finished with exit code 0")
    check(core._timer_info()["result"] == "success", "the timer reads that real run as a success")
    test_run = SB / "test-last-run.json"          # the checks below write their own runs, apart from the task's
    core._timer_run_path = lambda: test_run
info = core._timer_info()
check(info["active"] and (info["last"] == "never" or REAL), "the timer is active; never run yet: last run never")
check(info["next_ts"] and 0 < info["next_ts"] - time.time() <= 360, "next run within the next 5 minutes")
rc, text = run(core._cmd_setup, timer=True, yes=True)
check(rc == 0 and "Nothing to change." in text and "runs every provider with accounts (now: anthropic), active" in text,
      "a second setup --timer changes nothing")

# ── a run from the task ──────────────────────────────────────────────────────
os.environ["HERMES_ACCOUNT_POOL_TIMER"] = "1"
core._TIMER_PROC.clear()
check(core._in_timer() and core._by() == "timer", "HERMES_ACCOUNT_POOL_TIMER=1 marks the run as the timer's")
core._pool_providers = lambda: []
rc, text = run(core._cmd_balance_all)
rec = json.loads(core._timer_run_path().read_text(encoding="utf-8"))
check(rc == 0 and rec["rc"] == 0 and rec["end"] >= rec["start"] > time.time() - 60, "the run records its start, end and exit code")
info = core._timer_info()
check(info["result"] == "success" and info["last_ts"] == rec["start"] and not info["running"], "the page and doctor read that run")
real_every = core._balance_every
core._balance_every = lambda args: 3
rc, text = run(core._cmd_balance_all)
core._balance_every = real_every
check(rc == 3 and core._timer_info()["result"] == "exit-code 3", "a failed run records its exit code")
del os.environ["HERMES_ACCOUNT_POOL_TIMER"]
core._TIMER_PROC.clear()
check(not core._in_timer(), "without the flag it is not the timer")
core._pool_providers = lambda: ["anthropic"]

# ── doctor on Windows ────────────────────────────────────────────────────────
core._has_usage = lambda provider: False


def timer_checks():
    return [(lvl, t) for lvl, t in core._doctor_checks("anthropic") if "timer" in t or "Task Scheduler" in t]


got = timer_checks()
check(any(lvl == "fail" and "last run failed (exit-code 3)" in t and str(ws.log_path(SB)) in t for lvl, t in got),
      "doctor: a failed run points at balance.log, not journalctl")
_ = core._atomic_json(core._timer_run_path(), {"start": time.time() - 3600, "end": time.time() - 3590, "rc": 0})
got = timer_checks()
check(any(lvl == "warn" and "only while you are signed in" in t for lvl, t in got),
      "doctor: no run for an hour says Task Scheduler runs it only while you are signed in")
_ = core._atomic_json(core._timer_run_path(), {"start": time.time() - 30, "end": time.time() - 20, "rc": 0})
got = timer_checks()
check(any(lvl == "ok" and t.startswith("balance timer active, last run") for lvl, t in got)
      and not any("does not run anthropic" in t for _, t in got), "doctor: a recent good run is ok, and the timer covers the provider")
checks = core._doctor_checks("anthropic")
check(not any("permissions" in t for _, t in checks), "doctor skips Unix file modes on Windows")
check(not any("journalctl" in t or "systemctl" in t or "systemd" in t for _, t in checks), "doctor names no Linux tool")

# ── notifications ────────────────────────────────────────────────────────────
TOASTS = []
if not REAL:
    ws.powershell = lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    ws.toast = lambda title, body: TOASTS.append((title, body)) or True
check(core._desktop_channel() == (True, "Windows notifications"), "desktop notifications go through Windows notifications")
cfg = core._config()
cfg["notify"]["desktop"] = True
core._atomic_json(core._config_path(), cfg)
sent = core._notify("Accounts", "every account above 80%")
if REAL:     # a CI machine may have no notification service: the call must only come back without an error
    check(isinstance(sent, list), f"a Windows notification was attempted (sent: {sent})")
else:
    check("desktop" in sent and TOASTS == [("Accounts", "every account above 80%")], "an alert is shown as a Windows notification")
rc, text = run(core._cmd_notify, target="status")
check("desktop  : on" in text and "notify-send" not in text, "notify status does not mention notify-send")
if not REAL:
    ws.powershell = lambda: None
    check(core._desktop_channel() == (False, "Windows notifications") and "desktop" not in core._notify("a", "b"),
          "without Windows PowerShell no desktop notification is claimed")
    script = ws._TOAST
    check("$env:HAP_TOAST_TITLE" in script and "$env:HAP_TOAST_BODY" in script and '"' not in script,
          "the toast script takes title and body from the environment and has no double quotes to escape")

# ── processes: never os.kill(pid, 0) on Windows (signal 0 is Ctrl+C there) ────
if not REAL:
    real_kill = os.kill

    def no_kill(*a):
        raise AssertionError("os.kill on Windows")
    os.kill = no_kill
    try:
        kind_self = core._process_kind(os.getpid())
        kind_gone = core._process_kind(2 ** 22 + 12345)
        check(kind_self == "session" and kind_gone is None, "process detection through psutil, without os.kill")
    except AssertionError as x:
        check(False, f"process detection: {x}")
    finally:
        os.kill = real_kill

# ── the page backend ─────────────────────────────────────────────────────────
sys.modules["account_pool_core"] = core              # the backend then uses this (patched) core
spec2 = importlib.util.spec_from_file_location("hap_api_win", PLUGINS / "account-pool" / "dashboard" / "plugin_api.py")
try:
    api = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(api)
    st = api.notify_status("anthropic")
    check(api.core is core and st["desktop_via"] == "Windows notifications",
          "the page's alert settings say Windows notifications")
except ImportError as x:                      # fastapi missing in this environment
    print(f"info - page backend not loaded: {x}")

# ── setup --undo ─────────────────────────────────────────────────────────────
rc, text = run(core._cmd_setup, undo=True, yes=True)
check(rc == 0 and 'the Task Scheduler task "Hermes Account Balance"' in text and "FAILED" not in text,
      "setup --undo names the task it removes")
check(not core._timer_active() and not (root_dir / "balance.cmd").exists() and not (root_dir / "balance.vbs").exists(),
      "the task and its files are gone")
check(not LINK.exists() and not os.path.lexists(LINK) and TARGET.is_dir() and (REAL or not JUNCTIONS),
      "the link is removed, the plugin it points at stays")
if not REAL:
    check([c[1] for c in SCHT].count("/Delete") == 1, "the task was deleted with schtasks /Delete")
    ws.delete_task()                               # deleting a task that is not there is not an error
    check(True, "deleting a missing task is quiet")
    FAIL_CREATE = True
    (SB / "account-pool-timer").mkdir(exist_ok=True)
    core.winsys.install_task(SB, "x")
    check(SCHT[-2][-4:] == ["/RU", "DESKTOP-1\\you", "/NP", "/IT"] and "/RU" not in SCHT[-1],
          "when Task Scheduler refuses the user form, the plain form is tried")
    ws.delete_task()
    FAIL_CREATE = False
    Path.symlink_to = real_symlink_to

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
