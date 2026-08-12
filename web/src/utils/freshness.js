/**
 * freshness.js — «когда эти данные приходили с сервера».
 *
 * Нужно там, где экран может показывать СОХРАНЁННУЮ копию: без связи оценки и
 * расписание выглядят ровно так же, как свежие, и это худший вид неправды: она
 * правдоподобна и её не перепроверяют. Подпись превращает «оценки» в «оценки на
 * утро вторника», и человек сам решает, доверять ли им сейчас.
 *
 * Функция ЧИСТАЯ и возвращает не текст, а описание («минут назад столько-то»).
 * Слова подставляет вызывающий через словарь — иначе русский текст был бы зашит в
 * утилиту и не переводился бы, а проверить формат без запуска интерфейса стало бы
 * нельзя.
 */

/** Порог «только что»: за минуту данные устареть не успевают. */
const JUST_NOW_S = 60
/** До часа считаем минутами — «в 12:40» о свежем ничего не говорит. */
const MINUTES_UPTO_S = 3600

function hhmm(d) {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

/**
 * @param {number} ts   метка времени данных (мс). 0/пусто = не загружалось ни разу
 * @param {number} now  «сейчас» (мс), параметром — чтобы тест не зависел от часов
 * @returns {{kind: 'never'|'now'|'minutes'|'today'|'yesterday'|'date', n?: number,
 *            time?: string, date?: string}}
 */
export function freshness(ts, now = Date.now()) {
  if (!ts) return { kind: 'never' }
  const diff = (now - ts) / 1000
  // Метка из будущего — часы устройства перевели. Врать «через два часа» нельзя,
  // поэтому показываем дату как есть и не притворяемся, что понимаем разницу.
  if (diff < 0) {
    const d = new Date(ts)
    return { kind: 'date', date: `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`, time: hhmm(d) }
  }
  if (diff < JUST_NOW_S) return { kind: 'now' }
  if (diff < MINUTES_UPTO_S) return { kind: 'minutes', n: Math.floor(diff / 60) }

  const d = new Date(ts)
  const nd = new Date(now)
  if (sameDay(d, nd)) return { kind: 'today', time: hhmm(d) }

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameDay(d, yesterday)) return { kind: 'yesterday', time: hhmm(d) }

  return {
    kind: 'date',
    date: `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`,
    time: hhmm(d),
  }
}
