#!/bin/sh
# Scaffold a distributable dsh plugin package from the bundled template.
#
# Usage:
#   scripts/new-plugin.sh <target-directory> [--title "Human title"] [--description "One line"]
#
# The directory name is the package name and, by convention, the Loader row id
# and the browser bundle id all derive from it, so it must be a kebab-case name
# (`dsh-thing`). Everything else is substituted into the template.
#
# After it runs: `pnpm install`, `pnpm check`, then scripts/install.sh.
set -e

# Resolve the skill directory without changing the caller's working directory:
# a relative target must land beside the caller, not inside the skill.
SKILL_DIR=$(cd "$(dirname -- "$0")/.." && pwd)
TEMPLATE="$SKILL_DIR/assets/plugin-template"

TARGET=
TITLE=
DESCRIPTION=

while [ $# -gt 0 ]; do
  case "$1" in
    --title) TITLE=$2; shift 2 ;;
    --description) DESCRIPTION=$2; shift 2 ;;
    -*) echo "new-plugin: unknown option $1" >&2; exit 2 ;;
    *) TARGET=$1; shift ;;
  esac
done

[ -n "$TARGET" ] || { echo "usage: new-plugin.sh <target-directory> [--title T] [--description D]" >&2; exit 2; }
case "$TARGET" in
  /*) ;;
  *) TARGET="$PWD/$TARGET" ;;
esac
[ -d "$TEMPLATE" ] || { echo "new-plugin: template missing at $TEMPLATE" >&2; exit 1; }
[ ! -e "$TARGET" ] || { echo "new-plugin: $TARGET already exists" >&2; exit 1; }

NAME=$(basename "$TARGET")
case "$NAME" in
  @*/*) PACKAGE=$NAME; BARE=${NAME#*/} ;;
  *) PACKAGE=$NAME; BARE=$NAME ;;
esac

echo "$BARE" | grep -Eq '^[a-z][a-z0-9]*(-[a-z0-9]+)*$' || {
  echo "new-plugin: '$BARE' is not a kebab-case package name (try dsh-$BARE)" >&2
  exit 2
}

# The Loader row id and the client bundle id. Both must match the package name
# for the module system to accept the browser bundle.
PLUGIN_ID=$BARE

# camelCase panel/slot id shared by the sidebar row and the main page.
PANEL_ID=$(echo "$BARE" | awk -F- '{ printf "%s", $1; for (i = 2; i <= NF; i++) printf "%s%s", toupper(substr($i,1,1)), substr($i,2); print "" }')

if [ -z "$TITLE" ]; then
  TITLE=$(echo "$BARE" | tr '-' ' ' | awk '{ for (i = 1; i <= NF; i++) { $i = toupper(substr($i,1,1)) substr($i,2) } print }')
fi
if [ -z "$DESCRIPTION" ]; then
  DESCRIPTION="$TITLE — a DeepSeek Harness plugin"
fi

# Peer versions must match the runtime the user actually runs.
DSH_VERSION=$(node "$SKILL_DIR/scripts/dsh-sdk.mjs" version | awk -F': *' '/^dsh:/{ print $2 }')
[ -n "$DSH_VERSION" ] || { echo "new-plugin: could not read the installed dsh version" >&2; exit 1; }

# LICENSE holder: the git identity when there is one, else a neutral default.
YEAR=$(date +%Y)
HOLDER=$(git config user.name 2>/dev/null || true)
[ -n "$HOLDER" ] || HOLDER="$BARE contributors"

mkdir -p "$TARGET"
cp -R "$TEMPLATE/." "$TARGET/"

PLUGIN_NAME=$PACKAGE PLUGIN_ID=$PLUGIN_ID PANEL_ID=$PANEL_ID PLUGIN_TITLE=$TITLE \
PLUGIN_DESCRIPTION=$DESCRIPTION DSH_VERSION=$DSH_VERSION TARGET=$TARGET YEAR=$YEAR HOLDER=$HOLDER \
node --input-type=module -e '
import fs from "node:fs"
import path from "node:path"

const tokens = {
  __PLUGIN_NAME__: process.env.PLUGIN_NAME,
  __PLUGIN_ID__: process.env.PLUGIN_ID,
  __PANEL_ID__: process.env.PANEL_ID,
  __PLUGIN_TITLE__: process.env.PLUGIN_TITLE,
  __PLUGIN_DESCRIPTION__: process.env.PLUGIN_DESCRIPTION,
  __DSH_VERSION__: process.env.DSH_VERSION,
  __YEAR__: process.env.YEAR,
  __COPYRIGHT_HOLDER__: process.env.HOLDER,
}

const walk = (dir) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) { walk(full); continue }
    let body = fs.readFileSync(full, "utf8")
    const original = body
    for (const [token, value] of Object.entries(tokens)) body = body.split(token).join(value)
    if (body !== original) fs.writeFileSync(full, body)
  }
}
walk(process.env.TARGET)
'

chmod +x "$TARGET/scripts/install.sh" "$TARGET/scripts/dev-profile.sh"

cat <<EOF
new-plugin: scaffolded $TARGET

  package      $PACKAGE
  Loader row   $PLUGIN_ID
  panel id     $PANEL_ID
  dsh version  $DSH_VERSION

Next:
  cd $TARGET
  pnpm install
  pnpm check                 # typecheck both halves, build, then vitest
  scripts/install.sh         # pack dist/<name>-0.1.0.tgz and print the install path
EOF