"""Sign in from the Accounts page through Hermes' own `hermes auth add`.

A page cannot type into a terminal, so the page's backend runs the same command the CLI runs,
`hermes auth add <provider> --type oauth --label <email>` (plus `--browser --no-browser` for the
Codex browser method), as a child process and relays it:

- the sign-in link and, for a device code, the code that the child prints go to the page;
- the code the user pastes after authorizing goes to the child's input, where Hermes asks for it;
- for the browser method, the address the browser ended on (when that browser runs on another
  computer and cannot reach this one) goes to the child's own callback listener on this computer.

Hermes runs the whole OAuth exchange and saves the account in its pool. This module never sees a
token: it only checks that a pasted code or address carries the `state` of the link it relays, so a
code from another sign-in gets a clear message instead of a failed exchange.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
AUTHORIZE = re.compile(r"https://\S+?/authorize\?\S+")
CALLBACK = re.compile(r"(https?://(?:localhost|127\.0\.0\.1):(\d+)(/\S*callback))")
DEVICE_URL = re.compile(r"(https://\S+/device)\b")
DEVICE_CODE = re.compile(r"Enter (?:this|the) code:?\s*\n\s*([A-Z0-9][A-Z0-9-]{3,})")
START_TIMEOUT = 90            # seconds for the child to print its link (a first run can be slow)
FINISH_TIMEOUT = 90           # seconds for the exchange after the code or address went in


def _state_of(url: str) -> str:
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query).get("state") or [""])[0]


class Relay:
    """One running `hermes auth add` child and everything it printed so far."""

    def __init__(self, cmd: list, env: dict, method: str, windows: bool = False, no_window: int = 0):
        self.method = method
        self.windows = windows
        self.info: dict = {}
        self._raw = ""
        self._cv = threading.Condition()
        self._eof = False
        env = dict(env, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1", TERM="dumb")
        if sys.platform.startswith("linux"):
            # Without a display Hermes prints the link instead of opening the default browser on this
            # computer: the user opens it in the browser profile that is signed in as the account.
            for key in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER"):
                env.pop(key, None)
        opts = {"creationflags": no_window | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if windows \
            else {"start_new_session": True}
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, env=env, **opts)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        stream = self.proc.stdout
        while True:
            try:
                chunk = stream.read1(4096)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                break
            with self._cv:
                self._raw += chunk.decode("utf-8", "replace")
                self._cv.notify_all()
        with self._cv:
            self._eof = True
            self._cv.notify_all()

    @property
    def out(self) -> str:
        """Everything the child printed so far, without colour codes (a code can span two reads)."""
        return ANSI.sub("", self._raw).replace("\r", "")

    def wait_for(self, test, timeout: float):
        """Wait until test(output) returns something truthy (returned), or the child ends, or the time is up."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                found = test(self.out)
                if found or self._eof:
                    return found
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._cv.wait(min(left, 0.5))

    def send(self, line: str) -> None:
        self.proc.stdin.write((line.strip() + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def returncode(self, wait: float = 0):
        try:
            return self.proc.wait(timeout=wait) if wait else self.proc.poll()
        except subprocess.TimeoutExpired:
            return None

    def tail(self, n: int = 3) -> str:
        """The last lines the child printed, without links, codes or Hermes' boxes: the reason it stopped."""
        lines = [ln.strip() for ln in self.out.splitlines()]
        keep = [ln for ln in lines if ln and "://" not in ln and not ln.startswith(("╭", "╰", "│"))
                and not DEVICE_CODE.search(ln + "\n")]
        return " ".join(keep[-n:])[:300]

    def close(self) -> None:
        """Stop the child and anything it started (a waiting callback listener frees its port)."""
        if self.proc.poll() is None:
            try:
                if self.windows:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                                   capture_output=True, timeout=15)
                else:
                    os.killpg(self.proc.pid, signal.SIGTERM)
            except (OSError, subprocess.SubprocessError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def parse(text: str) -> dict:
    """What the child printed: the authorize link, its callback listener, a device page and code, and
    whether it now asks for the authorization code."""
    info = {}
    m = AUTHORIZE.search(text)
    if m:
        info["url"] = m.group(0)
    m = CALLBACK.search(text)
    if m:
        info["callback"] = f"http://127.0.0.1:{m.group(2)}{m.group(3)}"
    m, code = DEVICE_URL.search(text), DEVICE_CODE.search(text)
    if m and code:
        info["device_url"], info["user_code"] = m.group(1), code.group(1)
    info["asks_code"] = "authorization code" in text.lower()
    return info


def start(cmd: list, env: dict, method: str, windows: bool = False, no_window: int = 0,
          timeout: float = START_TIMEOUT):
    """Run the child until it shows what the user needs. Returns (relay, page info): kind "code" (open
    the link, paste the code back), "browser" (open the link; this computer gets the callback) or
    "device" (enter the code on the provider's page). RuntimeError with the child's reason otherwise."""
    relay = Relay(cmd, env, method, windows=windows, no_window=no_window)

    def ready(text):
        # Whatever Hermes chose decides the kind: Codex falls back from the browser to a device code when
        # its callback port is busy, and `auth.codex_login_flow: browser` turns a device sign-in into a
        # browser one.
        info = parse(text)
        if info.get("user_code"):
            return {"kind": "device", "url": info["device_url"], "user_code": info["user_code"]}
        if info.get("url") and info.get("callback"):
            relay.info["callback"] = info["callback"]
            return {"kind": "browser", "url": info["url"], "listening": True}
        if info.get("url") and info.get("asks_code"):
            return {"kind": "code", "url": info["url"]}
        return None

    page = relay.wait_for(ready, timeout)
    if not page:
        reason = relay.tail() or "it printed no sign-in link"
        relay.close()
        raise RuntimeError(f"hermes auth add did not start the sign-in: {reason}")
    relay.info.update(page)
    return relay, page


def step(relay: Relay, code: str = ""):
    """Hand a pasted code (kind code) or browser address (kind browser) to the child, or just look whether
    it finished. Returns the child's exit code once it ended, None while it still waits. ValueError with
    a message for the user when the paste belongs to another sign-in or is not an address."""
    kind, code = relay.info.get("kind"), (code or "").strip()
    rc = relay.returncode()
    if rc is not None or kind == "device":
        return rc
    if not code:
        if kind == "code":
            raise ValueError("Paste the code shown after you authorize.")
        return None
    want = _state_of(relay.info.get("url", ""))
    if kind == "code":
        got = code.partition("#")[2]
        if want and got != want:
            raise ValueError("This code belongs to another sign-in. Open the link from this window and copy the "
                             "whole code (it contains a #).")
        relay.send(code)
    else:
        parts = urllib.parse.urlsplit(code)
        query = urllib.parse.parse_qs(parts.query)
        if not query.get("code") and not query.get("error"):
            raise ValueError("Paste the whole address from the browser's address bar after you authorized "
                             "(it starts with http://localhost and contains code=).")
        if want and (query.get("state") or [""])[0] != want:
            raise ValueError("This address belongs to another sign-in. Use the link from this window.")
        try:
            urllib.request.urlopen(f"{relay.info['callback']}?{parts.query}", timeout=15).read()
        except Exception:  # noqa: BLE001 - the child's answer page or a closed listener: the exit code tells
            pass
    return relay.returncode(wait=FINISH_TIMEOUT)
