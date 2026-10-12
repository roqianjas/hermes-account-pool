#!/usr/bin/env bash
# Install the account-pool plugin for Hermes Agent from this checkout.
#
#   ./install.sh [--provider NAME]... [--set-strategy] [--no-timer]
#
# --provider      provider(s) to run setup for; repeat for several (default: anthropic).
#                 The timer balances every provider with accounts whichever you name.
# --set-strategy  set credential_pool_strategies.<provider>=fill_first in every profile
#                 that has another value (needed by balance)
# --no-timer      skip the systemd user timer that runs `balance` every 5 minutes
#
# After copying the plugin it runs `hermes account <provider> setup --yes`, the same
# step that follows `hermes plugins install`. Setup also links the plugin into every
# profile (session tracking) and removes the retired account-pool-tracker plugin
# (before 4.0), whose copy is backed up here first.
set -euo pipefail

PROVIDERS=()
SET_STRATEGY=0
TIMER=1
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDERS+=("${2:?--provider needs a value}"); shift 2 ;;
    --set-strategy) SET_STRATEGY=1; shift ;;
    --no-tracker) echo "  --no-tracker is gone: session tracking is part of account-pool since 4.0"; shift ;;
    --no-timer) TIMER=0; shift ;;
    -h|--help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

[ ${#PROVIDERS[@]} -gt 0 ] || PROVIDERS=(anthropic)
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="$(command -v hermes || true)"
[ -n "$HERMES_BIN" ] || HERMES_BIN="$HOME/.local/bin/hermes"
[ -x "$HERMES_BIN" ] || { echo "hermes not found on PATH or in ~/.local/bin" >&2; exit 1; }
[ -d "$ROOT" ] || { echo "Hermes home not found: $ROOT" >&2; exit 1; }
export HERMES_HOME="$ROOT"

say() { printf '\n== %s\n' "$*"; }

say "Installing account-pool into $ROOT/plugins"
mkdir -p "$ROOT/plugins"
STAMP="$(date +%Y%m%d-%H%M%S)"
for p in account-pool account-pool-tracker; do
  if [ -e "$ROOT/plugins/$p" ] && [ ! -L "$ROOT/plugins/$p" ]; then
    mkdir -p "$ROOT/plugin-backups"
    cp -a "$ROOT/plugins/$p" "$ROOT/plugin-backups/$p.$STAMP"   # outside plugins/: never loaded twice
    echo "  previous $p backed up to $ROOT/plugin-backups/$p.$STAMP"
  fi
done
rm -rf "$ROOT/plugins/account-pool"
cp -a "$HERE/plugins/account-pool" "$ROOT/plugins/account-pool"
find "$ROOT/plugins/account-pool" -name __pycache__ -prune -exec rm -rf '{}' +
echo "  account-pool -> $ROOT/plugins/account-pool"
"$HERMES_BIN" plugins enable account-pool >/dev/null && echo "  enabled account-pool (default profile: the command)"

# Profiles, session tracking, timer and strategy: one implementation, shared with `hermes plugins install`.
SETUP=(--yes)
[ "$TIMER" = 1 ] && SETUP+=(--timer)
[ "$SET_STRATEGY" = 1 ] && SETUP+=(--strategy)
for PROVIDER in "${PROVIDERS[@]}"; do
  say "hermes account $PROVIDER setup ${SETUP[*]}"
  "$HERMES_BIN" account "$PROVIDER" setup "${SETUP[@]}" || echo "  setup reported a problem (see above); doctor below names it"
done

say "Check"
for PROVIDER in "${PROVIDERS[@]}"; do "$HERMES_BIN" account "$PROVIDER" doctor || true; done
echo
echo "Done. Start with: hermes account help"
echo
echo "Hermes Desktop page (optional): restart Hermes Desktop so it loads the page's backend,"
echo "then in Capabilities > Plugins switch on the Desktop half of account-pool. Accounts appears in the sidebar."
