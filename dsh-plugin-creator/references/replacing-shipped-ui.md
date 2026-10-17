# Replacing or extending shipped UI

Sometimes the right plugin changes a control the harness already ships: the
composer's model picker, a settings card, a chat row. The seat exists, an
occupant is already registered, and the goal is to change what the user sees
without breaking anything that refers to the shipped one.

Read this before writing such a plugin; `client-half.md` covers the ordinary
registration path.

## Shadow, do not replace

A slot carries its entries in a ledger, and the renderer projects them to
**shadowing winners**: for `single` the slot is one cell, for `keyed` one cell per
`key`, for `list` one cell per `id`. Within a cell the winner is the **first live
(non-abdicated) entry in priority order** — the *lowest* `priority` renders, and
`priority` sorts before `order`. `chain` slots ignore shadowing entirely: election
consumes every entry.

So the supported way to take over a shipped surface is to register the same seat
at a **lower priority** and leave the shipped entry in place:

```ts
export const SLOT = 'conversation.input.model'
export const SHADOW_PRIORITY = -1   // the shipped occupant registers at the default 0

ctx.slots.register({ name: SLOT, priority: SHADOW_PRIORITY, locale: NS, inject: … }, Seat)
```

What that buys, in the order it matters:

- **The shipped implementation stays installed.** Nothing else that refers to it
  breaks — the `/model` command, a popup, another plugin's lookup.
- **A crash falls back instead of blanking.** A render that throws *abdicates* the
  entry, and the next live entry in priority order takes the cell. With the
  shipped entry still registered, your worst case is the old behaviour.
- **The data stays shared.** Read the same service the shipped occupant reads, so
  a change made in one surface is what the other shows next.

**The priority is exclusive.** Registering a second entry for the same cell at the
same priority **throws**:

```
single slot "conversation.input.model" already has a registration at priority 0
  — register at a different priority to shadow it (lowest renders)
```

Read that message: it is the registry teaching the shadow rule. Because your
registration can therefore fail through no fault of its own, wrap it and keep the
shipped surface rather than breaking the owner's registration:

```ts
try {
  return ctx.slots.register({ … }, Seat)
} catch (error) {
  console.warn('[my-plugin] the seat could not be shadowed', error)
  return () => {}
}
```

Pick a priority another plugin is unlikely to want, keep it in one exported
constant, and document it — the constant is part of your plugin's public
footprint.

**A dynamically loaded package does not choose its own priority.** When a plugin
arrives through the dynamic client runtime (`dsh-cordis-client-runner`, the Plugin
Hub path) instead of the boot graph, the `slots` facade replaces the option: every
non-chain registration gets `env.allocatePriority()`, a per-page decreasing
counter whose first value is `-1`. Such a package therefore shadows the shipped
occupant without asking, and the number it wrote is ignored. A **static** bundle
keeps the number it wrote. Practically: state the requirement, not the number —
yours must be lower than the shipped occupant's — and read `-1` as "first dynamic
registration on this page", not as your own constant.

### Shadowing means owning it

Once your entry renders, the shipped control is no longer on screen. Everything
users relied on — the label rule, the menu, search, keyboard navigation, pending
and error states, the accessible name — is now yours. Copy the shipped control's
markup and CSS under your own class prefix (never import its primitives), and
copy its **state variables** too: a composer-row control, for example, must honour
the `--dsh-composer-*-display` variables the host sets when the row is tight,
or the shadowed seat will overflow where the shipped one did not.

Read the shipped package's source for the behaviour to preserve:
`node scripts/dsh-sdk.mjs read <shipped-package> README.md`, then its
`lib/client.js`.

## Declare what your callee needs

This is the trap that costs a day. A cordis service is a **proxy**: it rebinds
`this` to the **caller's** context for the duration of the call. A service method
that reaches a *third* service internally therefore reads **your** `inject`
declaration — not its own.

The symptom is intermittent and session-shaped. `ctx.modelDirectories.directoryFor()`
builds a directory from `this.ctx.remote.session` on a cache miss:

| Who called first for that session | Result |
|---|---|
| Another surface that declares `remote.session` | directory built and cached; your later call is a cache hit |
| Your plugin, before anything warmed it | `cannot get property "remote.session" without inject` |

Which is why a plugin that shadows a seat must declare more than it reads:

```ts
export const inject = [
  'slots',
  'locale',
  'sessions',
  'modelDirectories',
  // Not read here — needed by directoryFor()'s own cache-miss path, which runs
  // on THIS context because the service proxy rebinds `this` to the caller.
  'remote',
  'remote.session',
]
```

When a service misbehaves only for you, ask what *it* builds on a cold path, and
declare that too. Reproduce the rule in your test double so dropping a declaration
fails the suite instead of the GUI:

```ts
directoryFor(sessionId) {
  if (!declaredServices.includes('remote.session')) {
    throw new Error('cannot get property "remote.session" without inject')
  }
  …
}
```

## Guard every boundary

Values crossing a plugin boundary arrive from code you do not control. Two
distinct protections:

**Reads must not throw during render.** A store read happens inside the renderer;
a throw there retires the seat — and not just for the session that broke, because
the entry is gone for the page's life. Wrap `getSnapshot()`/`subscribe()` so a
torn-down scope degrades to an empty state.

**Values must be normalized before use.** A catalogue shape this build did not
anticipate must degrade to an empty row, not explode:

```ts
const rows = Array.isArray(state.groups) ? state.groups : []
const name = typeof group.name === 'string' && group.name !== '' ? group.name : group.id
```

One real plugin shipped version 0.2.0 that registered, rendered once, and then
threw on an unexpected catalogue shape and was retired — with nothing on screen to
say why. `asArray`, id fallbacks and name fallbacks fixed it. Treat every field of
a foreign snapshot as optional, even when the type says otherwise.

## The injection factory must never throw

A slot registration's `inject` is the only code you run outside your own component
tree. `seats` and the render machinery call it **inside the renderer**: a throw
there retires the entry before any component of yours is mounted to catch it, so
the user sees the shipped surface — or nothing — and the reason goes only to the
console.

Guard every step and return a *failure* rather than throwing:

```ts
ctx.slots.register({
  name: SLOT,
  priority: SHADOW_PRIORITY,
  locale: NS,
  // A thunk, not a snapshot: a session binding that is not ready yet is retried
  // on the next render instead of retiring the entry.
  inject: (sessionId) => ({ resolve: () => resolveSeat(models, sessions, sessionId) }),
}, Seat)
```

Returning the resolution **behind a function** rather than a plain object matters
for the same reason: caches may hold injected props per session binding, so a
re-runnable thunk lets a not-ready binding repair itself, while a snapshot taken
once stays wrong.

## Report your own failures

The registry's fallback is silent: the reason reaches the page console, which a
user without developer tools cannot read, and a silent revert is indistinguishable
from "the plugin does nothing". Render the failure in the seat itself, and make
the message the way out.

Two failure paths are worth separating:

- **A wiring failure** — the injection face could not resolve its data. Print
  `picker error: <reason> — click to use the default picker` and **stay**. Do not
  auto-hide: a reason that disappears after a few seconds is one nobody can act
  on.
- **A render crash inside your control** — catch it in your own boundary and show
  it the same way.

Clicking the message should **throw**, which is what abdicates the entry and hands
the cell back to the shipped occupant. That is the only retirement path the seat
needs.

Also leave breadcrumbs that name the plugin, so "which picker am I looking at?"
is answerable from the console:

```
[dsh-provider-model-picker] shadowed "conversation.input.model" at priority -1
[dsh-provider-model-picker] the model seat could not be shadowed …
```

## Verifying a shadow

Beyond the ordinary checks in `verification.md`, a shadowed seat needs:

1. **Registration tests through the real `apply`**, using a registry double that
   throws on a duplicate priority and a service double that enforces the inject
   rule.
2. **The built bundle spec** — a broken loader banner fails the live page and
   nothing else catches it.
3. **Both faces**: the label and menu markup via `react-dom/server`, the
   interaction path (open, drill, choose, escape) in jsdom.
4. **Live inspection of the slot ledger.** The raw registry view is the
   inspection surface: `conversation.input.model` should hold **two** occupants —
   yours `active: true` at the lower priority and the shipped entry `active: false`
   as the fallback. That is what distinguishes "the registration landed" from "the
   registration was attempted".

   Read the three states precisely, because they are three different bugs:

   | Ledger | Meaning |
   |---|---|
   | One occupant, the shipped one, `active: true` | Your registration never ran (bundle not in the page's graph, `apply` threw, or the inject declarations never resolved) |
   | **Two** occupants, yours `active: false` | You registered and then **threw** — abdication is one-shot, so the entry stays in the ledger, retired, while the shipped entry renders |
   | Two occupants, yours `active: true` | The shadow is live |

   The middle row is the one worth memorising: "it showed for a moment, then the
   shipped control came back" *is* that state. The reason went to the page console
   (`slot entry crashed in '<slot>'`) — and the page console is **not reachable
   from the host**: the desktop app writes no renderer log, and renderer messages do
   not reach the system log. Either ask the user for the console line or the
   rendered message, or make the plugin render its own failures as described above.
   Do not plan on reading it yourself.

## Operational notes

- **The plugin is not self-contained.** A seat that reads a shipped service needs
  that package enabled; declare it in `dsh.client.inject`. With the owning bundle
  disabled there is no data to render.
- **A shadowed seat is a moving target.** The host control's markup and CSS change
  with the platform; yours does not. Budget for tracking it, and prefer copying
  tokens and behaviour over copying exact pixel values.
- **Say so in the README** when a plugin relies on an internal shape of another
  package: record which version it was read against, and what happens when it
  drifts.