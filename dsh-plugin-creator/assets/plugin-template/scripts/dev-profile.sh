#!/bin/sh
# Boot __PLUGIN_NAME__ inside an ISOLATED dsh profile, without touching the
# profile the desktop app is using.
#
# It creates a private dsh home under `.dev-home/` (gitignored), initializes a
# profile from the shipped `web` template, installs this package into it as a
# `link:` dependency, and boots the web UI on its own port.
#
# Why this exists: it is the only way to prove the host half mounts, the client
# bundle reaches the boot graph, and the slot registration lands — all without
# risking the live profile. It writes nothing outside this package.
#
# Usage:
#   scripts/dev-profile.sh boot [port]     create if needed, then boot
#   scripts/dev-profile.sh dump            print the composed profile tree
#   scripts/dev-profile.sh url [port]      print the served client bundle URL
#   scripts/dev-profile.sh remove          delete .dev-home entirely
#
# Environment:
#   DSH_APP   path to "DeepSeek Harness.app" (default: /Applications/...)
set -e
cd "$(dirname -- "$0")/.."

PACKAGE_DIR=$(pwd)
DEV_HOME="$PACKAGE_DIR/.dev-home"
PROFILE=__PLUGIN_ID__-dev
APP=${DSH_APP:-/Applications/DeepSeek Harness.app}
PORT=${2:-19499}

DSH_BIN="$APP/Contents/Resources/runtime/cli/bin/dsh"
export DSH_DESKTOP_NODE_EXECUTABLE="$APP/Contents/MacOS/DeepSeek Harness"
export DSH_HOME="$DEV_HOME"
# `dsh plugin add` shells out to pnpm. Pin its store inside the isolated home so
# nothing lands beside this package, and so the script also works under a file
# sandbox that forbids the user's global store (`--config.<key>` is how pnpm
# receives a setting it does not own a flag for).
STORE_DIR="$DEV_HOME/.pnpm-store"
# The desktop app's own environment must not leak into the isolated profile.
unset DSH_PROFILE DSH_PROFILE_DIR DSH_SESSION_ID DSH_SHELL DSH_WEB_URL

if [ ! -x "$DSH_BIN" ]; then
  echo "dev-profile: no dsh CLI at $DSH_BIN — set DSH_APP to the app bundle you want to test against" >&2
  exit 1
fi

command=${1:-boot}

if [ "$command" = "remove" ]; then
  rm -rf "$DEV_HOME"
  echo "dev-profile: removed $DEV_HOME"
  exit 0
fi

if [ ! -d "$DEV_HOME/profiles/$PROFILE" ]; then
  echo "dev-profile: initializing $DEV_HOME (a private dsh home, safe to delete)"
  mkdir -p "$DEV_HOME"
  "$DSH_BIN" --profile "$PROFILE" --from-default-profile web --dump-config > /dev/null
  "$DSH_BIN" plugin --profile "$PROFILE" add "$PACKAGE_DIR" "--config.store-dir=$STORE_DIR" > /dev/null
  "$DSH_BIN" --profile "$PROFILE" --dump-config > "$DEV_HOME/composed.yml"
fi

case "$command" in
  dump)
    grep -B 1 -A 2 'id: __PLUGIN_ID__' "$DEV_HOME/composed.yml"
    ;;
  url)
    echo "http://127.0.0.1:$PORT/plugins/__PLUGIN_NAME__/client.js"
    ;;
  boot)
    echo "dev-profile: composed entry:"
    grep -A 1 'id: __PLUGIN_ID__' "$DEV_HOME/composed.yml" | sed 's/^/  /'
    echo "dev-profile: booting on http://127.0.0.1:$PORT (Ctrl-C to stop)"
    exec "$DSH_BIN" --profile "$PROFILE" --host 127.0.0.1 --port "$PORT" --no-open
    ;;
  *)
    echo "usage: $0 [boot|dump|url|remove] [port]" >&2
    exit 2
    ;;
esac