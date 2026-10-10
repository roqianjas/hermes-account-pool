#!/usr/bin/env bash
# Remove the account-pool plugins, the session tracker and the systemd timer.
# Accounts in the credential pool are NOT touched. Parked accounts stay in
# $HERMES_HOME/account-pool-parked.json: unpark them before uninstalling if you
# want them back in rotation.
set -euo pipefail

ROOT="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"
export HERMES_HOME="$ROOT"

if [ -s "$ROOT/account-pool-parked.json" ] && grep -q '"id"' "$ROOT/account-pool-parked.json"; then
  echo "WARNING: there are parked accounts. They will stay out of rotation after uninstall."
  echo "         Unpark them first: hermes account <provider> list"
  read -r -p "Continue anyway? [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || exit 1
fi

systemctl --user disable --now hermes-account-balance.timer 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/hermes-account-balance.service" "$HOME/.config/systemd/user/hermes-account-balance.timer"
systemctl --user daemon-reload 2>/dev/null || true
echo "timer removed"

if [ -d "$ROOT/profiles" ]; then
  for d in "$ROOT"/profiles/*/; do
    prof="$(basename "$d")"
    if [ -L "$d/plugins/account-pool-tracker" ]; then
      "$HERMES_BIN" -p "$prof" plugins disable account-pool-tracker >/dev/null 2>&1 || true
      rm -f "$d/plugins/account-pool-tracker"
      echo "tracker removed from $prof"
    fi
  done
fi
"$HERMES_BIN" plugins disable account-pool-tracker >/dev/null 2>&1 || true
"$HERMES_BIN" plugins disable account-pool >/dev/null 2>&1 || true
rm -rf "$ROOT/plugins/account-pool" "$ROOT/plugins/account-pool-tracker"
echo "plugins removed"

echo
echo "Kept (delete by hand if you no longer need them):"
for f in account-pool-parked.json account-pool-sessions.json account-pool-history.jsonl account-pool-alerts.json account-pool.json; do
  [ -e "$ROOT/$f" ] && echo "  $ROOT/$f"
done
echo "credential_pool_strategies settings were left as they are."
