/**
 * The panel stylesheet.
 *
 * Two rules make plugin UI look like the Harness rather than beside it:
 *
 *  - every color is a `--dsw-alias-*` theme token, never a literal, so light
 *    and dark both work and a renamed token degrades instead of breaking;
 *  - the tag is created from the bundle's own factory body, so the client
 *    module system claims it and removes it when the plugin is disabled.
 *
 * Class names carry the plugin id so two plugins can never collide.
 *
 * @module __PLUGIN_NAME__/client/styles
 */

/** Id of the stylesheet tag, so injection stays idempotent. */
export const STYLE_ID = '__PLUGIN_NAME__-style'

/** Theme-token-only stylesheet for the panel. */
export const PANEL_CSS = `
.__PLUGIN_ID__-page{display:flex;flex-direction:column;gap:16px;padding:24px;height:100%;overflow:auto;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
.__PLUGIN_ID__-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.__PLUGIN_ID__-title{font-size:16px;font-weight:600;line-height:1.4}
.__PLUGIN_ID__-description{color:var(--dsw-alias-label-secondary);font-size:12px;line-height:1.6;max-width:56ch}
.__PLUGIN_ID__-button{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font-size:13px;padding:6px 12px;cursor:pointer}
.__PLUGIN_ID__-button:hover{background:var(--dsw-alias-bg-layer-2)}
.__PLUGIN_ID__-button:disabled{opacity:.5;cursor:default}
.__PLUGIN_ID__-card{border:1px solid var(--dsw-alias-border-l1);border-radius:10px;background:var(--dsw-alias-bg-layer-1);padding:16px;display:grid;grid-template-columns:max-content 1fr;gap:10px 20px;font-size:13px}
.__PLUGIN_ID__-key{color:var(--dsw-alias-label-secondary)}
.__PLUGIN_ID__-value{color:var(--dsw-alias-label-primary);font-family:var(--dsw-font-family-mono,ui-monospace,monospace);word-break:break-all}
.__PLUGIN_ID__-error{color:var(--dsw-alias-state-error-primary);font-size:13px}
`

/** Append the stylesheet once per document. */
export function injectStyles(): void {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ID) !== null) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = PANEL_CSS
  document.head.append(style)
}