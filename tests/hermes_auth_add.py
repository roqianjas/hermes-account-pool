"""Stand-in for `hermes auth add <provider> --type oauth --label <email> [--browser --no-browser]` in tests.

It runs Hermes' own `auth_add_command` (the code behind `hermes auth add`) in a child process, so the
Accounts page relay sees exactly what Hermes prints and Hermes saves the account itself. Only the
edges that would reach the network or a fixed port are replaced:

- anthropic: the token exchange answers with fake tokens (`fake-at-<code>`); a code starting with
  "bad" fails the exchange the way Anthropic refuses a spent code;
- openai-codex browser: the callback listener binds a free port instead of 1455 (FAKE_CODEX_PORT
  names a port to try instead, e.g. one the test holds so Hermes falls back to the device code), and
  the exchange answers with `cx-at-<code>`;
- openai-codex device: OpenAI's device-code service is faked; the sign-in is confirmed once the
  file named by FAKE_DEVICE_OK exists.

Never sends a request anywhere. Used by tests/api_sandbox.py.
"""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")))
home = os.environ.get("HERMES_HOME", "")
if not home or Path(home).resolve().is_relative_to((Path.home() / ".hermes").resolve()):
    sys.exit("refusing to run outside a sandbox HERMES_HOME")

from agent import anthropic_credentials as ac  # noqa: E402
from hermes_cli import auth_codex, auth_codex_browser  # noqa: E402
from hermes_cli.auth_commands import auth_add_command  # noqa: E402

def fake_anthropic_exchange(body, **kw):
    code = json.loads(body)["code"]
    if code.startswith("bad"):
        raise RuntimeError("HTTP 400 invalid_grant")
    return {"access_token": f"fake-at-{code}", "refresh_token": "fake-rt", "expires_in": 3600}


def fake_codex_exchange(code, *, redirect_uri, code_verifier):
    return {"access_token": f"cx-at-{code}", "refresh_token": "cx-rt"}


def fake_device_poll(issuer, *, device_auth_id, user_code, poll_interval):
    flag = Path(os.environ["FAKE_DEVICE_OK"])
    while not flag.exists():
        time.sleep(0.2)
    return {"authorization_code": "ac", "code_verifier": "cv"}


ac._post_oauth_token = fake_anthropic_exchange
auth_codex_browser.CODEX_BROWSER_CALLBACK_PORT = int(os.environ.get("FAKE_CODEX_PORT") or 0)
auth_codex_browser._codex_browser_exchange_code = fake_codex_exchange
auth_codex._codex_request_device_code = lambda issuer, client_id: {
    "device_auth_id": "dev-1", "user_code": "WXYZ-1234", "interval": 1}
auth_codex._codex_poll_authorization_code = fake_device_poll
auth_codex._codex_exchange_authorization_code = lambda issuer, client_id, resp: {
    "access_token": "cx-at-dev", "refresh_token": "cx-rt-dev"}

argv = sys.argv[1:]
assert argv[:2] == ["auth", "add"], argv
args = SimpleNamespace(provider=argv[2], auth_type=argv[argv.index("--type") + 1], label=argv[argv.index("--label") + 1],
                       browser="--browser" in argv, no_browser="--no-browser" in argv, timeout=None, priority=None,
                       api_key=None)
auth_add_command(args)
