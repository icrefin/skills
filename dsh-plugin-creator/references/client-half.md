# The browser half

The page-side half. It enters through the package's `exports["./client"]`, loaded
as a bundle by the web client's module system. It is plain React in a Cordis
plugin.

**Contents**

- [How a bundle is produced](#how-a-bundle-is-produced)
- [Manifest](#manifest)
- [The client plugin](#the-client-plugin)
- [Injection is two gates](#injection-is-two-gates)
- [Finding the seat to render into](#finding-the-seat-to-render-into)
- [Styling and localization](#styling-and-localization)
- [Config forms](#config-forms)
- [Debugging what the page loaded](#debugging-what-the-page-loaded)

To take over a control the harness already ships, read
[`replacing-shipped-ui.md`](replacing-shipped-ui.md) as well.

## How a bundle is produced

The harness serves each client bundle from `/plugins/<package>/client.js` and the
browser executes it lazily. The bundle must therefore have exactly one shape:

```js
window.__ModuleLoader__.load({
  id: 'my-plugin',                    // MUST equal the package name
  factory: (require) => {
    var module = { exports: {} }
    // …module body…
    exports.apply = apply
    exports.inject = inject
    return module.exports
  },
})
```

Consequences worth knowing:

- **Executing the bundle only registers the factory.** Module-body side effects —
  including creating a `<style>` tag — happen at *materialization*, the first
  time the plugin is imported. Put style injection at the top level of your
  client entry so the module system claims the tag and removes it when the plugin
  is disabled.
- **The `id` is the boot graph row id.** A mismatch fails the load with
  `loaded without registering "<id>"`.
- **`require` resolves from a frozen platform seed table**, then memoized
  records, then boot-graph rows, then registered factories. React
  (`react`, `react/jsx-runtime`) and the static UI libraries
  (`@deepseek-ai/dsh-client-ui-primitives`, `@deepseek-ai/dsh-client-ui-slots`,
  `@deepseek-ai/dsh-client-store`, `@deepseek-ai/cordis`) are seeds. A bare
  package name that is another enabled bundle's row resolves to that package's
  client half.
- Do **not** install a second React: two Reacts in one page break hooks silently.

You do not have to write this file by hand. `tsdown` does it: the template's
`tsdown.config.ts` emits CJS with the loader banner/footer around a normal TSX
entry, and `external: ['react', 'react/jsx-runtime']` keeps React as the seed.
Everything else is bundled in, which is why the client half needs no runtime
dependencies.

## Manifest

```json
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": {
    "platform": "web",
    "inject": ["@deepseek-ai/dsh-client-locale", "@deepseek-ai/dsh-client-ui-layout", "@deepseek-ai/dsh-client-ui-sidebar"]
  }
}
```

- `dsh.client.platform` is required.
- `dsh.client.inject` is **activation ordering**: those bundles load before yours,
  so a slot they declare is already in the registry when you ask for it. List the
  packages that own the slots you register into, the services you inject, and any
  bundle whose client half you `require`.
- `dsh.client.external` is for **non-baseline runtime module requests** — exact
  specifiers that are neither a seed nor an enabled bundle's row. Composition
  rejects a malformed request, a missing supplier, a self-request, or a
  synchronous cycle, so add entries only when the page actually asks for them.
- `dsh.client.immediately: true` loads the bundle at boot instead of on demand.
  Use it only when something must exist before the user opens the surface, such
  as the plugin's own settings card.

`dsh.client.inject` never makes code importable by itself, and a type-only import
produces no runtime request at all.

## The client plugin

```ts
export const inject = ['slots', 'locale']

export function apply(ctx) {
  ctx.effect(() => ctx.locale.register('my-plugin', { en, zh }), 'my-plugin: dictionaries')
  const t = ctx.locale.bind('my-plugin')

  ctx.effect(() => ctx.slots.inject('sidebar.panellist', () =>
    ctx.slots.register({ name: 'sidebar.panellist', id: 'myPlugin', order: 50, label: () => t('panel') }, PanelIcon),
  ), 'my-plugin: sidebar entry')

  ctx.effect(() => ctx.slots.inject('main', () =>
    ctx.slots.register({ name: 'main', key: 'myPlugin', locale: 'my-plugin' }, Panel),
  ), 'my-plugin: main panel')
}
```

Registration discipline:

- **`slots.inject(ownerKey, callback)` waits for the declaration**; registering
  into an undeclared slot throws at load. The callback's registrations are
  disposed when the owning declaration collapses and reinstalled when it returns,
  which is why every call is wrapped in an effect.
- **Declaring a slot is claiming it.** Never declare a slot id you did not invent;
  register into the owner's seat instead.
- **Wrap `apply` in try/catch.** The web shell fails the whole boot when a
  plugin's `apply` throws, and an external plugin must not be able to take the
  GUI down.
- Slot kinds decide the options: `single` (one cell), `list` (one cell per `id`,
  rendered by `order`), `keyed` (one cell per `key`, e.g. `main`), `chain`
  (entries elect themselves with `select`).
- **Within a cell, the lowest `priority` renders.** `priority` sorts before
  `order` for lists, and registering a second entry for the same cell at the same
  priority **throws**. That is the shadowing mechanism — see
  [`replacing-shipped-ui.md`](replacing-shipped-ui.md) before registering into a
  seat that already has an occupant.
- Components receive their data through **selector hooks the renderer binds at
  the render position**, plus a translate seat when the registration carries
  `locale`. Subscribe to the smallest slice.
- A registration's `inject` may be a function of the session binding
  (`inject: (sessionId) => ({ … })`), and returning the resolved data behind a
  thunk is how a binding that is not ready yet repairs itself instead of retiring
  the entry.

## Injection is two gates

`export const inject = [...]` gates the whole plugin: cordis holds the fiber until
those services exist. `ctx.inject([...], (scope) => { … })` is a second, narrower
gate that runs only once *its* services are available, and hands back a scope
carrying them:

```ts
export const inject = ['slots', 'locale']

export function apply(ctx) {
  ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'my-plugin: dictionaries')

  ctx.inject(['slots', 'modelDirectories', 'sessions', 'remote', 'remote.session'], (scope) => {
    scope.effect(() => scope.slots.inject(SLOT, () => scope.slots.register({ … }, Seat)), 'my-plugin: seat')
  })
}
```

Use the second gate when the plugin can mount usefully without a service but one
registration cannot. And note what the example declares: **more than it reads.**

A cordis service is a **proxy — it rebinds `this` to the caller's context for the
duration of the call.** A service method that reaches a third service internally
therefore reads *your* `inject` list, not its own, on its cold path. The failure is
intermittent and cache-shaped: it appears only when your plugin is the first to
ask for something nobody warmed yet, and the error names a service you never
called (`cannot get property "remote.session" without inject`). When a service
misbehaves only for you, ask what *it* builds on a cache miss, and declare that
too. The full account is in
[`replacing-shipped-ui.md`](replacing-shipped-ui.md#declare-what-your-callee-needs).

## Finding the seat to render into

Never guess a slot id, and never read another plugin's DOM to position yourself.
Enumerate the documented seats and read the owner's README:

```sh
node scripts/dsh-sdk.mjs slots              # every documented seat id + its owners
node scripts/dsh-sdk.mjs slots conversation # filter
node scripts/dsh-sdk.mjs read dsh-client-ui-layout README.md
```

`references/surfaces.md` carries the catalogue captured from dsh 0.2.0-rc.2 and
the recipes for going deeper. Pick a seat that already allocates space; a
decoration belongs in a slot with room, not in an overlay you position by hand.

## Styling and localization

- **Theme tokens only** for anything that must match the harness:
  `--dsw-alias-bg-layer-1`, `--dsw-alias-border-l1`, `--dsw-alias-label-primary`,
  `--dsw-alias-label-secondary`, `--dsw-alias-state-error-primary`. Literal colors
  are for artwork. A renamed token degrades appearance; a literal color breaks
  dark mode.
- **Route visible text through the locale service.** Register a namespace and
  read it with `ctx.locale.bind(ns)`; never hard-code a user-facing string.
- **Prefer writing your own controls over importing host UI packages.** A
  primitive can change without notice, a plain-JS plugin has no type check, and a
  throwing component blanks your slot entry (`slot entry crashed in '<slot>'`). If
  you need a host control, read its markup and CSS from the shipped package
  (`node scripts/dsh-sdk.mjs read dsh-client-ui-primitives README.md`) and copy it
  under your own class prefix.
- **When you occupy a seat the host also styles, copy its CSS variables too.** A
  composer-row control must honour the display switches the host row sets (for the
  model control, `--dsh-composer-model-text-display` /
  `--dsh-composer-model-icon-display`), or the seat overflows exactly where the
  shipped one became compact.
- **Portalling needs ReactDOM from the platform table.** A hand-written menu that
  uses `createPortal` must keep `react-dom` external in `tsdown.config.ts` — and
  must **not** bundle it: a second React DOM breaks hooks and portals silently.
  `verification.md` has the bundle assertion that catches it.
- **Do not append to `document.body`,** do not replace the app root, and do not
  render a second application.
- Verify in both light and dark themes beside a comparable host page.

## Config forms

A settings card reads and writes the plugin's own Loader-entry `Config` — the
namespace equals the row id:

```ts
const scope = ctx.configForms.get('my-plugin')
ctx.effect(
  () => ctx.configForms.whileServed(['my-plugin'], () =>
    ctx.slots.inject('settings.models.footer', () =>
      ctx.slots.register({ name: 'settings.models.footer', id: 'my-plugin', order: 10, label: () => t('title') }, Card),
    ),
  ),
  'my-plugin: settings card',
)
```

`whileServed` keeps the card off a deployment that never composed the host half:
with no namespace there is nothing to read or write, and a card that cannot save
must not appear. Saving goes through the ordinary settings transport, and the
host is the only authority on whether a value was accepted.

## Debugging what the page loaded

- The browser console reports a failed bundle as
  `loaded without registering "<id>"`, a dependency cascade failure, or a factory
  exception.
- `slot entry crashed in '<slot>'` names the slot whose registration threw.
- Compute the bundle URL directly: `http://127.0.0.1:<port>/plugins/<package>/client.js`.
  Fetching it in the page is the fastest way to tell a build problem from a
  composition problem.