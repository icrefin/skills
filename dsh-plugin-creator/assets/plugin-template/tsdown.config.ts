import type { UserConfig } from 'tsdown'

/**
 * Browser-half bundler: emits `lib/client.js` in the module loader's factory
 * form. The `id` in the banner MUST equal the package name — it is the boot
 * graph row id, and a mismatch makes the module system reject the bundle with
 * "loaded without registering <id>".
 *
 * React is the only thing left unbundled: `react` and `react/jsx-runtime` are
 * platform seeds in the browser module table. Everything else the client imports
 * is bundled in, which is why the client needs no dependencies at install time.
 *
 * This is expressed as `deps.neverBundle`, not the top-level `external` that
 * tsdown deprecated. The two mean the same thing here — mark these imports
 * external rather than resolve them — but `external` prints a deprecation
 * warning on every build with tsdown 0.22.x.
 */
export default {
  entry: { client: 'src/client/index.tsx' },
  outDir: 'lib',
  format: ['cjs'],
  platform: 'browser',
  target: 'es2022',
  dts: false,
  sourcemap: true,
  clean: false,
  deps: { neverBundle: ['react', 'react/jsx-runtime'] },
  outputOptions: {
    entryFileNames: 'client.js',
    banner: 'window.__ModuleLoader__.load({ id: "__PLUGIN_NAME__", factory: (require) => {',
    footer: 'return module.exports; } });',
    intro: 'var module = { exports: {} }; var exports = module.exports;',
  },
} satisfies UserConfig