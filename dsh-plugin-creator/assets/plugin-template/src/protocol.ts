/**
 * Wire contract shared by both halves.
 *
 * Both halves import this module, so a route path or payload field can never
 * drift between the host that serves it and the browser that reads it. Keep it
 * dependency-free: the client bundle inlines it.
 *
 * @module __PLUGIN_NAME__/protocol
 */

/** Route paths served by the host half under the web server's route table. */
export const API = {
  /** Liveness probe and identity of the running host process. */
  hello: '/api/__PLUGIN_ID__/hello',
} as const

/** Body of a successful `GET API.hello`. */
export interface HelloPayload {
  /** Loader row id, so the panel can prove which plugin answered. */
  id: string
  /** Human-readable greeting. */
  message: string
  /** Host process id. */
  pid: number
  /** Host process working directory. */
  cwd: string
  /** Host clock, ISO 8601. */
  time: string
}

/** Body of any failed request. */
export interface ErrorPayload {
  error: string
}