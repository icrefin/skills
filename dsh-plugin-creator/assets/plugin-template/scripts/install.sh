#!/bin/sh
# Pack __PLUGIN_NAME__ into dist/ and print how to install it.
#
# Why a tarball and not `dsh plugin add /this/directory`: a `link:` dependency
# points OUTSIDE the profile's node_modules, so it is only reachable once the
# harness host has registered that path as a linked root — which happens at
# boot. A packed tarball installs as a real directory under
# `<profile>/node_modules/`, the same shape a registry plugin has, so the
# installation's module-interception layer resolves its peers immediately.
#
# Usage:
#   scripts/install.sh                 pack, then print instructions
#   scripts/install.sh --profile tui   pack, then install into a CLI-managed profile
set -e
cd "$(dirname -- "$0")/.."

PROFILE=
if [ "$1" = "--profile" ]; then
  PROFILE=$2
  [ -n "$PROFILE" ] || { echo "usage: $0 [--profile <name>]" >&2; exit 2; }
fi

NAME=$(node -p "require('./package.json').name")
VERSION=$(node -p "require('./package.json').version")
# `pnpm pack`, not `npm pack`: npm needs a writable ~/.npm for its log and cache,
# which a sandboxed or read-only home does not provide. pnpm pack also creates
# the destination directory. Build first — the tarball must carry both halves.
pnpm build > /dev/null
mkdir -p dist
pnpm pack --pack-destination dist > /dev/null
TARBALL="$(pwd)/dist/$NAME-$VERSION.tgz"
echo "packed $TARBALL"
echo

if [ -z "$PROFILE" ]; then
  cat <<EOF
Install it from the app:  Settings → Plugins → install, and give it this path:

    $TARBALL

The desktop profile is owned by the Electron application, so \`dsh plugin add\`
refuses it; the Plugins page (or the plugin-manager tool) is the supported path.

After installing, RESTART the app. A bundle added to a running profile cannot be
imported by that process: its module path is not in the resolution the harness
computed at boot, so the entry reports "failed to import" until the next start.
EOF
else
  APP=${DSH_APP:-/Applications/DeepSeek Harness.app}
  export DSH_DESKTOP_NODE_EXECUTABLE="$APP/Contents/MacOS/DeepSeek Harness"
  "$APP/Contents/Resources/runtime/cli/bin/dsh" plugin --profile "$PROFILE" add "$TARBALL"
  echo
  echo "restart the harness that serves profile '$PROFILE' for the entry to activate."
fi