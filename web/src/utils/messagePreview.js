// messagePreview.js — человеческий вид сообщения ОДНОЙ СТРОКОЙ (список чатов, цитаты,
// уведомления). Раньше строка списка печатала сырое тело, и служебные сообщения выглядели
// как «user_joined\x1fadmin:admin\x1fАдминистратор», а кнопка отчёта — как «rpt:К75/1|3».
//
// Один модуль на весь мессенджер намеренно: разметка тела задаётся СЕРВЕРОМ (kind/body),
// и два независимых разборщика (в списке и в ленте) неизбежно разъезжаются — так уже
// вышло с системными сообщениями, которые лента показывала правильно, а список нет.

// Разделитель полей служебного сообщения — \x1f (Unit Separator), НЕ ':': id участника сам
// вида "stud:login" и split(':') расклеивал бы его на куски.
const SEP = '\x1f'

/** Служебное событие ("user_joined\x1f<id>\x1f<ФИО>") → человеческий текст. */
export function formatSystemMessage(body) {
  const parts = String(body || '').split(SEP)
  const type = parts[0]
  const rest = parts.slice(1)
  if (type === 'user_joined' || type === 'user_left') {
    const name = rest[1] || rest[0] || 'Участник'
    return type === 'user_joined' ? `${name} вступил(а) в беседу` : `${name} покинул(а) беседу`
  }
  if (type === 'title_changed') return `Название изменено на «${rest[0] || ''}»`
  if (type === 'pin_added') return '📌 Сообщение закреплено'
  if (type === 'pin_removed') return 'Сообщение откреплено'
  return body
}

/**
 * Markdown-разметку в однострочном предпросмотре не показываем — только текст.
 * Набор символов ТОТ ЖЕ, что понимает лента (utils/markdownLite): **жирный**, __подчёрк__,
 * ~~зачёркнутый__, *курсив*, `код`, ```блок```, > цитата, ссылки. Иначе получалось
 * несогласованно: в переписке текст оформлен, а в списке чатов рядом с ним торчат «**».
 */
function stripMarkup(text) {
  return String(text || '')
    .replace(/```[\s\S]*?```/g, '[код]')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')   // ссылка → её текст
    .replace(/\*\*\*([^*]+)\*\*\*/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/^\s*>\s?/gm, '')                   // цитата
    .replace(/^\s*[-*]\s+/gm, '• ')              // список
    .replace(/^\s*#{1,2}\s*/gm, '')              // заголовок
    .replace(/\s*\n+\s*/g, ' ')                  // многострочное — в одну строку
    .trim()
}

/**
 * Текст последнего сообщения для строки чата.
 * @param {object|null} msg  last_message из /chats
 * @param {object} opts  { withSender: показывать «Имя: …» (группы/каналы) }
 */
export function messagePreview(msg, opts = {}) {
  if (!msg) return ''
  if (msg.deleted) return 'Сообщение удалено'
  let text
  if (msg.kind === 'system') text = formatSystemMessage(msg.body)
  //Кнопка отчёта несёт в теле только id («rpt:К75/1|3») — показывать его человеку нечего.
  else if (msg.kind === 'report') {
    const seq = msg.report?.seq
    text = seq ? `📊 Отчёт №${seq} по группе ${msg.report.group || ''}`.trim() : '📊 Отчёт по группе'
  } else text = stripMarkup(msg.body)
  if (!text) return ''
  if (msg.kind === 'system') return text          //служебные — без подписи автора
  if (msg.mine) return `Вы: ${text}`
  if (opts.withSender && msg.sender_name) return `${msg.sender_name}: ${text}`
  return text
}
