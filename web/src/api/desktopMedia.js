/**
 * desktopMedia.js — кэш картинок программы: сколько занято и очистка (17.10.2026).
 *
 * Ручки `/desk/media/*` живут ТОЛЬКО в локальном сервере программы
 * (`desktop/local_api.py::install_media_cache`); на сайте их нет, и блок настроек там
 * не показывается вовсе. Тот же приём и тот же токен, что у состояния синка
 * (`api/desktopSync.js`): своё чтение localStorage разъехалось бы с общим правилом.
 */
import { getAccess } from './tokens.js'

async function call(path, method = 'GET') {
  const token = getAccess()
  const r = await fetch(path, { method, headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

/** { bytes, files, by_kind: {gif, avatar}, max_bytes, ttl_days: {gif, avatar} } */
export const mediaCacheStats = () => call('/desk/media/stats')
export const clearMediaCache = () => call('/desk/media/clear', 'POST')

/** «12,4 МБ» — размер для человека. */
export function formatMegabytes(bytes) {
  const mb = (Number(bytes) || 0) / (1024 * 1024)
  return (mb < 10 ? mb.toFixed(1) : String(Math.round(mb))).replace('.', ',')
}
