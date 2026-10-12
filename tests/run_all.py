"""Run every sandbox test, each in its own throwaway Hermes home, on Linux, macOS or Windows.

    <Hermes' Python> tests/run_all.py [name ...]

Hermes' Python is the interpreter of the Hermes install (Linux: ~/.hermes/hermes-agent/venv/bin/python;
Windows: %LOCALAPPDATA%\\hermes\\hermes-agent\\venv\\Scripts\\python.exe). HERMES_AGENT_DIR names the
Hermes checkout when it is not in the default place. Names pick tests (setup_sandbox windows_sandbox);
without names all run. The sandboxes are made under ~/.cache and removed afterwards.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TESTS = ["features_sandbox", "tokens_sandbox", "api_sandbox", "profile_backend", "insights_sandbox",
         "setup_sandbox", "codex_sandbox", "wake_privacy_sandbox", "parked_usage_sandbox", "windows_sandbox"]
HERE = Path(__file__).resolve().parent


def agent_dir() -> str:
    if os.environ.get("HERMES_AGENT_DIR"):
        return os.environ["HERMES_AGENT_DIR"]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return str(Path(os.environ["LOCALAPPDATA"]) / "hermes" / "hermes-agent")
    return str(Path.home() / ".hermes" / "hermes-agent")


def main() -> int:
    names = sys.argv[1:] or TESTS
    unknown = [n for n in names if n not in TESTS]
    if unknown:
        print(f"unknown test(s): {' '.join(unknown)}; known: {' '.join(TESTS)}")
        return 2
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache.mkdir(parents=True, exist_ok=True)
    env_base = dict(os.environ, HERMES_AGENT_DIR=agent_dir(), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                    PYTHONIOENCODING="utf-8")
    results = []
    for name in names:
        sb = tempfile.mkdtemp(prefix="hap-sandbox.", dir=cache)
        started = time.monotonic()
        try:
            r = subprocess.run([sys.executable, str(HERE / f"{name}.py")], env=dict(env_base, HERMES_HOME=sb),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as x:
            partial = x.stdout.decode("utf-8", "replace") if isinstance(x.stdout, bytes) else (x.stdout or "")
            out, rc = partial + "\n(timed out after 600 s)", 124
        finally:
            shutil.rmtree(sb, ignore_errors=True)
        oks = sum(1 for line in out.splitlines() if line.startswith("ok   - "))
        fails = [line for line in out.splitlines() if line.startswith("FAIL - ")]
        results.append((name, rc, oks, fails, time.monotonic() - started))
        print(f"{'ok  ' if rc == 0 else 'FAIL'} {name}: {oks} ok, {len(fails)} failed ({time.monotonic() - started:.0f} s)",
              flush=True)
        if rc != 0:
            tail = out.strip().splitlines()[-40:]
            print("\n".join("    " + line for line in tail), flush=True)
    bad = [r for r in results if r[1] != 0]
    print(f"\n{len(results) - len(bad)}/{len(results)} test files passed, {sum(r[2] for r in results)} checks ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
