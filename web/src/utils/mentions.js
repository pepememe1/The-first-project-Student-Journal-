// mentions.js — подсветка отметок «@Фамилия» в уже собранном HTML сообщения.
//
// Формы — как у сервера (`routers/messenger/_common.py::_MENTION_RE`): «@», «/@», «/@!»,
// «/!@», «@!», «!@». И то же правило границы: отметка начинается с начала текста или
// после пробела/знака, а не внутри слова и не внутри ссылки.
//
// 🔥 До 16.10.2026 замена шла регуляркой по ВСЕЙ строке HTML, включая атрибуты: ссылка
// «https://example.com/@user» получала `<span class="mention">` прямо внутрь `href`,
// кавычки вставки закрывали атрибут, и по клику открывался не тот адрес. Почта
// «ivan@mail.ru» подсвечивалась как отметка человека «mail». Теперь трогаем только
// текст МЕЖДУ тегами (сам текст сообщения экранирован `markdownLite`, поэтому «<» в нём
// быть не может — каждый «<…>» в строке это наш тег) и пропускаем содержимое `<a>`.

// Перед отметкой не может стоять буква, цифра, «_», «.», «/», «@» или «!» — иначе это
// часть слова, адреса почты или пути ссылки. Без lookbehind: старые WebView его не знают.
const MENTION_RE = /(^|[^A-Za-zА-Яа-яЁё0-9_./@!])(\/?(?:@!?|!@))([A-Za-zА-Яа-яЁё]+)/g

/**
 * @param {string} html — результат `renderMarkdownLite` (текст уже экранирован)
 * @param {(surname: string) => string | undefined} uidFor — id участника по фамилии
 * @returns {string}
 */
export function highlightMentions(html, uidFor = () => undefined) {
  let inLink = 0
  return String(html ?? '')
    .split(/(<[^>]*>)/)
    .map((part) => {
      if (part.startsWith('<')) {
        if (/^<a[\s>]/i.test(part)) inLink += 1
        else if (/^<\/a\s*>/i.test(part)) inLink = Math.max(0, inLink - 1)
        return part
      }
      if (inLink > 0 || !part) return part
      return part.replace(MENTION_RE, (_m, before, prefix, name) => {
        const uid = uidFor(name.toLowerCase())
        const hit = prefix + name
        //id участника ложится в АТРИБУТ — экранируем: он приходит с сервера, но атрибут
        //не должен зависеть от того, какие символы однажды окажутся в логине.
        const attr = String(uid ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
        return before + (uid
          ? `<span class="mention" data-mention-uid="${attr}">${hit}</span>`
          : `<span class="mention">${hit}</span>`)
      })
    })
    .join('')
}
