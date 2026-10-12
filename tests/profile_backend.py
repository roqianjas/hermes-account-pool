"""Hermes Desktop runs its backend under the profile it last used (`hermes --profile <name> serve`).

Checks, in a throwaway Hermes home with one profile `worker`:

1. account-pool listed only in the default profile: the backend launched under `worker` does not
   mount the page's routes (404), which is the "backend did not answer" case.
2. account-pool also listed in `worker` (what install.sh does): the routes mount and serve the
   shared pool of the default home, not the profile's.
3. register() adds the `hermes account` command in the default home and nothing in a profile.

    SB=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" hap-sandbox.XXXX)
    HERMES_HOME=$SB ~/.hermes/hermes-agent/venv/bin/python tests/profile_backend.py
    rm -rf "$SB"
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent / "plugins" / "account-pool"
AGENT = os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent"))


def load_core():
    spec = importlib.util.spec_from_file_location("hap_core", PLUGIN / "__init__.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ctx:
    def __init__(self):
        self.commands = []

    def register_cli_command(self, **kw):
        self.commands.append(kw["name"])


if len(sys.argv) > 1 and sys.argv[1] == "--child":
    # Runs with HERMES_HOME=<sandbox>/profiles/worker, like `hermes --profile worker serve`.
    sys.path.insert(0, AGENT)
    from fastapi.testclient import TestClient
    import hermes_cli.web_server as ws
    from hermes_cli.web_server_dashboard import _mount_plugin_api_routes
    _mount_plugin_api_routes()
    c = TestClient(ws.app)
    r = c.get("/api/plugins/account-pool/summary", headers={ws._SESSION_HEADER_NAME: ws._SESSION_TOKEN})
    ctx = Ctx()
    load_core().register(ctx)
    print(json.dumps({"status": r.status_code, "body": r.json(), "commands": ctx.commands}))
    sys.exit(0)

HOME = os.environ.get("HERMES_HOME", "")
if not HOME or any(Path(HOME).resolve().is_relative_to(h.resolve()) for h in  # the real Hermes home, also on Windows
                  [Path.home() / ".hermes"] + ([Path(os.environ["LOCALAPPDATA"]) / "hermes"] if os.environ.get("LOCALAPPDATA") else [])):
    sys.exit("Set HERMES_HOME to a sandbox outside ~/.hermes first (see the docstring).")
root = Path(HOME)
sys.path.insert(0, AGENT)
from agent.credential_pool import PooledCredential, load_pool  # noqa: E402

shutil.copytree(PLUGIN, root / "plugins" / "account-pool", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"))
(root / "config.yaml").write_text("plugins:\n  enabled:\n    - account-pool\n")
worker = root / "profiles" / "worker"
(worker / "plugins").mkdir(parents=True, exist_ok=True)
load_pool("anthropic").add_entry(PooledCredential(provider="anthropic", id="fake00", label="alice@example.com",
                                                  auth_type="api_key", priority=0, source="manual",
                                                  access_token="fake-key-0"))
failures = []


def check(cond, what):
    print(("ok   - " if cond else "FAIL - ") + what)
    if not cond:
        failures.append(what)


def child():
    env = dict(os.environ, HERMES_HOME=str(worker), PYTHONPATH=AGENT)
    out = subprocess.run([sys.executable, __file__, "--child"], env=env, capture_output=True, text=True, timeout=300)
    line = next((l for l in reversed(out.stdout.splitlines()) if l.startswith("{")), None)
    if not line:
        print(out.stdout[-1500:], out.stderr[-1500:])
        return {}
    return json.loads(line)


(worker / "config.yaml").write_text("plugins:\n  enabled:\n    - disk-cleanup\n")
r = child()
check(r.get("status") == 404, "listed only in default: backend under a profile does not serve the page (404)")

(worker / "config.yaml").write_text("plugins:\n  enabled:\n    - disk-cleanup\n    - account-pool\n")
r = child()
check(r.get("status") == 200, "listed in the profile too: backend under the profile serves the page")
check((r.get("body") or {}).get("rotation") == 1, "it reads the shared pool of the default home")
check(r.get("commands") == [], "register() adds nothing in a profile")
check("fake-key" not in json.dumps(r), "no token in the response")

ctx = Ctx()
load_core().register(ctx)
check(ctx.commands == ["account"], "register() adds `hermes account` in the default home")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
