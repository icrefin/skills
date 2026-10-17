# __PLUGIN_NAME__

A [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (dsh)
plugin. _One paragraph: what it adds, and where in the GUI it shows up._

```
Settings/Sidebar ▸ __PLUGIN_TITLE__
└── the surface this plugin occupies
```

## What it contributes

| Surface | What it does |
|---|---|
| Host route `GET /api/__PLUGIN_ID__/hello` | liveness and identity of the host process |
| Sidebar row **__PLUGIN_TITLE__** | a global panel row in the icon rail |
| The **__PLUGIN_TITLE__** page | fetches the host route and renders the result |

## Install

```sh
pnpm install
pnpm check                              # typecheck both halves, build, then vitest
pnpm run pack                           # -> dist/__PLUGIN_NAME__-0.1.0.tgz
scripts/install.sh                      # build, pack, and print the install path
```

The desktop profile is owned by the Electron application, so `dsh plugin add`
refuses it: install the packed tarball from **Settings → Plugins**. A bundle
added to a running profile needs a **restart** before its entry can be imported;
the browser half additionally needs the page reloaded.

## Develop

```sh
pnpm check                              # typecheck both halves, then vitest
scripts/install.sh                      # pack to dist/ and print the install path
scripts/dev-profile.sh boot             # boot in an isolated profile on :19499
scripts/dev-profile.sh dump             # print the composed profile tree
scripts/dev-profile.sh remove
```

`check` builds before it tests on purpose: `test/bundle.spec.ts` executes the
built `lib/client.js` behind a fake `window.__ModuleLoader__`, which is the only
check that catches a loader banner bound to the wrong id. It skips with a visible
note when the artifact is absent.

## Layout

| Path | Role |
|---|---|
| `src/index.ts` | host half: the `webServer` route registration |
| `src/routes.ts` | the `/api/__PLUGIN_ID__` route family and its fences |
| `src/protocol.ts` | the wire contract both halves import |
| `src/client/index.tsx` | browser half: locale dictionaries and the two slot registrations |
| `src/client/Panel.tsx` | the page |
| `cordis.patch.yml` | the bundle patch that inserts the entry into a profile's roster |

## License

MIT