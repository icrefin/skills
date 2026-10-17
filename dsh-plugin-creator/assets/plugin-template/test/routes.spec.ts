/**
 * The host half's route family, served from a real loopback HTTP server and
 * driven with `fetch`. Nothing about the handlers is stubbed: the fences, the
 * status codes and the payload shape are the shipped code's own.
 *
 * @module __PLUGIN_NAME__/test/routes
 */

import { createServer, type Server } from 'node:http'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import { API, type HelloPayload } from '../src/protocol.ts'
import { makeRoutes } from '../src/routes.ts'

/** Minimal host context: the route family only reads `logger`. */
const ctx = {
  logger: { debug() {}, info() {}, warn() {}, error() {} },
} as unknown as Context

const routes = makeRoutes(ctx)

let server: Server
let origin: string

beforeAll(async () => {
  server = createServer((req, res) => {
    const path = new URL(req.url ?? '/', 'http://localhost').pathname
    const route = routes.find((candidate) => candidate.path === path)
    if (route === undefined) {
      res.writeHead(404)
      res.end()
      return
    }
    void route.handler(req, res)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('the test server bound no TCP port')
  origin = `http://127.0.0.1:${address.port}`
})

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()))
})

describe('GET API.hello', () => {
  it('answers the identity of the host process', async () => {
    const response = await fetch(`${origin}${API.hello}`)
    expect(response.status).toBe(200)
    expect(response.headers.get('cache-control')).toBe('no-store')
    const payload = (await response.json()) as HelloPayload
    expect(payload.id).toBe('__PLUGIN_ID__')
    expect(payload.pid).toBe(process.pid)
    expect(payload.cwd).toBe(process.cwd())
    expect(Number.isNaN(Date.parse(payload.time))).toBe(false)
  })

  it('rejects a method the route does not own', async () => {
    const response = await fetch(`${origin}${API.hello}`, { method: 'POST' })
    expect(response.status).toBe(405)
    expect((await response.json()) as { error: string }).toMatchObject({ error: expect.stringContaining('method not allowed') })
  })
})