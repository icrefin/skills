/**
 * The `/api/__PLUGIN_ID__` route family.
 *
 * Every route carries a loopback-only fence: a LAN-exposed `dsh web`
 * deployment must not serve plugin APIs to other machines. Handlers own the
 * full response lifecycle, so each one writes and ends its own response.
 *
 * @module __PLUGIN_NAME__/routes
 */

import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Context } from '@deepseek-ai/cordis'
import type { WebRoute } from '@deepseek-ai/dsh-host-webserver'
import { API, type ErrorPayload, type HelloPayload } from './protocol.ts'

/** Loader row id; mirrors `cordis.patch.yml`. */
const PLUGIN_ID = '__PLUGIN_ID__'

/** Write one JSON response body. */
function writeJson(res: ServerResponse, status: number, body: unknown): void {
  const text = JSON.stringify(body)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text),
    'cache-control': 'no-store',
  })
  res.end(text)
}

/** Write one JSON error body. */
function writeError(res: ServerResponse, status: number, message: string): void {
  const body: ErrorPayload = { error: message }
  writeJson(res, status, body)
}

/** Whether the request arrived over the loopback interface. */
function isLoopbackRequest(req: IncomingMessage): boolean {
  const address = req.socket.remoteAddress
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1'
}

/**
 * Build every route of the `/api/__PLUGIN_ID__` family.
 * @param ctx - host plugin context, used for logging.
 * @returns the exact-path routes to register on `ctx.webServer`.
 */
export function makeRoutes(ctx: Context): WebRoute[] {
  return [
    {
      kind: 'exact',
      path: API.hello,
      handler: async (req, res) => {
        if (!isLoopbackRequest(req)) {
          writeError(res, 403, 'forbidden: loopback-only')
          return
        }
        if (req.method !== 'GET') {
          writeError(res, 405, `method not allowed: ${req.method ?? ''}`)
          return
        }
        ctx.logger.debug('[__PLUGIN_NAME__] %s %s', req.method, API.hello)
        const payload: HelloPayload = {
          id: PLUGIN_ID,
          message: '__PLUGIN_TITLE__ is running',
          pid: process.pid,
          cwd: process.cwd(),
          time: new Date().toISOString(),
        }
        writeJson(res, 200, payload)
      },
    },
  ]
}