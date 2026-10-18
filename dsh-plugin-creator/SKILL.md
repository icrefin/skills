---
name: dsh-plugin-creator
description: Build, verify, and package DeepSeek Harness (dsh) plugins as installable npm bundles — host halves, browser halves, sidebar panels and settings seats, config schemas, cordis patch rows, and installation into a profile. Use when creating a new dsh/DSH plugin or Cordis bundle, when adding a panel, page, settings card, agent tool, background policy, or HTTP API to the Harness, when forking or repairing an installed dsh plugin, or when packaging and verifying a plugin against an installed DSH runtime.
---

# Building a dsh plugin

A plugin is a **bundle**: an npm package plus one Loader row. The package can carry
two halves — a host half in the harness process (`exports["."]`) and a browser
half in the page (`exports["./client"]`) — and the row mounts the host half while
the manifest's `dsh.client` declaration loads the browser half.

```
my-plugin/
├── package.json          "dsh.bundle.patch" + "dsh.client"   ← makes it a bundle
├── cordis.patch.yml      insert: [{ id, name }]              ← the Loader row
├── src/index.ts          host half: services, routes, events, tools
├── src/routes.ts         host HTTP surface
├── src/protocol.ts       wire contract BOTH halves import
├── src/client/index.tsx  browser half: slots, locale
└── test/                 real-code tests
```

Three ids must agree everywhere: **package name**, **row id** (`cordis.patch.yml`,
`export const name`), and — for a settings card — the **namespace**, which is the
row id because a Loader entry's `Config` *is* its settings namespace. The client
bundle must additionally register under the package name.

Paths below are relative to this skill's directory, which the `skill` tool
reported. Work in the user's workspace, never inside this skill directory.

## Workflow

1. **Choose the surface before writing any view.** A host-only plugin, a
   dual-face plugin, a decoration, or a fork of a plugin you do not own. See
   `references/surfaces.md` — this decision cannot be recovered later by styling.
   Say which one it is out loud: **adding** to a seat, **replacing** a control the
   harness already ships (`references/replacing-shipped-ui.md`), or **forking** a
   package you do not own (`references/packaging.md`). Replacing means owning
   everything the shipped occupant did.
2. **Scaffold** a package in the user's workspace:

   ```sh
   scripts/new-plugin.sh <target-dir> --title "Human Title" --description "One line"
   cd <target-dir> && pnpm install
   ```

   The template is a working dual-face plugin: an HTTP route, a sidebar row, a
   page, locale dictionaries, real tests, and an isolated-profile dev script. It
   typechecks, builds and tests clean against dsh 0.2.1-rc.2 — replace what you do
   not need rather than starting from empty files.
3. **Implement the host half** — `references/host-half.md`: export forms,
   `ctx.effect`, schemastery `Config`, event and waterfall listeners, `webServer`
   routes with the loopback fence, `ctx.tools.register(defineTool(…))`.
4. **Implement the browser half** — `references/client-half.md`: the module
   loader's factory form, the `dsh.client` manifest, slot registration discipline,
   the two injection gates, theme tokens, locale, config forms.
5. **Build**: `pnpm check` — typecheck both halves, **build**, then vitest, in that
   order, because the bundle spec consumes the built artifact.
6. **Verify before installing** — `references/verification.md`: manifest and
   bundle-id checks, tests that drive real code, the built bundle behind a fake
   module loader, then an isolated profile via `scripts/dev-profile.sh`.
7. **Package and install** — `references/packaging.md`: pack a tarball, install
   it into the profile, reload the page, restart.

## Read the installed harness, not your assumptions

The desktop app ships its runtime inside `app.asar`, which `cat`, `cp`, ripgrep
and pnpm cannot open. Use the bundled reader:

```sh
S=scripts/dsh-sdk.mjs

node $S version                  # archive path, dsh version, package count
node $S list host-webserver      # find a package by name
node $S read dsh-host-webserver README.md
node $S find 'ctx\.tools\.register'
node $S slots                    # documented UI seat ids and their owners
node $S extract dsh-tools ./sdk  # materialise a package to read or import
```

- **A package's README is its contract**: it documents the Context augmentation
  (which services exist), the Events with their dispatch mode, and the Config
  fields. `lib/index.js` is the implementation of record, JSDoc intact.
- The generated inventory of every installable plugin package — and the Loader
  patch dialect — is inside the bundled composition reference:

  ```sh
  node scripts/dsh-sdk.mjs read dsh-agent-preset skills/cordis-composition-reference/references/packages.md
  ```

- Deeper guidance ships with dsh too, and is worth reading once end to end:
  `node scripts/dsh-sdk.mjs read dsh-agent-preset skills/cordis-plugin-development/SKILL.md`.
- When the harness runs with the Cordis preset, live inspection
  (`cordis_inspect_query` for `Service`, `Event`, `Slots`, `Theme`,
  `Config.listConfigs`) beats reading: it reports the actual runtime.
- For editor-level types, add the npm-published `@deepseek-ai/*` packages as
  devDependencies pinned to the runtime version `$S version` prints. Shipped
  packages carry no `.d.ts`, so without them a wrong slot id compiles cleanly.

## Rules that are not optional

- **Register inside `ctx.effect(fn, label)`** and return the disposer. Cordis runs
  it on unload, on a profile-patch disable, and at shutdown. A bare `register()`
  leaks past unload and breaks hot reload.
- **A client bundle's loader `id` must equal the package name.** A mismatch fails
  the load with `loaded without registering "<id>"`.
- **Never declare a slot you did not invent.** `slots.inject(ownerKey, cb)` waits
  for the declaration; registering into an undeclared slot throws at load.
- **To change a shipped control, shadow it — do not replace it.** Register the same
  seat at a **lower `priority`** and leave the shipped entry in place: it stays the
  supervised fallback if your render throws. Registering the same cell at the same
  priority **throws**. See `references/replacing-shipped-ui.md`.
- **Declare the services your *callee* needs.** A cordis service proxy rebinds
  `this` to the **caller's** context, so a service that reaches a third service on
  its cold path reads *your* `inject` list. The failure is intermittent and
  cache-shaped: `cannot get property "<name>" without inject`.
- **Nothing in a slot registration's `inject` factory may throw, and values
  crossing a plugin boundary must be normalized.** `inject` runs inside the
  renderer, and a throw there retires your entry silently for the page's life.
  Guard the factory, guard `getSnapshot`/`subscribe`, and treat every foreign
  field as optional.
- **Fence your routes.** Named routes are matched before the authenticated SPA
  fallback and are not covered by the launch token, so anything that mutates state
  checks loopback, method and body size itself.
- **Style with `--dsw-alias-*` tokens and route text through the locale service.**
  Literal colors break dark mode; hard-coded strings ignore the language setting.
- **Do not import host UI packages into the client half.** A primitive can change
  without notice and a throwing component blanks your slot entry. Write your own
  control, or copy the host's markup and CSS under your own class prefix.
- **Wrap the client `apply` in try/catch**: the shell fails the whole boot when a
  plugin's `apply` throws.
- **Install the packed tarball, not the directory.** A `link:` dependency is only
  reachable once the host has registered that path as a linked root at boot.
- **Adding a bundle to a running profile needs a restart**, and reinstalling the
  same version is a silent no-op. Bump the version or remove the bundle first. A
  local install also pins the tarball's **path** — delete that file and the next
  install fails with `ENOENT`.
- **A client half may not reach an already-open page.** The host row goes active
  immediately; if the surface still shows the old control, reload the window
  before concluding anything, and restart only if the reload does not take.
- **Do not hand-edit a profile's `package.json` or `cordis.patch.yml`,** and do
  not run pnpm inside the profile directory, when the plugin-manager tool is
  available: `install_bundle` performs those steps. Read its result
  (`application`, `warnings`) instead of inferring success from logs.

## Reporting

Say which level you actually verified: typecheck, a behavioural test, the built
bundle materialized behind a fake loader, a composed row in an isolated profile,
the live slot ledger, or the rendered GUI. "Installed and the entry is active" is
not the claim "the panel renders correctly in both themes", and a shadowed seat
reporting `active: true` at the lower priority is a different claim from the
surface looking right. When no browser control is available, verify the manifest,
the built bundle, the composed row and the live registration, then state plainly
that the visual check was not performed — do not build a mock preview and present
it as evidence.

## What is in this skill

| Path | Read it when |
|---|---|
| `references/host-half.md` | writing the host half: exports, Config, events, routes, tools |
| `references/client-half.md` | writing the browser half: bundle form, manifest, slots, injection, styling |
| `references/replacing-shipped-ui.md` | changing a control the harness already ships |
| `references/surfaces.md` | choosing the surface, or looking up a UI seat or extension point |
| `references/packaging.md` | manifest fields, patch rows, install and distribution, forking |
| `references/verification.md` | deciding what to test, and what a test does not prove |
| `scripts/dsh-sdk.mjs` | reading, searching or extracting the installed SDK |
| `scripts/new-plugin.sh` | scaffolding a new plugin package |
| `assets/plugin-template/` | the scaffold's source; read it as the canonical working example |