// docPreview — предпросмотр документа в браузере, БЕЗ единой внешней библиотеки.
//
// ━━ ПОЧЕМУ НЕ БИБЛИОТЕКА ━━
// Готовые просмотрщики (pdf.js, mammoth) весят сотни килобайт и едут в каждый бандл —
// включая OTA-обновление для телефонов и сборку .exe. Ради «посмотреть, тот ли это
// файл» это дорого. Здесь три пути, и все они опираются на то, что браузер уже умеет:
//
//   PDF     → нативный просмотрщик браузера (встроенный фрейм), наш код не участвует;
//   текст   → просто читаем как текст (txt, md, csv, json, log);
//   DOCX    → распаковываем ZIP и достаём word/document.xml через DecompressionStream.
//
// ━━ ПОЧЕМУ DOCX РАЗБИРАЕМ САМИ ━━
// DOCX — это обычный ZIP. Инфлейт в браузере есть с 2023 года (`DecompressionStream`),
// а разбор оглавления ZIP — три десятка строк. Взамен документ НИКУДА НЕ УХОДИТ: ни на
// наш сервер, ни к стороннему сервису. Для журнала с ПДн студентов это не мелочь —
// у нас уже есть один болезненный пункт с внешним обработчиком (перевод), второй
// заводить незачем.
//
// ⚠️ Это ПРЕДПРОСМОТР, а не вёрстка документа: таблицы, картинки и оформление теряются.
// Так и задумано — задача «убедиться, что это тот файл», а не «открыть вместо Word».

/** Текстовые типы, которые можно показать как есть. */
const TEXT_MIME = new Set([
  'text/plain', 'text/markdown', 'text/csv', 'application/json',
])

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

/** Что вообще умеем показать. Остальное — только скачать. */
export function previewKind(mime, name = '') {
  const m = (mime || '').split(';')[0].trim().toLowerCase()
  if (m === 'application/pdf') return 'pdf'
  if (m === DOCX_MIME) return 'docx'
  if (TEXT_MIME.has(m)) return 'text'
  // Имя — запасной признак: некоторые браузеры отдают пустой тип для .md и .log.
  if (/\.(txt|md|csv|json|log)$/i.test(name)) return 'text'
  return ''
}

/**
 * Прочитать «оглавление» ZIP и вернуть смещения нужного файла.
 *
 * ⚠️ Читаем ЦЕНТРАЛЬНЫЙ КАТАЛОГ с конца, а не идём заголовками с начала. У локального
 * заголовка размеры могут быть нулевыми (их дописывают в data descriptor ПОСЛЕ данных),
 * и наивный проход по файлу спотыкается ровно на тех архивах, которые пишет Word.
 */
function findInZip(buf, wanted) {
  const view = new DataView(buf)
  const bytes = new Uint8Array(buf)

  // Конец центрального каталога (EOCD): сигнатура 0x06054b50, ищем с конца.
  let eocd = -1
  for (let i = bytes.length - 22; i >= 0 && i > bytes.length - 66000; i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break }
  }
  if (eocd < 0) throw new Error('это не ZIP-архив')

  const count = view.getUint16(eocd + 10, true)
  let p = view.getUint32(eocd + 16, true)          // начало центрального каталога

  for (let i = 0; i < count; i++) {
    if (view.getUint32(p, true) !== 0x02014b50) break
    const method = view.getUint16(p + 10, true)
    const compressed = view.getUint32(p + 20, true)
    const nameLen = view.getUint16(p + 28, true)
    const extraLen = view.getUint16(p + 30, true)
    const commentLen = view.getUint16(p + 32, true)
    const localOff = view.getUint32(p + 42, true)
    const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen))

    if (name === wanted) {
      // У ЛОКАЛЬНОГО заголовка своя длина имени и «extra» — она отличается от той, что
      // в каталоге. Считать данные по каталожной — классическая ошибка, дающая мусор.
      const lNameLen = view.getUint16(localOff + 26, true)
      const lExtraLen = view.getUint16(localOff + 28, true)
      const start = localOff + 30 + lNameLen + lExtraLen
      return { method, start, end: start + compressed }
    }
    p += 46 + nameLen + extraLen + commentLen
  }
  throw new Error(`в архиве нет ${wanted}`)
}

/**
 * 🔒 ПРЕДЕЛЫ ПРЕДПРОСМОТРА DOCX (аудит 17.10.2026).
 *
 * Сжатие у ZIP — до тысячи раз, поэтому предел размера ФАЙЛА ничего не говорит о
 * размере РАСПАКОВАННОГО: архив в 4 КБ разворачивался в 4 млн знаков, а распаковка
 * целиком (`Response.arrayBuffer()`) и строка поверх неё могли съесть память вкладки
 * или окна программы у получателя — на одном открытии предпросмотра.
 * Теперь распаковка идёт ПОРЦИЯМИ и обрывается на `xmlBytes`; текста показываем не
 * больше `chars` знаков и `paragraphs` абзацев. 4 МБ разметки — это сотня с лишним
 * страниц обычного документа: для «убедиться, что это тот файл» с запасом.
 */
export const DOCX_PREVIEW_LIMITS = Object.freeze({
  xmlBytes: 4 * 1024 * 1024,
  chars: 200_000,
  paragraphs: 5_000,
})

/** Метка в конце обрезанного предпросмотра — тем же словом, что у `plainText`. */
export const DOCX_CUT_MARK = '[…документ показан не целиком…]'

/**
 * Распаковать deflate-raw, но не больше `limit` байт.
 * Возвращает `{ bytes, truncated }`; лишнее НЕ распаковывается (поток отменяется).
 */
export async function inflateRaw(chunk, limit = DOCX_PREVIEW_LIMITS.xmlBytes) {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('браузер не умеет распаковывать')
  }
  const reader = new Blob([chunk]).stream()
    .pipeThrough(new DecompressionStream('deflate-raw')).getReader()
  const parts = []
  let total = 0
  let truncated = false
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    const room = limit - total
    if (value.length > room) {
      if (room > 0) parts.push(value.subarray(0, room))
      total = limit
      truncated = true
      // Дальше не распаковываем вовсе: отменённый поток не тратит ни память, ни время.
      try { await reader.cancel() } catch { /* поток уже закрыт — отменять нечего */ }
      break
    }
    parts.push(value)
    total += value.length
  }
  const bytes = new Uint8Array(total)
  let at = 0
  for (const p of parts) { bytes.set(p, at); at += p.length }
  return { bytes, truncated }
}

/**
 * Текст из DOCX. Возвращает абзацы строками; обрезанный предпросмотр кончается
 * абзацем `DOCX_CUT_MARK`.
 *
 * ⚠️ Разбираем разметку РЕГУЛЯРКАМИ по `<w:p>`/`<w:t>`, а не DOM-парсером: строить
 * XML-дерево на документе в мегабайт ради текста — лишняя память на телефоне, а
 * структура здесь ровно та, что нам нужна, и она стабильна.
 */
export async function docxText(buf, limits = DOCX_PREVIEW_LIMITS) {
  const entry = findInZip(buf, 'word/document.xml')
  const raw = new Uint8Array(buf).subarray(entry.start, entry.end)
  // method 0 — файл лежит без сжатия (так бывает у мелких документов). Предел тот же:
  // «без сжатия» не значит «маленький».
  let xmlBytes, truncated
  if (entry.method === 0) {
    truncated = raw.length > limits.xmlBytes
    xmlBytes = truncated ? raw.subarray(0, limits.xmlBytes) : raw
  } else {
    ({ bytes: xmlBytes, truncated } = await inflateRaw(raw, limits.xmlBytes))
  }
  const xml = new TextDecoder().decode(xmlBytes)

  const paragraphs = []
  let chars = 0
  // Обрыв посреди разметки безопасен: кусок текста берётся только из ЗАКРЫТОГО `<w:t>`,
  // и недописанный хвост последнего абзаца просто не совпадёт.
  for (const p of xml.split(/<w:p[ >]/).slice(1)) {
    let text = ''
    for (const m of p.matchAll(/<w:t[^>]*>([\s\S]*?)<\/w:t>/g)) text += m[1]
    // Разрыв строки внутри абзаца Word пишет отдельным тегом.
    text = text.replace(/<w:br\s*\/?>/g, '\n')
    let clean = decodeEntities(text).trim()
    if (!clean) continue
    if (paragraphs.length >= limits.paragraphs || chars >= limits.chars) { truncated = true; break }
    if (chars + clean.length > limits.chars) {
      clean = clean.slice(0, limits.chars - chars)
      truncated = true
    }
    paragraphs.push(clean)
    chars += clean.length
  }
  if (truncated) paragraphs.push(DOCX_CUT_MARK)
  return paragraphs
}

function decodeEntities(s) {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')      // &amp; последним, иначе развернём чужие сущности дважды
}

/** Текст из простого файла. Ограничиваем: предпросмотр не должен вешать вкладку. */
export function plainText(buf, limit = 200_000) {
  const bytes = new Uint8Array(buf)
  const cut = bytes.length > limit ? bytes.subarray(0, limit) : bytes
  const text = new TextDecoder('utf-8', { fatal: false }).decode(cut)
  return bytes.length > limit ? text + '\n\n[…файл показан не целиком…]' : text
}

/** Человеческий размер. Тут же, чтобы не заводить его в трёх компонентах по-своему. */
export function humanSize(bytes) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} КБ`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} МБ`
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} ГБ`
}
