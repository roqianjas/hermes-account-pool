"""Windows pieces of the account-pool plugin: the balance timer as a Task Scheduler task, desktop
notifications as Windows toasts, and directory junctions for the session tracker.

Everything that touches Windows goes through `run()`, so the sandbox tests replace it with a recorder
and exercise this module on any system. Nothing here is imported for its side effects; the core calls
these functions only when `os.name == "nt"`.

The timer is three files in `<Hermes home>/account-pool-timer/` plus one task:

    balance.cmd   the commands, one line per run (`"...hermes.exe" account all balance`), output to
                  balance.log in the same folder. The core reads and rewrites these lines the way it
                  reads the systemd service's ExecStart lines on Linux.
    balance.vbs   runs balance.cmd with a hidden window (wscript has no console, so no window flashes
                  every 5 minutes) and passes on its exit code; it keeps balance.log under 1 MB.
    task XML      registered with `schtasks /Create /XML` as "Hermes Account Balance": every 5 minutes
                  while the user is signed in, missed runs caught up, no admin rights needed.

Hermes' own gateway uses the same pattern (wscript launcher, task XML in UTF-16) on Windows.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "Hermes Account Balance"
INTERVAL_MIN = 5
LOG_NAME = "balance.log"
CMD_NAME = "balance.cmd"
VBS_NAME = "balance.vbs"
REDIRECT = f" >>{LOG_NAME} 2>&1"
NO_WINDOW = 0x08000000                           # CREATE_NO_WINDOW: no console flash from a windowless parent
_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
# A command line as balance.cmd holds it: the quoted hermes path, then `account <provider> balance [opts]`.
_LINE = re.compile(r'^("[^"\r\n]+"\s+account\s+(\S+)\s+balance\b.*?)(?:\s*>>\s*' + re.escape(LOG_NAME)
                   + r'\s+2>&1)?\s*$', re.M)


def run(args: list, timeout: float = 60) -> tuple:
    """Run a Windows tool without a console window. Returns (exit code, output text). Replaced in tests."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"{Path(args[0]).name} timed out after {timeout:.0f}s"
    except OSError as x:
        return 1, f"{Path(args[0]).name} could not start: {x}"
    return r.returncode, (decode(r.stdout) + decode(r.stderr)).strip()


def decode(data: bytes) -> str:
    """Console tools write the console or OEM code page, not UTF-8: try UTF-8, then those pages."""
    if not data:
        return ""
    if data[:2] == b"\xff\xfe" or (len(data) > 3 and data[1] == 0 and data[3] == 0):   # UTF-16 (no NUL in text)
        return data.decode("utf-16-le", errors="replace").lstrip("\ufeff")
    pages = ["utf-8"]
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        for getter in ("GetConsoleOutputCP", "GetOEMCP", "GetACP"):
            cp = int(getattr(k32, getter)())
            if cp > 0 and f"cp{cp}" not in pages:
                pages.append(f"cp{cp}")
    except Exception:
        pass
    for enc in pages:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


# ── the timer's files ────────────────────────────────────────────────────────

def task_dir(root: Path) -> Path:
    return Path(root) / "account-pool-timer"


def cmd_path(text: str) -> str:
    """A path as balance.cmd writes it: %LOCALAPPDATA% / %USERPROFILE% for the user's own folders (the
    file then stays ASCII for any user name, and cmd reads a batch file in the OEM code page), the short
    8.3 name for a non-ASCII path elsewhere, `%` doubled so cmd does not expand it."""
    text = str(text)
    for var in ("LOCALAPPDATA", "USERPROFILE"):
        base = os.environ.get(var, "").rstrip("\\/")
        if base and text.lower().startswith(base.lower() + "\\"):
            return f"%{var}%" + text[len(base):].replace("%", "%%")
    if not text.isascii():
        text = short_path(text)
    return text.replace("%", "%%")


def short_path(text: str) -> str:
    """The 8.3 name of an existing path (ASCII on every volume that keeps short names), else the path."""
    try:
        import ctypes
        from ctypes import wintypes
        get = ctypes.windll.kernel32.GetShortPathNameW
        get.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(1024)
        n = get(text, buf, len(buf))
        if 0 < n < len(buf) and buf.value.isascii():
            return buf.value
    except Exception:
        pass
    return text


def read_lines(root: Path) -> dict:
    """{provider or "all": its command line, without the log redirect}, in file order; {} without the file."""
    try:
        text = (task_dir(root) / CMD_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {m.group(2): m.group(1).rstrip() for m in _LINE.finditer(text)}


def command(hermes: str, provider: str, opts: str = "") -> str:
    return f'"{cmd_path(hermes)}" account {provider} balance{opts}'


def write_files(root: Path, lines: list, home: str | None, description: str) -> Path:
    """Write balance.cmd (the given command lines) and balance.vbs. `home`: a custom HERMES_HOME to set,
    None for the default one. Returns the folder."""
    d = task_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    body = ["@echo off", f"rem {description}",
            "rem Written by `hermes account <provider> setup --timer`; balance.vbs runs it every "
            f"{INTERVAL_MIN} minutes.",
            'cd /d "%~dp0"',
            'set "HERMES_ACCOUNT_POOL_TIMER=1"']
    if home:
        body.append(f'set "HERMES_HOME={cmd_path(home)}"')
    body += [line + REDIRECT for line in lines]
    body.append("exit /b %ERRORLEVEL%")
    text = "\r\n".join(body) + "\r\n"
    if any(ord(c) > 127 for c in text):              # a path outside the user folders with non-ASCII letters
        text = "@chcp 65001 >nul\r\n" + text
    _write(d / CMD_NAME, text, "utf-8")
    _write(d / VBS_NAME, VBS, "ascii")
    return d


VBS = "\r\n".join([
    "' Hermes account pool: runs balance.cmd in this folder with a hidden window and returns its exit code.",
    "' Written by `hermes account <provider> setup --timer`.",
    "Option Explicit",
    "Dim sh, fso, dir, logf",
    'Set sh = CreateObject("WScript.Shell")',
    'Set fso = CreateObject("Scripting.FileSystemObject")',
    "dir = fso.GetParentFolderName(WScript.ScriptFullName)",
    f'logf = dir & "\\{LOG_NAME}"',
    "If fso.FileExists(logf) Then",
    "  If fso.GetFile(logf).Size > 1048576 Then",
    '    fso.CopyFile logf, logf & ".1", True',
    "    fso.DeleteFile logf",
    "  End If",
    "End If",
    "sh.CurrentDirectory = dir",
    f'WScript.Quit sh.Run("cmd.exe /d /c {CMD_NAME}", 0, True)',
]) + "\r\n"


def _write(path: Path, text: str, encoding: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def replace(src, dst) -> None:
    """os.replace that waits out a reader: on Windows a file another process has open cannot be replaced
    (PermissionError) for the moment it is open."""
    for attempt in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def remove_files(root: Path) -> None:
    d = task_dir(root)
    for name in (CMD_NAME, VBS_NAME):
        try:
            (d / name).unlink()
        except OSError:
            pass


def log_path(root: Path) -> Path:
    return task_dir(root) / LOG_NAME


# ── the task ─────────────────────────────────────────────────────────────────

def _user() -> str | None:
    name = os.environ.get("USERNAME")
    if not name:
        return None
    dom = os.environ.get("USERDOMAIN")
    return name if "\\" in name or not dom else f"{dom}\\{name}"


def task_xml(vbs: Path, description: str, start: datetime | None = None) -> str:
    """Task Scheduler XML: every 5 minutes from `start` (default: in one minute), only while the user is
    signed in (no stored password, no admin rights), on battery too, a missed run caught up at once, at
    most one run at a time, stopped after 10 minutes."""
    start = (start or datetime.now() + timedelta(minutes=1)).replace(microsecond=0)
    user = _user()
    principal = f"\n      <UserId>{escape(user)}</UserId>" if user else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{INTERVAL_MIN}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">{principal}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>//B //Nologo "{escape(str(vbs))}"</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def schtasks() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    path = Path(root) / "System32" / "schtasks.exe"
    return str(path) if path.exists() else "schtasks.exe"


def install_task(root: Path, description: str) -> None:
    """Register (or replace) the task for the files in task_dir(root). RuntimeError with schtasks' message."""
    d = task_dir(root)
    xml = d / "task.xml"
    with open(xml, "w", encoding="utf-16", newline="") as fh:
        fh.write(task_xml(d / VBS_NAME, description))
    try:
        base = [schtasks(), "/Create", "/F", "/TN", TASK_NAME, "/XML", str(xml)]
        user = _user()
        last = ""
        # As Hermes' gateway does: name the user first (no stored password, interactive only), then plain.
        for args in ([*base, "/RU", user, "/NP", "/IT"], base) if user else (base,):
            rc, out = run(args)
            if rc == 0:
                return
            last = out or f"exit code {rc}"
        raise RuntimeError(f"Task Scheduler refused the task: {last}")
    finally:
        try:
            xml.unlink()
        except OSError:
            pass


def start_task() -> None:
    rc, out = run([schtasks(), "/Run", "/TN", TASK_NAME])
    if rc:
        raise RuntimeError(f"schtasks /Run: {out or f'exit code {rc}'}")


def delete_task() -> None:
    rc, out = run([schtasks(), "/Delete", "/F", "/TN", TASK_NAME])
    if rc and not re.search(r"cannot find|does not exist|tidak dapat|not found", out, re.I):
        raise RuntimeError(f"schtasks /Delete: {out or f'exit code {rc}'}")


def query_task() -> dict | None:
    """{enabled, start, interval, command} of the registered task, or None when there is none. Read from
    the task's XML, which is not translated (the table output of schtasks is)."""
    rc, out = run([schtasks(), "/Query", "/TN", TASK_NAME, "/XML"])
    if rc or "<Task" not in out:
        return None
    # The XML comes from schtasks.exe about our own task, not from the network; expat does not fetch
    # external entities, so the stdlib parser is fine here.
    try:
        tree = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", out[out.find("<"):]).strip())
    except ET.ParseError:
        return {"enabled": True, "start": None, "interval": INTERVAL_MIN * 60, "command": ""}

    def text(path, default=""):
        el = tree.find(path, _NS)
        return (el.text or "").strip() if el is not None and el.text else default

    trig = "t:Triggers/t:TimeTrigger/"
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text(trig + "t:Repetition/t:Interval", "PT5M"))
    interval = (int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)) if m else INTERVAL_MIN * 60
    start = None
    try:
        start = datetime.fromisoformat(text(trig + "t:StartBoundary")[:19]).timestamp()
    except ValueError:
        pass
    return {"enabled": text("t:Settings/t:Enabled", "true").lower() != "false"
                       and text(trig + "t:Enabled", "true").lower() != "false",
            "start": start, "interval": interval or INTERVAL_MIN * 60,
            "command": " ".join(filter(None, (text("t:Actions/t:Exec/t:Command"), text("t:Actions/t:Exec/t:Arguments"))))}


def next_run(task: dict, now: float | None = None) -> float | None:
    """The next start of a repeating trigger: the first start + a whole number of intervals after now."""
    now = time.time() if now is None else now
    start, step = task.get("start"), task.get("interval") or INTERVAL_MIN * 60
    if not start:
        return None
    if start >= now:
        return start
    return start + (int((now - start) // step) + 1) * step


# ── notifications ────────────────────────────────────────────────────────────

# Windows PowerShell 5.1 (powershell.exe, in every Windows 10 and 11) can call the WinRT toast API; the
# toast appears under Windows PowerShell's name, which needs no app registration. Title and body come in
# through the environment, so no quoting of user text on a command line.
_TOAST = (
    "$ErrorActionPreference='Stop';"
    "$null=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime];"
    "$null=[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime];"
    "$e=[System.Security.SecurityElement];"
    "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml('<toast><visual><binding template=''ToastGeneric''><text>'+$e::Escape($env:HAP_TOAST_TITLE)"
    "+'</text><text>'+$e::Escape($env:HAP_TOAST_BODY)+'</text></binding></visual></toast>');"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
)


def powershell() -> str | None:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    path = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(path) if path.exists() else None


def toast(title: str, body: str) -> bool:
    """Show a Windows notification. True when PowerShell reported no error."""
    ps = powershell()
    if not ps:
        return False
    import base64
    env = dict(os.environ, HAP_TOAST_TITLE=title, HAP_TOAST_BODY=body)
    script = base64.b64encode(_TOAST.encode("utf-16-le")).decode("ascii")   # no command-line quoting at all
    try:
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", script],
                           env=env, capture_output=True, timeout=30, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# ── links ────────────────────────────────────────────────────────────────────

def is_junction(path: Path) -> bool:
    try:
        if hasattr(os.path, "isjunction"):                   # Python 3.12+
            return os.path.isjunction(path)
        import stat
        st = os.lstat(path)
        return bool(getattr(st, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1))
    except OSError:
        return False


def junction(link: Path, target: Path) -> None:
    """A directory junction: like a symlink to a folder, but any user may create one (a symlink needs
    Developer Mode or admin rights on Windows)."""
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def unlink_dir_link(link: Path) -> None:
    """Remove a symlink or junction to a folder, never the folder it points to."""
    try:
        os.rmdir(link)                  # a junction or a directory symlink on Windows
    except OSError:
        os.unlink(link)
