/**
 * The panel's copy, in the two languages the shipped web client ships.
 *
 * `__PANEL_ID__` is this plugin's locale namespace: `ctx.locale.register`
 * publishes the dictionaries and `ctx.locale.bind` hands out a translate seat
 * bound to them. A locale revision re-renders every registered slot, so the
 * panel never caches a translated string.
 *
 * @module __PLUGIN_NAME__/client/locales
 */

/** English copy. */
export const en = {
  panel: '__PLUGIN_TITLE__',
  title: '__PLUGIN_TITLE__',
  description: 'A starter panel served by __PLUGIN_NAME__, with its data fetched from the host half.',
  refresh: 'Refresh',
  loading: 'Contacting the host…',
  failed: 'The host refused the request',
  pid: 'Host process',
  cwd: 'Working directory',
  time: 'Host time',
}

/** Simplified Chinese copy. Typed against `en`, so a missing key fails the build. */
export const zh: typeof en = {
  panel: '__PLUGIN_TITLE__',
  title: '__PLUGIN_TITLE__',
  description: '由 __PLUGIN_NAME__ 提供的起始面板，数据取自主机半侧。',
  refresh: '刷新',
  loading: '正在请求主机…',
  failed: '主机拒绝了该请求',
  pid: '主机进程',
  cwd: '工作目录',
  time: '主机时间',
}

/**
 * Translate one key of this panel's dictionary.
 *
 * Every child component accepts exactly this shape, so the panel can pass its
 * translate seat down without repeating the framework's generic machinery.
 */
export type PanelTranslate = (key: keyof typeof en) => string