# The host half

The Node-side half of a plugin. It enters through the package's `exports["."]`
and one Loader row, and it runs in the harness process — not in the page.

**Contents**

- [Export forms](#export-forms)
- [Lifecycle](#lifecycle)
- [Config and settings](#config-and-settings)
- [Events and waterfalls](#events-and-waterfalls)
- [HTTP routes](#http-routes)
- [Registering a model-facing tool](#registering-a-model-facing-tool)
- [Verify the host half before installing](#verify-the-host-half-before-installing)

A plugin that only changes shipped **browser** UI still needs a host half, even an
empty one: the row mounts `exports["."]`, and it is the row that carries the
`dsh.client` declaration into the boot graph.

```ts
export const name = 'my-plugin'
/** No route, no service, no Config — the row exists to carry the client half. */
export function apply(): void {}
```

## Export forms

`index.ts` exports one of these. Do not mix them.

```ts
import z from '@deepseek-ai/schemastery'

export const name = 'my-plugin'          // must equal the cordis.patch.yml row id
export const inject = ['webServer']      // services that must exist before apply()
export const Config = z.object({ … })    // optional: the row's config schema

export function apply(ctx, config) { … }
```

The alternative is a service class as the default export. For a plugin that only
observes or registers, prefer `apply`.

`inject` is not decoration: a missing entry there means the plugin mounts before
its collaborator exists and sees `undefined`. List a service only when the plugin
cannot work without it — put optional ones behind `ctx.get('name')`, which returns
`undefined` instead of holding the fiber back. `ctx.inject([...], (scope) => …)` is
a narrower second gate; both are covered in
[`client-half.md`](client-half.md#injection-is-two-gates), including the rule that
you sometimes must declare a service you never call.

## Lifecycle

Every registration lives inside `ctx.effect(callback, label)`, whose callback
returns the disposer (or `void`):

```ts
ctx.effect(() => {
  const disposers = makeRoutes(ctx).map((route) => ctx.webServer.register(route))
  return () => { for (const dispose of disposers) dispose() }
}, 'my-plugin: routes')
```

Cordis runs that cleanup when the plugin unloads, when a profile patch disables
its row, and at process shutdown. A bare `register()` outside an effect leaks the
registration past unload and breaks hot reload.

`ctx.on(event, listener, options)` registers an event and returns its own
disposer, so it can be used directly or wrapped in an effect. `ctx.logger`
(`info`/`debug`/`warn`/`error`) takes printf-style arguments.

## Config and settings

`Config` is a schemastery schema validated at activation against the row's
`config` in the profile's YAML. A schema-less row accepts no config at all.

```ts
export const Config = z.object({
  enabled: z.boolean().default(true).volatile(),
  maxRetries: z.number().step(1).min(0).max(50).default(5).volatile(),
})
```

- **`.volatile()`** makes the value writable at runtime. The Loader updates a
  volatile field **in place** on the running fiber, so a listener registered in
  `apply()` reads the current value with no re-`apply()` and no restart.
- A volatile field arrives at `apply()` as a **live reference**, not a plain
  value. Read it through `.get()`, and handle the case where a schema-less mount
  hands over a plain value instead:

```ts
function readValue(config, field, fallback) {
  const holder = config?.[field]
  if (holder === undefined || holder === null) return fallback
  const value = typeof holder.get === 'function' ? holder.get() : holder
  return value === undefined ? fallback : value
}
```

- **A Loader entry's `Config` is its settings namespace** (dsh ≥ 0.1.7). That is
  what lets a browser half read and write the same document through
  `ctx.configForms`, and what makes the namespace string equal to the row id
  everywhere — `cordis.patch.yml`, `Config`, `ctx.configForms.get(...)`.
- Ship a default that matches stock behaviour, so enabling the plugin changes
  nothing until a user changes a value. Users set values in
  `<profile>/cordis.patch.yml` or through a settings card; the user's patch layer
  survives upgrades, hand-edited JSON inside `node_modules` does not.

## Events and waterfalls

- `ctx.on(name, listener)` observes an `emit` event.
- A `waterfall` composes listeners **outermost-first**, and each listener
  receives `(payload, next)`. `{ prepend: true }` makes your listener the
  outermost one, so it rewrites the payload *before* the listeners registered
  later — including the built-in executor — read it:

```ts
ctx.on('agent/request-error', (payload, next) => {
  if (payload?.retryPolicy?.mode === 'normal') {
    payload.retryPolicy = Object.freeze({ ...payload.retryPolicy, maxRetries })
  }
  return next()
}, { prepend: true })
```

Always `return next()` unless your listener owns the decision outright, and
spread the payload you rewrite so fields you did not intend to touch survive.
Replacing the whole object where the contract passes it by reference breaks
downstream listeners.

Event names, their dispatch mode, and the payload shape are runtime facts: read
them from the owning package's README, and confirm with the live registry when
the harness is running (see `surfaces.md`).

## HTTP routes

`ctx.webServer` owns the named route table. A route handler owns its whole
response lifecycle, so it writes and ends its own response — and may hold it open
for SSE.

```ts
const route: WebRoute = {
  kind: 'exact',                                  // or 'prefix'
  path: '/api/my-plugin/hello',                   // absolute, no trailing slash
  handler: async (req, res) => { … },
}
const dispose = ctx.webServer.register(route)
```

Named routes are matched before the web app's authenticated SPA fallback, so a
route is **not** covered by the `?token=` launch token. A route that mutates
state, or that answers anything a user did not ask for, therefore carries its own
fence: a loopback check on `req.socket.remoteAddress`, a method check, and a body
size cap. Routes are exact-path and must be distinct — a collision fails
activation rather than silently winning.

## Registering a model-facing tool

`ctx.tools` is the registry the agent loop dispatches through; registering is
enough to make a tool visible, because the registry feeds its schema into the
system-prompt assembly.

```ts
import { defineTool } from '@deepseek-ai/dsh-tools'

export const inject = ['tools']

ctx.tools.register(defineTool({
  name: 'my_plugin_do',
  description: 'What it does, and when to call it instead of something else.',
  parameters: { target: { type: 'string', required: true, description: '…' } },
  output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
  execute(args) { return doTheThing(args) },
}))
```

One operation, one implementation: give the same host method to a UI action and
to the tool rather than writing the logic twice. An action that grants authority
(approving a call, loosening a policy) stays user-only.

Use the weakest extension point that suffices. In increasing order of strength:
`ctx.tools.restrict()` removes tools, `ctx.tools.guard()` denies, a waterfall
listener rewrites and depends on order, and a full replacement hook takes over
the decision — and with it the obligation to preserve every other plugin's
contribution.

## Verify the host half before installing

`pnpm typecheck` catches a wrong export shape and a missing service, but not a
wrong runtime contract. For anything load-bearing, drive the real route handler
over a real loopback socket (`test/routes.spec.ts` in the template does exactly
that), or extract the real SDK and import it (see `verification.md`).