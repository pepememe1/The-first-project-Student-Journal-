// messagePreview.js — человеческий вид сообщения ОДНОЙ СТРОКОЙ (список чатов, цитаты,
// уведомления). Раньше строка списка печатала сырое тело, и служебные сообщения выглядели
// как «user_joined\x1fadmin:admin\x1fАдминистратор», а кнопка отчёта — как «rpt:К75/1|3».
//
// Один модуль на весь мессенджер намеренно: разметка тела задаётся СЕРВЕРОМ (kind/body),
// и два независимых разборщика (в списке и в ленте) неизбежно разъезжаются — так уже
// вышло с системными сообщениями, которые лента показывала правильно, а список нет.
//
// useLocaleStore() вызывается ВНУТРИ функций (не на верхнем уровне модуля), поэтому всегда
// читает ТЕКУЩИЙ активный язык — тот же приём, что в composables/useConfirm.js.
import { useLocaleStore } from '../stores/locale.js'

// Разделитель полей служебного сообщения — \x1f (Unit Separator), НЕ ':': id участника сам
// вида "stud:login" и split(':') расклеивал бы его на куски.
const SEP = '\x1f'

/** Служебное событие ("user_joined\x1f<id>\x1f<ФИО>") → человеческий текст. */
export function formatSystemMessage(body) {
  const t = useLocaleStore().t
  const parts = String(body || '').split(SEP)
  const type = parts[0]
  const rest = parts.slice(1)
  if (type === 'user_joined' || type === 'user_left') {
    const name = rest[1] || rest[0] || t('messagePreview.participant', 'Участник')
    return type === 'user_joined' ? t('messagePreview.joined', { name }) : t('messagePreview.left', { name })
  }
  if (type === 'title_changed') return t('messagePreview.titleChanged', { title: rest[0] || '' })
  if (type === 'pin_added') return t('messagePreview.pinAdded', '📌 Сообщение закреплено')
  if (type === 'pin_removed') return t('messagePreview.pinRemoved', 'Сообщение откреплено')
  //§ролей: /mute и /clear тоже постят системную строку — тот же приём, что «вступил/вышел».
  if (type === 'muted' || type === 'unmuted') {
    const name = rest[1] || rest[0] || t('messagePreview.participant', 'Участник')
    return type === 'muted' ? t('messagePreview.muted', { name }) : t('messagePreview.unmuted', { name })
  }
  if (type === 'cleared') return t('messagePreview.cleared', { n: rest[0] || '0' })
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
  const t = useLocaleStore().t
  if (msg.deleted) return t('chatThread.deleted', 'Сообщение удалено')
  let text
  if (msg.kind === 'system') text = formatSystemMessage(msg.body)
  //Кнопка отчёта несёт в теле только id («rpt:К75/1|3») — показывать его человеку нечего.
  else if (msg.kind === 'report') {
    const seq = msg.report?.seq
    text = seq ? t('messagePreview.reportWithSeq', { seq, group: msg.report.group || '' }).trim() : t('messagePreview.reportNoSeq', '📊 Отчёт по группе')
  }
  //GIF (Klipy) — тело сообщения это прямая ссылка на CDN, показывать её человеку в
  //списке чатов нечего (та же логика, что у отчёта выше).
  else if (msg.kind === 'gif') text = t('messagePreview.gif', 'GIF')
  // ⚠️ Файл — отдельная ветка. Без неё сообщение, состоящее ТОЛЬКО из файла (подпись
  // необязательна), давало в списке чатов ПУСТУЮ строку: тело пустое, а про `kind`
  // превью не знало. Найдено Полковником 25.08.2026.
  else if (msg.kind === 'file') {
    const name = msg.attachment?.name || ''
    text = (msg.body || '').trim() || (name ? `📎 ${name}` : t('messagePreview.file', 'Файл'))
  }
  //Активность и сохранённая доска — тот же случай: в теле лежит только id («act:6de1…»),
  //и он уезжал в список чатов как есть. Название категории берём из ТОГО ЖЕ словаря
  //`activity.kind.*`, которым подписаны карточки в ленте, — второй копии названий не
  //заводим, иначе они разъедутся при добавлении новой категории.
  else if (msg.kind === 'activity') {
    const kind = msg.activity?.kind
    const cat = kind ? t(`activity.kind.${kind}`, '') : ''
    const title = (msg.activity?.title || '').trim()
    //«Активность: Викторина» и, если у неё есть своё имя, «… · тест по циклам».
    text = cat ? t('messagePreview.activity', { kind: cat }) : t('messagePreview.activityPlain', 'Активность')
    if (title) text += ` · ${title}`
  }
  else if (msg.kind === 'board') {
    const title = (msg.board?.title || '').trim()
    text = t('messagePreview.board', '🖉 Доска')
    if (title) text += ` · ${title}`
  }
  else text = stripMarkup(msg.body)
  if (!text) return ''
  if (msg.kind === 'system') return text          //служебные — без подписи автора
  if (msg.mine) return t('messagePreview.youPrefix', { text })
  if (opts.withSender && msg.sender_name) return `${msg.sender_name}: ${text}`
  return text
}
