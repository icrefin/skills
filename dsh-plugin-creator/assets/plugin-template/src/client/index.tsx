/**
 * __PLUGIN_NAME__ — browser half.
 *
 * Contributes one row to the sidebar's global panel list (`sidebar.panellist`)
 * and the page it opens in the centre column (`main`), both keyed by
 * `__PANEL_ID__`. Selecting the row is a layout lookup in the live `main`
 * registry, so the two registrations must share the id by construction.
 *
 * `dsh.client.inject` in package.json orders this bundle after the two packages
 * that declare those slots, so both `slots.inject` calls resolve instead of
 * racing the declaration.
 *
 * This module is bundled into the loader's factory form; its top-level side
 * effects run at materialization, which is when the client module system claims
 * styles and installs the plugin.
 *
 * @module __PLUGIN_NAME__/client
 */

import type { ReactElement } from 'react'
import type { SlotCore, TranslateNS } from '@deepseek-ai/dsh-client-ui-slots'
// Type-only imports for their declaration merging: these are the packages that
// declare `main` and `sidebar.panellist` in SlotMap.
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { Panel } from './Panel.tsx'
import { en, zh, type PanelTranslate } from './locales.ts'
// The ids and the injection list live in a plain `.ts` module so a test can
// import them without pulling JSX into the host tsconfig.
import { NS, PANEL_ID, inject } from './plugin.ts'
import { injectStyles } from './styles.ts'

export { NS, PANEL_ID, inject }

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** Keys of this plugin's own dictionary. */
    __PANEL_ID__: keyof typeof en
  }
}

/** Structural face of the client locale service. */
interface LocaleService {
  register(namespace: '__PANEL_ID__', dictionaries: { en: typeof en; zh: typeof zh }): () => void
  bind(namespace: '__PANEL_ID__'): TranslateNS<'__PANEL_ID__'>
}

/** Structural face of the client slot service. */
interface SlotsService {
  readonly register: SlotCore['register']
  /**
   * Run `callback` once the named slot is declared; the returned disposer is
   * the registration's own disposer, so the effect teardown removes it.
   */
  inject(key: string, callback: () => () => void): () => void
}

/** Structural face of the client root context this plugin uses. */
interface ClientContext {
  effect(callback: () => (() => void) | void, label?: string): void
  slots: SlotsService
  locale: LocaleService
}

/** Geometry the sidebar hands its panel rows. */
interface PanelIconProps {
  /** Requested square edge in pixels (16 expanded, 18 in the rail). */
  size: number
  /** Whether this panel is the selected main panel. */
  active: boolean
}

/**
 * The global-panel row glyph, drawn in `currentColor` so the sidebar's own
 * active and idle colors apply.
 * @param props - requested size and selection state.
 * @returns the inline SVG glyph.
 */
function PanelIcon({ size, active }: PanelIconProps): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 1.5 : 1.3}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2.25" y="3.25" width="11.5" height="9.5" rx="1.5" />
      <path d="M2.25 6.25h11.5" />
      <path d="M5.25 9.25h3.5" />
    </svg>
  )
}

/**
 * Register the sidebar row and the page it opens.
 *
 * An external plugin must never take the web shell down with it, so mounting
 * failures are logged rather than thrown: the shell fails the whole boot when a
 * plugin's `apply` throws.
 *
 * @param ctx - client root context carrying the slot and locale services.
 */
export function apply(ctx: ClientContext): void {
  try {
    ctx.effect(() => ctx.locale.register(NS, { en, zh }), '__PLUGIN_NAME__: dictionaries')
    const t: PanelTranslate = ctx.locale.bind(NS)

    ctx.effect(
      () =>
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            {
              name: 'sidebar.panellist',
              id: PANEL_ID,
              order: 50,
              label: () => t('panel'),
            },
            PanelIcon,
          ),
        ),
      '__PLUGIN_NAME__: sidebar entry',
    )

    ctx.effect(
      () =>
        ctx.slots.inject('main', () =>
          ctx.slots.register({ name: 'main', key: PANEL_ID, locale: NS }, Panel),
        ),
      '__PLUGIN_NAME__: main panel',
    )
  } catch (error) {
    console.warn('[__PLUGIN_NAME__] the panel could not mount', error)
  }
}

// Materialization runs this: the client module system claims a style tag created
// from the bundle's factory body and removes it again when the plugin unloads.
injectStyles()