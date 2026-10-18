# Where to plug in

Choosing the surface is a design decision, and it is the one that cannot be fixed
later: a page served as HTML in an iframe never receives the harness theme or
locale, and a feature implemented in the wrong layer duplicates machinery the
harness already runs. Decide the surface before writing the view.

**Contents**

- [The four shapes a plugin can take](#the-four-shapes-a-plugin-can-take)
- [Finding the extension point](#finding-the-extension-point)
- [Documented UI seats (dsh 0.2.1-rc.2)](#documented-ui-seats-dsh-021-rc2)
- [Host extension points](#host-extension-points)
- [Verification limits](#verification-limits)

## The four shapes a plugin can take

| Shape | Manifest | Typical request |
|---|---|---|
| **Host only** | `dsh.bundle.patch`, no `dsh.client` | a model-facing tool, a session projection, a background policy, a CLI/HTTP capability |
| **Host + browser (dual face)** | both | a GUI panel that reads and writes host state — the common case |
| **Browser only** | `dsh.client` with a host half that does nothing | a decoration, a new seat, or **a control the harness already ships** — see [`replacing-shipped-ui.md`](replacing-shipped-ui.md) |
| **Fork of a shipped/third-party plugin** | `pnpm patch` files + a rebuilt package | changing a plugin you do not own — see `packaging.md` |

The third row hides a real distinction. **Adding** to a seat and **replacing** an
occupant are different problems: adding is a registration, replacing is a
registration at a lower `priority` plus the obligation to reimplement everything
the shipped occupant did. Decide which one the request actually is before
scaffolding.

A dual-face plugin is one package, one row, two entry points: `exports["."]` runs
in the host process, `exports["./client"]` in the page. They talk over
`ctx.webServer` routes, or over the remote/settings transport when the data is
already a harness concept.

## Finding the extension point

The installed packages are the authority, and `scripts/dsh-sdk.mjs` reads them out
of the archive the shell tools cannot open.

```sh
S=scripts/dsh-sdk.mjs

node $S version                                   # archive path, dsh version, package count
node $S list dsh-tool                             # candidate packages by name
node $S read dsh-host-webserver README.md         # the contract document for one package
node $S find 'ctx\.tools\.register'               # who registers what, and how
node $S slots                                     # every documented UI seat
node $S extract dsh-host-webserver /tmp/sdk       # materialise it to read or import
```

The generated package inventory — every plugin package, its group, whether its
row takes a `config`, and one line on what it provides — ships inside the
`cordis-composition-reference` skill:

```sh
node scripts/dsh-sdk.mjs read dsh-agent-preset skills/cordis-composition-reference/references/packages.md
```

Search it rather than reading it whole, and prefer it over guessing a service
name.

Two rules for reading a package:

- **`README.md` is the contract.** Shipped packages carry no `.d.ts`; the README
  documents the Context augmentation (which services exist), the Events with
  their dispatch mode (`emit` vs `waterfall`), and the Config fields.
- **`lib/index.js` is the implementation of record**, with its JSDoc intact.
  Read it when the README leaves a question open, and read the package that
  *consumes* a seam to see the intended call site.

For editor-level types, add the npm-published `@deepseek-ai/*` packages as
devDependencies, pinned to the runtime version (`node scripts/dsh-sdk.mjs version`).
They carry the full `declare module '@deepseek-ai/cordis'` augmentation, so
`ctx.webServer`, the event map and the slot map are all checked at compile time.
This is also what makes `tsc` catch a bad slot registration instead of the
browser console doing it.

## Documented UI seats (dsh 0.2.1-rc.2)

Reconciled against the live ledger in 0.2.1-rc.2: `node scripts/dsh-sdk.mjs slots`
reports 76 documented seat ids, and every id below is one of them unless its note
says otherwise. The catalogue is not exhaustive in the other direction either —
some seats are declared only in code and no README mentions them (`root` is one),
so `slots` never lists them. Confirm a seat with the owner's README and
`node scripts/dsh-sdk.mjs find '<pattern>'` before concluding it does not exist. A
seat marked *occupied* already has an owner; register into the seats **inside**
it rather than replacing it, unless replacing is the goal.

### Shell

| Seat | Kind | Notes |
|---|---|---|
| `shell.leading` | single | frame top-left window-chrome seat; occupied by the sidebar's controls on macOS |
| `shell.overlay` | — | viewport overlay layer for dialogs and transient surfaces |
| `shell.bottom` | — | frame bottom seat, added in 0.2.1-rc.2 |
| `root` | single | the renderer's one root occupant, owning product layout. Do not register here. **Code-only**: declared in `dsh-client-ui-layout` but in no README, so `slots` never lists it |

### Left column

| Seat | Kind | Notes |
|---|---|---|
| `sidebar` | single | *occupied* — the whole column; replacing it removes every seat it declares |
| `sidebar.panellist` | list | **global panel rows.** An entry's `id` addresses the same key in `main` |
| `sidebar.brand.mark`, `sidebar.brand.name` | single | brand mark and wordmark |
| `sidebar.toggle.badge` | single | non-interactive badge on the collapsed expand button |
| `sidebar.workspaces` | — | *occupied* — the workspace/session browser |
| `sidebar.workspaces.directoryFlow` | single | the directory-flow child hole the picker composition fills |
| `sidebar.workspaces.session.menu.item`, `sidebar.workspaces.session.row.action` | list | per-session-row menu entries and hover buttons. The browser's own Pin / Rename / Fork / Archive / Copy-ID actions are themselves entries, so an added action lands wherever its `order` puts it |
| `sidebar.chat.conversation` | — | a session rendered as a sidebar chat, declared by the subagent surface |
| `sidebar.settings` | — | *occupied* — the bottom-pinned Settings trigger |
| `sidebar.session.row.leading`, `sidebar.session.row.hover` | — | per-session-row seats |
| `sidebar.footer.action` | — | footer action row |

### Centre column and conversation

| Seat | Kind | Notes |
|---|---|---|
| `main` | keyed | **global pages.** `conversation` is reserved for the Conversation; the live ledger spells that entry `main.conversation` |
| `conversation.header`, `conversation.content`, `conversation.view` | — | *occupied* — the Conversation shell |
| `conversation.composer` / `conversation.composer.dock` | — | below and inside the composer; `dock` is the safest decoration seat |
| `conversation.chat.node` | keyed | **Chat rows**, dispatched by the event definition's `kind` |
| `conversation.chat.turnTail` | — | after the last row of a turn |
| `conversation.input.model` | single | **occupied** by the shipped model picker at priority `0`, so a plugin changes it by shadowing — see [`replacing-shipped-ui.md`](replacing-shipped-ui.md) |
| `conversation.input.model.label` | — | the model trigger's label child, added in 0.2.1-rc.2 |
| `conversation.input.activity`, `conversation.input.dock`, `conversation.input.overlay`, `conversation.input.permission`, `conversation.input.plan` | — | the remaining input-area seats. Register with the full id: the `.name` form is shorthand **in this table only**. There is no `conversation.input.attachments` seat in 0.2.1-rc.2 |
| `conversation.session`, `conversation.session.header.corner`, `conversation.session.header.utilities` | — | session-scoped header seats; `.utilities` is a **sibling** of `.corner`, not a child of it |
| `conversation.chat.message.images`, `conversation.chat.user.images`, `conversation.images.content`, `conversation.trajectory.images` | — | the four image renderers. `conversation.message.images` existed before 0.2.1-rc.2 and is gone — registering it fails |
| `conversation.chat.flow`, `conversation.chat.message.images`, `conversation.chat.reasoning.body`, `conversation.chat.reasoning.content`, `conversation.chat.user.content`, `conversation.chat.user.images` | — | per-row Chat renderers, added in 0.2.1-rc.2 |
| `conversation.user.text`, `conversation.user.text.node` | — | the user-text pipeline: a whole user turn, and one node of its document |
| `conversation.hero.brand.mark`, `conversation.hero.workspace.directoryFlow` | — | the empty-state hero |

### Settings

| Seat | Kind | Notes |
|---|---|---|
| `settings.shell`, `settings.launcher`, `settings.onboarding`, `settings.describe`, `settings.describe.writable` | — | *occupied* — the settings domain |
| `settings.section` | — | a settings section entry |
| `settings.general.item` | — | a row on the General page |
| `settings.models.footer` | — | the Models page's page-wide extension area |
| `settings.plugins.tab` | — | a tab on the Plugins page |
| `settings.agentLoop` | — | agent-loop settings |
| `settings.mutate`, `settings.replace`, `settings.update` | keyed | the settings service's three write operations, exposed as seats by the API controller. Each returns the namespace's new redacted view; a stale write reports `settings-conflict` |
| `settings.yaml`, `settings.yaml.imported` | keyed | the YAML settings pipeline, and the hook that runs after an import |

These settings seats are **data** seats, not UI: they carry a namespace's value
through the settings service rather than rendering a card. The rendering seats are
the `settings.section` / `settings.general.item` / `settings.models.footer` rows
above.

### Right column

| Seat | Kind | Notes |
|---|---|---|
| `rightbar` | — | *occupied* — the right column |
| `rightbar.session` | — | one Session-bound subtree. Each View owns its Session reference; only the foreground subtree reports a frame track, and the others stay hidden without deleting tab state |
| `sidebar.right.pane.tab` | keyed | a right-panel tab **body**, keyed by the tab definition's `id`; the body reads `{ sidebar, panel, tab }` through the framework's `useTabInfo()` |
| `sidebar.right.pane.tab.title` | keyed | that tab's title. Omitted, the text captured at open time is used |
| `sidebar.right.tab.document`, `sidebar.right.tab.document.action`, `sidebar.right.tab.document.actions`, `sidebar.right.tab.document.unpreviewable` | — | the document-preview tab's body, its single action, its action row, and its unpreviewable state |
| `sidebar.right.tab.files.actions` | — | the files tab's action row |
| `sidebar.right.tab.guide` | chain | replaces the guide tab's **body** without replacing the tab |
| `sidebar.right.tab.guide.entry` | keyed | one guide entry, by its active definition id |
| `sidebar.right.tab.menu.item` | list | content-level actions appended to a tab's menu, after the kit's own layout actions |

### Workspace surfaces

| Seat | Kind | Notes |
|---|---|---|
| `workspace.create` | — | the **Add workspace…** action. It renders only while its directory-flow hole is occupied, so an empty hole means the composition has no picking affordance |
| `workspace.files` | — | the workspace file surface |
| `workspace.toast` | keyed | the notice overlay, dispatched by notice kind. Keyed registrations inject localized display mappings and their own actions; only archive notices subscribe to the viewing filter |
| `workspace.toast.content` | — | the shared Toast body every presentation reuses |

## Host extension points

Ordered weakest to strongest. Use the weakest one that solves the problem: every
step up means preserving more of other plugins' contributions yourself.

| Want | Use |
|---|---|
| Change what a shipped seat renders | register that seat at a **lower `priority`** — [`replacing-shipped-ui.md`](replacing-shipped-ui.md) |
| Remove a tool from one agent | `ctx.tools.restrict()` on that agent's context |
| Deny a tool call regardless of order | `ctx.tools.guard()` |
| Rewrite a decision before it is made | a waterfall listener with `{ prepend: true }` |
| Replace a whole assembly | the owning seam's replacement hook — last resort |
| Add a capability the model can call | `ctx.tools.register(defineTool({ … }))` |
| Add prompt text | `ctx.systemPrompt.section()` |
| Add per-agent context | `agent.inject()`, registered on `agent.ctx` from an `agent/created` listener |
| Serve the browser half | `ctx.webServer.register({ kind, path, handler })` |
| Persist plugin state | a storage service, found with `list` + `read` — never a new session event type |
| Derive per-session state from the log | a `ctx.sessionProjections` unit, not a `session/event` subscription |

Registrations made on another context — an agent's, a session's — have two owners:
wrap them in your plugin's own effect **and** keep the disposer keyed by that
agent, so either teardown removes them.

## Verification limits

Prefer the already-connected page for anything visual. Do not launch a separate
browser, change `HOME`, or inspect personal browser profiles to obtain a
screenshot. When no browser control is available, limit verification to
JavaScript syntax, manifest validation, the built bundle, and the live
registration, and say plainly that visual verification remains unavailable. A
screenshot of a mock page is not verification of a running plugin.