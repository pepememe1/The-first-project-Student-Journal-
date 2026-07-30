/**
 * videoEmbed.js — извлечение видео-эмбеда из ссылки мессенджера (Фаза 1,
 * docs/MESSENGER-ATTACHMENTS-PLAN.md §2/§6/§9).
 *
 * БЕЛЫЙ СПИСОК хостов (YouTube/VK Video/Rutube) — id ролика достаётся regex'ом из самой
 * ссылки, сервер НИКУДА не ходит за превью. Это закрывает SSRF архитектурно: серверу
 * незачем разбирать произвольный URL, а нераспознанные ссылки остаются обычным
 * кликабельным текстом (см. markdownLite.js) без всякого встраивания.
 */

const PATTERNS = [
  {
    provider: 'youtube',
    re: /(?:youtube\.com\/watch\?(?:[^\s#]*&)?v=|youtube\.com\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{6,})/,
    embed: (id) => `https://www.youtube.com/embed/${id}`,
  },
  {
    provider: 'vk',
    re: /vk\.com\/video(-?\d+_\d+)/,
    embed: (id) => {
      const [oid, vid] = id.split('_')
      return `https://vk.com/video_ext.php?oid=${oid}&id=${vid}&hd=2`
    },
  },
  {
    provider: 'rutube',
    re: /rutube\.ru\/video\/([a-zA-Z0-9]+)/,
    embed: (id) => `https://rutube.ru/play/embed/${id}`,
  },
]

/** @returns {{provider:string,id:string,embedUrl:string,sourceUrl:string}|null} */
export function detectVideo(url) {
  const clean = String(url ?? '').trim()
  if (!/^https?:\/\//i.test(clean)) return null
  for (const p of PATTERNS) {
    const m = p.re.exec(clean)
    if (m) return { provider: p.provider, id: m[1], embedUrl: p.embed(m[1]), sourceUrl: clean }
  }
  return null
}

/** Ссылки из СЫРОГО текста сообщения → распознанные видео (без дублей по url). */
export function extractVideos(text) {
  const urls = String(text ?? '').match(/https?:\/\/[^\s<>]+/g) || []
  const seen = new Set()
  const out = []
  for (const raw of urls) {
    const clean = raw.replace(/[.,!?;:)\]}]+$/, '')
    if (seen.has(clean)) continue
    const v = detectVideo(clean)
    if (v) { seen.add(clean); out.push(v) }
  }
  return out
}
