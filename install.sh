#!/usr/bin/env bash
# Install the account-pool plugins for Hermes Agent from this checkout.
#
#   ./install.sh [--provider NAME]... [--set-strategy] [--no-tracker] [--no-timer]
#
# --provider      provider(s) the timer balances; repeat for several (default: anthropic)
# --set-strategy  set credential_pool_strategies.<provider>=fill_first in every profile
#                 that has another value (needed by balance)
# --no-tracker    skip the session tracker (`hermes account <provider> who` stays empty)
# --no-timer      skip the systemd user timer that runs `balance` every 5 minutes
#
# After copying the plugins it runs `hermes account <provider> setup --yes`, the same
# step that follows an install from the Hermes plugin catalog.
set -euo pipefail

PROVIDERS=()
SET_STRATEGY=0
TRACKER=1
TIMER=1
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDERS+=("${2:?--provider needs a value}"); shift 2 ;;
    --set-strategy) SET_STRATEGY=1; shift ;;
    --no-tracker) TRACKER=0; shift ;;
    --no-timer) TIMER=0; shift ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
"$HERMES_BIN" plugins enable account-pool >/dev/null && echo "  enabled account-pool (default profile: the command)"

# Profiles, tracker, timer and strategy: one implementation, shared with catalog installs.
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
