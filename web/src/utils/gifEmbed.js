/**
 * gifEmbed.js — распознавание голых ссылок на CDN Klipy в ТЕКСТЕ сообщения мессенджера
 * (та же идея, что у videoEmbed.js: клиент ничего не проверяет по сети, просто узнаёт
 * СВОЙ белый список хостов по regex и рисует картинку под текстом).
 *
 * Нужен ОТДЕЛЬНО от Message.kind='gif' (см. ChatThread.vue): тот путь — GIF, отправленный
 * через пикер, тело сообщения — сама ссылка и ничего больше. Этот путь — человек ВСТАВИЛ
 * такую же ссылку (например, скопировал «адрес картинки» уже отправленной гифки) ВНУТРЬ
 * обычного текстового сообщения — раньше она просто лежала мёртвым текстом.
 *
 * Хост совпадает с серверным gif_service.ALLOWED_CDN_HOST — здесь НЕ проверяем расширение
 * файла: Klipy отдаёт прямые ссылки без «.gif» на конце (id-путь), а хост уже достаточно
 * узкий белый список (SSRF/подмена закрыты тем же приёмом, что у видео-эмбедов).
 */
const KLIPY_CDN_HOST = 'static.klipy.com'

/** @returns {{sourceUrl:string}|null} */
export function detectGifLink(url) {
  const clean = String(url ?? '').trim()
  if (!/^https?:\/\//i.test(clean)) return null
  try {
    if (new URL(clean).hostname !== KLIPY_CDN_HOST) return null
  } catch {
    return null
  }
  return { sourceUrl: clean }
}

/** Ссылки из СЫРОГО текста сообщения → распознанные GIF (без дублей по url). */
export function extractGifLinks(text) {
  const urls = String(text ?? '').match(/https?:\/\/[^\s<>]+/g) || []
  const seen = new Set()
  const out = []
  for (const raw of urls) {
    const clean = raw.replace(/[.,!?;:)\]}]+$/, '')
    if (seen.has(clean)) continue
    const g = detectGifLink(clean)
    if (g) { seen.add(clean); out.push(g) }
  }
  return out
}
