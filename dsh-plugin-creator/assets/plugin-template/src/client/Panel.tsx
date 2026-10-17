/**
 * The page opened by the sidebar row: fetch `/api/__PLUGIN_ID__/hello` from the
 * host half and render what came back.
 *
 * The component receives its translate seat through props; it never imports the
 * locale service. Session and workspace data, when a panel needs it, arrives the
 * same way — through selector hooks the framework binds at the render position.
 *
 * @module __PLUGIN_NAME__/client/Panel
 */

import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { API, type HelloPayload } from '../protocol.ts'
import type { PanelTranslate } from './locales.ts'

/** Props composed by the slot framework for this key of the `main` slot. */
export interface PanelProps {
  t: PanelTranslate
}

/** Human-readable form of an unknown thrown value. */
function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * Read the host half's hello payload.
 * @returns the parsed payload.
 * @throws when the response is not ok or not JSON.
 */
async function fetchHello(): Promise<HelloPayload> {
  const response = await fetch(API.hello, { headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return (await response.json()) as HelloPayload
}

/**
 * Render the panel.
 * @param props - the framework-injected translate seat.
 * @returns the panel element tree.
 */
export function Panel({ t }: PanelProps): ReactElement {
  const [payload, setPayload] = useState<HelloPayload | undefined>(undefined)
  const [error, setError] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(undefined)
    try {
      setPayload(await fetchHello())
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="__PLUGIN_ID__-page">
      <div className="__PLUGIN_ID__-head">
        <div>
          <div className="__PLUGIN_ID__-title">{t('title')}</div>
          <div className="__PLUGIN_ID__-description">{t('description')}</div>
        </div>
        <button type="button" className="__PLUGIN_ID__-button" onClick={() => void load()} disabled={loading}>
          {loading ? t('loading') : t('refresh')}
        </button>
      </div>
      {error === undefined ? null : (
        <div className="__PLUGIN_ID__-error">
          {t('failed')}: {error}
        </div>
      )}
      {payload === undefined ? null : (
        <div className="__PLUGIN_ID__-card">
          <div className="__PLUGIN_ID__-key">{t('pid')}</div>
          <div className="__PLUGIN_ID__-value">{String(payload.pid)}</div>
          <div className="__PLUGIN_ID__-key">{t('cwd')}</div>
          <div className="__PLUGIN_ID__-value">{payload.cwd}</div>
          <div className="__PLUGIN_ID__-key">{t('time')}</div>
          <div className="__PLUGIN_ID__-value">{payload.time}</div>
        </div>
      )}
    </div>
  )
}