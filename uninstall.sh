#!/usr/bin/env bash
# Remove the account-pool plugin (with the Hermes Desktop page and its session tracking in every
# profile), the retired account-pool-tracker plugin if it is still there, and the systemd timer.
# Accounts in the credential pool are NOT touched. A parked account stays in the pool, held out of
# rotation by Hermes until its park time ends (a park without an end time: up to 30 days); unpark
# it before uninstalling, or return every held account at once with `hermes auth reset <provider>`.
set -euo pipefail

ROOT="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"
export HERMES_HOME="$ROOT"

PARKED=""
for f in account-pool-parking.json account-pool-parked.json; do
  if [ -s "$ROOT/$f" ] && grep -q '"id"' "$ROOT/$f"; then PARKED="$ROOT/$f"; fi
done
if [ -n "$PARKED" ]; then
  echo "WARNING: there are parked accounts. Hermes keeps them out of rotation until their park time ends."
  echo "         Unpark them first (hermes account <provider> list), or afterwards: hermes auth reset <provider>"
  read -r -p "Continue anyway? [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || exit 1
fi

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
systemctl --user disable --now hermes-account-balance.timer 2>/dev/null || true
rm -f "$UNIT_DIR/hermes-account-balance.service" "$UNIT_DIR/hermes-account-balance.timer"
systemctl --user daemon-reload 2>/dev/null || true
echo "timer removed"

if [ -d "$ROOT/profiles" ]; then
  for d in "$ROOT"/profiles/*/; do
    prof="$(basename "$d")"
    for p in account-pool account-pool-tracker; do
      if [ -L "$d/plugins/$p" ]; then
        [ "$p" = account-pool-tracker ] && { "$HERMES_BIN" -p "$prof" plugins disable "$p" >/dev/null 2>&1 || true; }
        rm -f "$d/plugins/$p"
        echo "$p link removed from $prof"
      fi
    done
  done
fi
"$HERMES_BIN" plugins disable account-pool-tracker >/dev/null 2>&1 || true
"$HERMES_BIN" plugins disable account-pool >/dev/null 2>&1 || true
# install.sh listed account-pool in every profile for the Accounts page backend
if [ -d "$ROOT/profiles" ]; then
  for d in "$ROOT"/profiles/*/; do
    prof="$(basename "$d")"
    [ -f "$d/config.yaml" ] || continue
    cur="$("$HERMES_BIN" -p "$prof" config get plugins.enabled --json 2>/dev/null || true)"
    case "$cur" in *'"account-pool"'*) ;; *) continue ;; esac
    new="$(printf '%s' "$cur" | sed -E 's/"account-pool"[[:space:]]*,[[:space:]]*//; s/,[[:space:]]*"account-pool"//; s/"account-pool"//')"
    "$HERMES_BIN" -p "$prof" config set plugins.enabled "$new" >/dev/null && echo "account-pool unlisted in $prof"
  done
fi
rm -rf "$ROOT/plugins/account-pool" "$ROOT/plugins/account-pool-tracker"
# Hermes Desktop's copy of the Accounts page (it would also go on the app's next start)
if [ -f "$ROOT/desktop-plugins/account-pool/.hermes-package.json" ]; then
  rm -rf "$ROOT/desktop-plugins/account-pool"
fi
echo "plugins removed"

echo
echo "Kept (delete by hand if you no longer need them):"
for f in account-pool-parking.json account-pool-parked.json account-pool-sessions.json account-pool-tokens.json account-pool-history.jsonl account-pool-activity.jsonl account-pool-alerts.json account-pool-state.json account-pool.json; do
  [ -e "$ROOT/$f" ] && echo "  $ROOT/$f"
done
echo "credential_pool_strategies settings were left as they are."
