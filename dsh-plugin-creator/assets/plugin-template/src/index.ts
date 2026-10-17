/**
 * __PLUGIN_NAME__ — host half.
 *
 * Mounts the `/api/__PLUGIN_ID__` route family. The browser half (`./client`)
 * is the sidebar panel that drives it.
 *
 * Every registration lives inside `ctx.effect`, whose callback returns the
 * disposer; cordis runs it when the plugin unloads, when the profile patch
 * disables the row, or when the host tears down. A bare `register()` outside an
 * effect leaks that registration past unload.
 *
 * @module __PLUGIN_NAME__
 */

import type { Context } from '@deepseek-ai/cordis'
// Type-only import for the declaration merging that puts `webServer` on Context.
import type {} from '@deepseek-ai/dsh-host-webserver'
import { makeRoutes } from './routes.ts'

/** Loader row id; mirrors `cordis.patch.yml`. */
export const name = '__PLUGIN_ID__'

/** Services required before this plugin may mount. */
export const inject = ['webServer']

/**
 * Mount the routes and drop them again on teardown.
 * @param ctx - host plugin context.
 */
export function apply(ctx: Context): void {
  ctx.effect(() => {
    const disposers = makeRoutes(ctx).map((route) => ctx.webServer.register(route))
    ctx.logger.info('[__PLUGIN_NAME__] /api/__PLUGIN_ID__ routes mounted')
    return () => {
      for (const dispose of disposers) dispose()
    }
  }, '__PLUGIN_NAME__: routes')
}