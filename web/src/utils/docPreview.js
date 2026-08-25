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

async function inflateRaw(chunk) {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('браузер не умеет распаковывать')
  }
  const stream = new Blob([chunk]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

/**
 * Текст из DOCX. Возвращает абзацы строками.
 *
 * ⚠️ Разбираем разметку РЕГУЛЯРКАМИ по `<w:p>`/`<w:t>`, а не DOM-парсером: строить
 * XML-дерево на документе в мегабайт ради текста — лишняя память на телефоне, а
 * структура здесь ровно та, что нам нужна, и она стабильна.
 */
export async function docxText(buf) {
  const entry = findInZip(buf, 'word/document.xml')
  const raw = new Uint8Array(buf).subarray(entry.start, entry.end)
  // method 0 — файл лежит без сжатия (так бывает у мелких документов).
  const xmlBytes = entry.method === 0 ? raw : await inflateRaw(raw)
  const xml = new TextDecoder().decode(xmlBytes)

  const paragraphs = []
  for (const p of xml.split(/<w:p[ >]/).slice(1)) {
    let text = ''
    for (const m of p.matchAll(/<w:t[^>]*>([\s\S]*?)<\/w:t>/g)) text += m[1]
    // Разрыв строки внутри абзаца Word пишет отдельным тегом.
    text = text.replace(/<w:br\s*\/?>/g, '\n')
    const clean = decodeEntities(text).trim()
    if (clean) paragraphs.push(clean)
  }
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
  return `${(n / 1024 / 1024).toFixed(1)} МБ`
}
