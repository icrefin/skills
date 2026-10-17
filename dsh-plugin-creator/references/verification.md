# Verifying a plugin

Four levels, cheapest first. Do not skip to installing: almost every failure that
reaches a live profile is one a static check would have caught.

**Contents**

- [1 — Static](#1--static)
- [2 — Behavioural](#2--behavioural)
- [3 — An isolated profile](#3--an-isolated-profile)
- [4 — The live harness](#4--the-live-harness)
- [What each level does not prove](#what-each-level-does-not-prove)
- [Verification limits](#verification-limits)

## 1 — Static

```sh
pnpm typecheck     # tsc over src/ (host) and src/client/ (browser)
pnpm build
node -e '
const fs = require("fs"), path = require("path")
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"))
const patch = pkg.dsh?.bundle?.patch
if (!patch || !fs.existsSync(patch)) throw new Error("no dsh.bundle.patch: " + patch)
if (pkg.dsh?.client?.platform !== "web") throw new Error("dsh.client.platform must be web")
const id = fs.readFileSync(patch, "utf8").match(/id:\s*(\S+)/)?.[1]
if (id !== pkg.name) throw new Error(`row id ${id} != package name ${pkg.name}`)
const banner = fs.readFileSync("lib/client.js", "utf8").slice(0, 200)
if (!banner.includes(`id: "${pkg.name}"`)) throw new Error("client bundle registers the wrong id:\n" + banner)
for (const file of ["lib/index.js", "lib/client.js", patch]) if (!pkg.files.includes(file.replace(/^\.\//, ""))) throw new Error(`files[] omits ${file}`)
console.log("manifest, patch row and client bundle id all agree on", pkg.name)
'
```

That single script catches the four failures that are otherwise discovered only
in the browser console: a missing patch, a non-web client declaration, a row id
that disagrees with the package name, and a client bundle bound to the wrong id.

Wire the three into `check` **in that order** — `"check": "pnpm typecheck && pnpm build && pnpm test"`
— because the bundle spec in the next section consumes the built artifact, and a
`check` that tests before building silently skips it.

`pnpm typecheck` is only as good as the types it sees. Install the
npm-published `@deepseek-ai/*` packages as devDependencies, pinned to the runtime
version (`node scripts/dsh-sdk.mjs version`). The shipped `app.asar` carries no
`.d.ts`, so without them `ctx.webServer` is `any` and a wrong slot registration
compiles happily.

## 2 — Behavioural

Test real code, not a mock of it.

**Host half.** Serve the route family from a real HTTP server on an ephemeral
loopback port and drive it with `fetch` — the template's `test/routes.spec.ts`
does exactly this and covers the happy path, a wrong method, and the payload
shape. Nothing about the handlers is stubbed, so the fences and status codes are
the shipped ones. Writing into a temporary directory rather than the real
`$DSH_HOME` keeps the test from touching user state.

**Browser half.** Execute the **built** `lib/client.js` behind a fake module
loader. Executing the emitted bundle is the point: it is the only check that
catches a broken loader banner, which fails the live page with
`loaded without registering "<id>"` and nothing else.

```ts
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const bundlePath = fileURLToPath(new URL('../lib/client.js', import.meta.url))
const built = existsSync(bundlePath)

function loadBundle() {
  let entry: { id: string; factory: (r: (s: string) => unknown) => Record<string, unknown> } | undefined
  const globals = globalThis as { window?: unknown }
  const previous = globals.window
  globals.window = { __ModuleLoader__: { load: (candidate) => { entry = candidate } } }
  try {
    const requireFromBundle = createRequire(bundlePath)
    new Function(readFileSync(bundlePath, 'utf8'))()        // executing the bundle IS the test
    const captured = entry!
    return { id: captured.id, exports: captured.factory((specifier) => requireFromBundle(specifier)) }
  } finally {
    if (previous === undefined) delete globals.window
    else globals.window = previous
  }
}

describe.skipIf(!built)('built client bundle', () => {
  it('registers under its package name — the boot graph row id', () => {
    expect(loadBundle().id).toBe('my-plugin')
  })

  it('exports the face the harness mounts', () => {
    const { exports } = loadBundle()
    expect(typeof exports.apply).toBe('function')
    expect(exports.inject).toEqual(inject)                  // import `inject` from the source
  })

  it('does not bundle a second copy of React or React DOM', () => {
    const source = readFileSync(bundlePath, 'utf8')
    expect(source).toContain('require("react")')
    // A bundled React brings its own copy of this internal marker.
    expect(source).not.toContain('__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED')
  })
})
```

Notes that make this work:

- `createRequire(bundlePath)` resolves the bundle's `require("react")` against the
  package's own `node_modules`, which is why React must be a devDependency.
- `describe.skipIf(!built)` keeps a source-only run green, with a visible skip.
  Make `check` build first, so a normal run always exercises it:
  `"check": "pnpm typecheck && pnpm build && pnpm test"`.
- The loader is *lazy*: `load()` captures the factory and nothing runs until
  `factory(require)` is called. Materialization is where the bundle's side effects
  fire, including style injection.

**Doubles that enforce the contract, not just satisfy it.** A structural double
for the registry and for any service you call should reproduce the rules the real
one has, so a missing declaration fails the suite instead of the GUI:

- the registry double throws on a **duplicate priority** for a `single`/`keyed`/
  `list` cell, and removes the registration when its disposer runs;
- a service double that internally reaches another service throws
  `cannot get property "<name>" without inject` unless the plugin's own exported
  `inject` list contains it.

Then assert through the **real `apply`**, not a hand-built registration: the
services passed to `ctx.inject`, the slot keys passed to `slots.inject`, the
locale namespaces registered, the exact options each `slots.register` received,
and that `disposeAll()` leaves nothing registered.

**Three rendering levels, cheapest first.**

| Level | Tool | Use it for |
|---|---|---|
| Markup | `renderToStaticMarkup` from `react-dom/server` | the label rule, which rows exist, empty and error faces |
| Interaction | `jsdom` + `react-dom/client` + `act` from `react-dom/test-utils` | open, drill, choose, search, keyboard walk, escape |
| Live | the running GUI | the only proof a user sees it |

Both first levels feed the component a real store double and the plugin's own
dictionary (`const t = (key) => en[key]` with `{name}` substitution) — never a
string the test itself assembled. Mark the interaction spec with
`// @vitest-environment jsdom` at the top of the file, and add `jsdom` to
devDependencies.

Worked examples against the real SDK live in this repository:

- `dsh-provider-model-picker/test/` — the bundle spec above, a registry/service
  double that enforces both contract rules, a seat spec driven through the real
  `apply`, static-markup render specs, and a jsdom interaction spec (81 cases).
- `dsh-model-retry-settings/test/` — an `app.asar` reader, a setup script that
  materializes the real `@deepseek-ai/*` packages, and Node module hooks that stub
  browser-only collaborators.
- `dsh-agent-prompt/test/` — route tests against a real loopback server, plus
  `tools/preview.mjs`, which renders the built client bundle outside the GUI.

Copy the technique, not the file: every harness is shaped around its own plugin.

## 3 — An isolated profile

Prove the composition accepts the plugin without risking the profile the desktop
app is using:

```sh
scripts/dev-profile.sh boot      # private $DSH_HOME under .dev-home/, own port
scripts/dev-profile.sh dump      # the composed row, proving the patch applied
scripts/dev-profile.sh url       # http://127.0.0.1:<port>/plugins/<package>/client.js
scripts/dev-profile.sh remove
```

Then check the two things that only a real boot can show:

```sh
curl -s http://127.0.0.1:19499/plugins/my-plugin/client.js | head -3   # banner id
curl -s http://127.0.0.1:19499/api/my-plugin/hello                     # host route
```

If the entry is missing from `dump`, the patch did not apply — usually a row id
that does not match, or a patch file not listed in `files`. If the bundle 404s,
`lib/client.js` was not built or is not in the package.

## 4 — The live harness

Install into the profile in use and restart, then reload the page.

- **Host half**: the plugin's own HTTP route, or the plugin inventory, or the
  plugin-manager tool's list, shows the row as enabled and its fiber as active.
- **Browser half**: the surface renders where the slot puts it, its text follows
  the language setting, and its colors follow the theme. Read the browser console:
  a failed bundle reports `loaded without registering "<id>"`, and a throwing
  component reports `slot entry crashed in '<slot>'`.
- **Registration, not just the row.** When the client inspection provider is
  composed, read the live slot tree. For a plugin that shadows a shipped seat the
  ledger must show **both** occupants — yours `active: true` at the lower priority
  and the shipped one `active: false` as the supervised fallback. That is the
  difference between "the registration landed" and "the registration was
  attempted", and it is available even when the visual check is not.
- **Both themes**: switch light and dark and look at the plugin beside a
  comparable host page. A literal color or a hard-coded label shows up here and
  nowhere else.
- **Disposal**: disable the plugin (or its bundle) and confirm the surface, its
  styles and its registrations all disappear, then enable it again and confirm it
  returns once — not twice.

## What each level does not prove

- Typecheck proves the API shape, not that the plugin mounts.
- A unit test proves the handler, not the composition.
- A composed row proves the harness accepted the plugin, not that a user can see
  anything.
- Only the live GUI proves the plugin renders as designed, and only the user's
  own page proves it in their theme and language.

State the weakest link in what you checked. "Installed and the entry is active" is
not the same claim as "the panel renders correctly", and the two should be
reported differently.

## Verification limits

Prefer the already-connected page for anything visual. Do not launch a separate
browser from shell commands, change `HOME`, inspect personal browser profiles,
search for authentication tokens, or alter keychains to obtain a screenshot. Do
not build a rasterizer, emulate React or the DOM, or produce a mock preview to
compensate for missing browser control: a screenshot of a mock is not evidence
about a running plugin.

When no browser control is available, verify the built bundle, the manifest, the
composed row and the live host route, then report the visual check as unperformed
rather than implied.