# Packaging and installing

A plugin reaches a profile as a **bundle**: an npm package whose manifest declares
`dsh.bundle.patch`, installed *into the profile* so the profile's composition
picks up its row.

Placement on disk is not installation. A directory that is merely present is
never composed, and the installation's module-interception layer can only resolve
the plugin's `@deepseek-ai/*` peers once the profile owns it as a dependency.

**Contents**

- [The three ids that must agree](#the-three-ids-that-must-agree)
- [Manifest](#manifest)
- [The patch row](#the-patch-row)
- [Installing into a profile](#installing-into-a-profile)
- [Iterating without touching the live profile](#iterating-without-touching-the-live-profile)
- [Distributing](#distributing)
- [Forking a plugin you do not own](#forking-a-plugin-you-do-not-own)
- [Pre-install checklist](#pre-install-checklist)

## The three ids that must agree

| Id | Where it lives |
|---|---|
| Package name | `package.json` `name`; also the client bundle's loader `id` |
| Loader row id | `cordis.patch.yml` `insert[].id`, and `export const name` in the host half |
| Settings namespace | the same row id — a Loader entry's `Config` *is* its namespace |

Add the client's panel key when the plugin renders a page. Get these wrong and the
failure is quiet at build time and loud at runtime: an unimportable entry, a
bundle rejected for registering the wrong id, or a settings card that can never
save.

## Manifest

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=22.17.0", "dsh": "0.2.0-rc.2" },
  "main": "lib/index.js",
  "exports": {
    ".": { "types": "./lib/types/index.d.ts", "default": "./lib/index.js" },
    "./client": "./lib/client.js",
    "./cordis.patch.yml": "./cordis.patch.yml",
    "./package.json": "./package.json"
  },
  "files": ["lib", "cordis.patch.yml", "README.md", "LICENSE"],
  "dsh": {
    "manifestVersion": 1,
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": { "platform": "web", "inject": ["@deepseek-ai/dsh-client-locale"] }
  }
}
```

- `dsh.bundle.patch` is one patch path or an ordered list of them, each relative
  to the package root; the launcher applies a list in order as one bundle layer.
- `engines.dsh` is an author-declared compatible range. Pin peer versions to the
  runtime you build against — `node scripts/dsh-sdk.mjs version` prints it — so a
  mismatch surfaces at install instead of at activation.
- `exports["./package.json"]` matters: the plugin inventory and the plugin hub
  read the manifest without activating the plugin.

## The patch row

```yaml
- insert:
    - id: my-plugin
      name: 'my-plugin'
      config: {}
```

The dialect, in one paragraph: `insert` appends rows; a patch with an `id` and no
`insert` targets the existing row with that id, and supplied fields replace the
row's fields — **`config` is replaced wholesale, never deep-merged**, so restate
every field the row needs. `disabled` accepts a boolean or a `!!js` expression
evaluated at every mount decision. `group: true` with `name: cordis:group` makes
`config` a nested entry list that further patches can insert into. Use `!!js`
(never `!js`); inside `config`, expressions are evaluated against that plugin's
own context.

For the full dialect and the inventory of installable packages, read the
`cordis-composition-reference` skill shipped with dsh:

```sh
node scripts/dsh-sdk.mjs read dsh-agent-preset skills/cordis-composition-reference/SKILL.md
```

## Installing into a profile

Profiles live under `$DSH_HOME/profiles/<name>` (default `~/.dsh`).

```sh
scripts/install.sh                    # npm pack, then print what to do
scripts/install.sh --profile tui      # pack and install into a CLI-managed profile
```

| Profile | How to install |
|---|---|
| CLI-managed (`dsh --profile <name>`) | `dsh plugin --profile <name> add <tarball-or-spec>` |
| **Desktop** | owned by the Electron app, so `dsh plugin add` refuses it: use **Settings → Plugins**, or the plugin-manager tool |

The plugin-manager tool, when the composition includes it, exposes
`install_bundle` / `list_plugins` / `list_bundles` / `set_plugin` / `set_bundle` /
`remove_bundle`. Read its result rather than the terminal: `application: applied`
means live, `restart-required` means not yet, `overridden` means a higher-priority
layer wins, and `failed` needs diagnosis.

Install, then confirm, then look:

```sh
dsh --profile <name> --dump-config | grep -A2 'id: my-plugin'
```

### Install a packed tarball, not a directory

A `link:` dependency points outside the profile's `node_modules`, so the host can
reach it only once it has registered that path as a linked root — which happens
at boot. A packed tarball installs as a real directory under
`<profile>/node_modules/`, the same shape a registry plugin has. That is why
`scripts/install.sh` packs before it installs.

Two operational facts that look like bugs and are not:

- **A bundle added to a running profile generally needs a restart.** The new
  module path is not in the resolution the host computed at boot, so the entry
  reports `failed to import` and stays inactive until the next start. Any newly
  added bundle behaves this way.
- **Reinstalling the same version is a no-op.** pnpm sees an unchanged spec and
  leaves the extracted copy alone, so a rebuilt tarball at the same version never
  reaches the profile. Remove the bundle first, or bump the version.

A **client half** is a third case, and the sequence is worth knowing because the
host half goes active immediately while the page may not: the running page only
loads the bundles its boot graph handed it, so an already-open window can keep
showing the old control after a successful install. **Reload the window first;**
if the surface still does not change, restart the app. Do not conclude the
registration failed before trying the reload.

### A local install pins the tarball path

Installing a tarball by path records the **path**, not the package: the profile's
`package.json` gets
`"my-plugin": "file:…/dist/my-plugin-<version>.tgz"`. Delete or replace that file
and the *next* install fails with `ENOENT` before it can update anything.

So keep the packed tarball where it was installed from, or remove the bundle
before installing the new one — and never reuse a version number across builds.

## Iterating without touching the live profile

`scripts/dev-profile.sh` (in the template) creates a private `$DSH_HOME` under
`.dev-home/`, initializes a profile from the shipped `web` template, installs the
package with `link:`, and boots on its own port. A fresh boot composes the profile
with the plugin already in it, so its entry activates without the restart dance.
It writes nothing outside the package.

## Distributing

- `npm pack` honours the `files` whitelist: ship `lib/` (both halves), the patch,
  the README and the LICENSE. Never ship `src/`, tests, or `.dev-home/`.
- **Pack with `pnpm pack --pack-destination dist`, not `npm pack`.** npm needs a
  writable `~/.npm` for its log and cache, and fails with a write error under a
  sandboxed or read-only home — the exact condition an agent run is usually in.
  `pnpm pack` needs no npm cache and creates the destination directory itself.
  Note that `pnpm pack` does **not** run a `pack` script: use `pnpm run pack` when
  the script is what builds first.
- The browser half must be **built before packing**. The host serves built client
  bundles, and a missing one fails activation loudly with a build instruction. Have
  the install script build rather than trusting a stale `lib/`.
- Version every behaviour change. Nothing else in the pipeline re-installs an
  unchanged version.
- Publishing to npm is optional: a tarball path, a git spec, or a local registry
  all install the same way. Whatever you choose, keep the tarball reproducible.
- **Check the tarball's contents, not just its existence**, the first time a
  package layout changes — a `files` whitelist that omits `cordis.patch.yml`
  produces an install that composes nothing, with no error until the profile is
  dumped.

## Forking a plugin you do not own

Changing a shipped or third-party plugin means changing a package that lives in
`node_modules`, where the next `pnpm install` overwrites it. Two durable forms:

1. **A `pnpm patch` file** — generated with `pnpm patch <pkg>`, committed under
   `patches/`, and registered in `package.json`'s `pnpm.patchedDependencies`. Any
   install in the profile re-materializes the package with the patch applied, and
   the patch is a machine-applicable record of exactly what changed. This
   repository's `dsh-mcp-mgr` is the worked example: `patches/` carries the
   delta, `tools/` carries a source-build pipeline and a verifier that reproduces
   the vendored files from the npm tarball byte-for-byte.
2. **A vendored package directory** plus a script that rebuilds it from the
   published tarball and reapplies your edits. Use this when the change is easier
   to express as an idempotent transform than as a patch — `dsh-skill-hub`'s
   `tools/fix-skill-hub-theme.mjs` reports `SKIP` when the edits are already in
   place and `REFUSED`, naming every anchor it could not find, rather than
   writing a half-applied bundle.

Either way, the durable record is the **built artifact** the profile loads. Commit
it, or commit a command that reproduces it byte-for-byte — not both halves of the
story in different places. In this repository the choice is per plugin and stated
in the root README: plugins distributed as built output commit `lib/`, while a
plugin built from source (`pnpm pack` runs `pnpm build` first) gitignores it like
any other build product.

## Pre-install checklist

- [ ] `pnpm check` passes — typecheck both halves, build, then tests.
- [ ] `pnpm build` produced `lib/index.js` **and** `lib/client.js`.
- [ ] The client bundle's banner `id` equals the package name.
- [ ] The manifest/bundle check script agrees on all four ids.
- [ ] The patch row id equals `export const name` and the package name.
- [ ] `cordis.patch.yml` and `package.json` are both in `files`.
- [ ] The tarball path recorded by the profile still exists (or the bundle was
      removed before this install).
- [ ] Every route carries a loopback fence if it mutates anything.
- [ ] Every user-visible string goes through the locale service.