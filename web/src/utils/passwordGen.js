/**
 * Генератор паролей для админки — кнопка «⟳» рядом с полем пароля при создании
 * и правке студента/преподавателя/родителя.
 *
 * ⚠️ ВТОРАЯ РЕАЛИЗАЦИЯ в продукте, и это осознанно. Первая — серверная
 * `server/app/reg_utils.py::gen_password` (выдаёт пароль при одобрении заявки на
 * самостоятельную регистрацию). Ходить на сервер ради нажатия кнопки — добавить
 * сетевой отказ и спиннер туда, где расчёт занимает микросекунды и обязан работать
 * даже при мёртвой сети (внутри программы админка живёт на локальном сервере).
 * АЛФАВИТ И ПОЛИТИКА обязаны совпадать с питоновской: их сверяет
 * `web/tests/passwordGen.test.mjs`, читая сам `reg_utils.py` — разъезд ловится
 * тестом, а не жалобой «пароли из двух мест выглядят по-разному».
 */

// Ровно `_SPECIALS` из reg_utils.py. Набор узкий намеренно: кавычки, слеш и пробел
// ломают копирование через терминал и вставку в чужие формы, а пароль этот человек
// диктует вслух и вводит руками.
const SPECIALS = '!@#$%^&*'
const LOWER = 'abcdefghijklmnopqrstuvwxyz'
const UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const DIGITS = '0123456789'
const ALPHABET = LOWER + UPPER + DIGITS + SPECIALS

export const PASSWORD_LENGTH = 10
export const PASSWORD_ALPHABET = ALPHABET

/**
 * Случайное целое [0, max) без перекоса по модулю.
 *
 * ⚠️ Только `crypto.getRandomValues`, без отката на `Math.random()`: тихий откат дал бы
 * предсказуемый пароль, который выглядит ровно так же, как настоящий, — это хуже явной
 * ошибки. Секретного контекста функции НЕ нужно (в отличие от `crypto.subtle`), поэтому
 * она работает и на сайте по HTTPS, и на 127.0.0.1 внутри программы, и по локальному IP.
 */
function randomInt(max) {
  const limit = Math.floor(0xffffffff / max) * max   // хвост диапазона отбрасываем
  const buf = new Uint32Array(1)
  let v
  do {
    globalThis.crypto.getRandomValues(buf)
    v = buf[0]
  } while (v >= limit)
  return v % max
}

function pick(chars) {
  return chars[randomInt(chars.length)]
}

/**
 * Пароль длиной `length` (минимум 8, как на сервере): гарантированно ≥1 строчная,
 * ≥1 заглавная, ≥1 цифра, ≥1 спецсимвол.
 *
 * Питоновский близнец добирает случайную строку и ПЕРЕБИРАЕТ, пока та не удовлетворит
 * условию; здесь по одному символу каждого класса кладётся сразу, остаток добирается из
 * общего алфавита, и всё перемешивается. Политика та же, но время работы фиксировано —
 * цикла «а вдруг не повезёт», который в интерфейсе некому прервать, нет вовсе.
 */
export function generatePassword(length = PASSWORD_LENGTH) {
  const size = Math.max(8, length)
  const chars = [pick(LOWER), pick(UPPER), pick(DIGITS), pick(SPECIALS)]
  while (chars.length < size) chars.push(pick(ALPHABET))

  // Перемешивание Фишера—Йетса: без него первые четыре позиции всегда шли бы
  // «строчная, заглавная, цифра, спец» — по паролю читался бы сам генератор.
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomInt(i + 1)
    const t = chars[i]
    chars[i] = chars[j]
    chars[j] = t
  }
  return chars.join('')
}
