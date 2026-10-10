#!/usr/bin/env bash
# Install the account-pool plugins for Hermes Agent.
#
#   ./install.sh [--provider anthropic] [--set-strategy] [--no-tracker] [--no-timer]
#
# --set-strategy  set credential_pool_strategies.<provider>=fill_first in the default
#                 profile and every profile under $HERMES_HOME/profiles (needed by balance)
# --no-tracker    skip the session tracker (`hermes account <provider> who` stays empty)
# --no-timer      skip the systemd user timer that runs `balance` every 5 minutes
set -euo pipefail

PROVIDER="anthropic"
SET_STRATEGY=0
TRACKER=1
TIMER=1
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER="${2:?--provider needs a value}"; shift 2 ;;
    --set-strategy) SET_STRATEGY=1; shift ;;
    --no-tracker) TRACKER=0; shift ;;
    --no-timer) TIMER=0; shift ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="$(command -v hermes || true)"
[ -n "$HERMES_BIN" ] || HERMES_BIN="$HOME/.local/bin/hermes"
[ -x "$HERMES_BIN" ] || { echo "hermes not found on PATH or in ~/.local/bin" >&2; exit 1; }
[ -d "$ROOT" ] || { echo "Hermes home not found: $ROOT" >&2; exit 1; }
export HERMES_HOME="$ROOT"

say() { printf '\n== %s\n' "$*"; }
profiles() { [ -d "$ROOT/profiles" ] && find "$ROOT/profiles" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/config.yaml' ';' -printf '%f\n' | sort; }

say "Installing plugins into $ROOT/plugins"
mkdir -p "$ROOT/plugins"
STAMP="$(date +%Y%m%d-%H%M%S)"
for p in account-pool account-pool-tracker; do
  [ "$p" = account-pool-tracker ] && [ "$TRACKER" = 0 ] && continue
  if [ -e "$ROOT/plugins/$p" ] && [ ! -L "$ROOT/plugins/$p" ]; then
    mkdir -p "$ROOT/plugin-backups"
    cp -a "$ROOT/plugins/$p" "$ROOT/plugin-backups/$p.$STAMP"   # outside plugins/: never loaded twice
    echo "  previous $p backed up to $ROOT/plugin-backups/$p.$STAMP"
  fi
  rm -rf "$ROOT/plugins/$p"
  cp -a "$HERE/plugins/$p" "$ROOT/plugins/$p"
  find "$ROOT/plugins/$p" -name __pycache__ -prune -exec rm -rf '{}' +
  echo "  $p -> $ROOT/plugins/$p"
done
"$HERMES_BIN" plugins enable account-pool >/dev/null && echo "  enabled account-pool (default profile only)"

if [ "$TRACKER" = 1 ]; then
  say "Session tracker"
  "$HERMES_BIN" plugins enable account-pool-tracker >/dev/null && echo "  default: enabled"
  for prof in $(profiles); do
    mkdir -p "$ROOT/profiles/$prof/plugins"
    ln -sfn "$ROOT/plugins/account-pool-tracker" "$ROOT/profiles/$prof/plugins/account-pool-tracker"
    "$HERMES_BIN" -p "$prof" plugins enable account-pool-tracker >/dev/null && echo "  $prof: enabled (symlink)"
  done
fi

say "Pool strategy for $PROVIDER"
if [ "$SET_STRATEGY" = 1 ]; then
  "$HERMES_BIN" config set "credential_pool_strategies.$PROVIDER" fill_first >/dev/null && echo "  default: fill_first"
  for prof in $(profiles); do
    "$HERMES_BIN" -p "$prof" config set "credential_pool_strategies.$PROVIDER" fill_first >/dev/null && echo "  $prof: fill_first"
  done
else
  echo "  unchanged. balance needs fill_first; re-run with --set-strategy, or set it yourself:"
  echo "  hermes [-p <profile>] config set credential_pool_strategies.$PROVIDER fill_first"
fi

if [ "$TIMER" = 1 ]; then
  say "systemd user timer (balance every 5 minutes)"
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  sed -e "s#@HERMES_BIN@#$HERMES_BIN#g" -e "s#@PROVIDER@#$PROVIDER#g" \
    "$HERE/systemd/hermes-account-balance.service.in" > "$UNIT_DIR/hermes-account-balance.service"
  if [ "$ROOT" != "$HOME/.hermes" ]; then
    sed -i "/^\[Service\]/a Environment=HERMES_HOME=$ROOT" "$UNIT_DIR/hermes-account-balance.service"
  fi
  cp "$HERE/systemd/hermes-account-balance.timer" "$UNIT_DIR/"
  systemctl --user daemon-reload
  systemctl --user enable --now hermes-account-balance.timer >/dev/null 2>&1
  systemctl --user start hermes-account-balance.service || echo "  first run failed; see: journalctl --user -u hermes-account-balance.service -n 20"
  echo "  $(systemctl --user is-active hermes-account-balance.timer): hermes-account-balance.timer"
fi

say "Check"
"$HERMES_BIN" account "$PROVIDER" doctor || true
echo
echo "Done. Start with: hermes account help"
echo "Running sessions pick up the tracker after /reset or a gateway/desktop restart."
