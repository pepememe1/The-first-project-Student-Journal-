/**
 * loginHints.js — что проверить, когда журнал ответил «неверный логин или пароль».
 *
 * Зачем (13.10.2026, совет преподавателей: «делайте для тех, кто с компьютером на вы»).
 * Отказ во входе — первое, во что упирается человек, и единственное, что он видел, было
 * «Неверный логин или пароль». Пароль при этом скрыт точками: набран ли он русскими
 * буквами, заглавными, с пробелом на конце — на экране не видно. Причину знаем МЫ (она в
 * самих полях), поэтому называем её, а не оставляем человека перебирать попытки до
 * блокировки.
 *
 * ⚠️ Это ПОДСКАЗКИ, а не проверки: вход они не запрещают. Логин вполне может быть выдан
 * с заглавной буквой или кириллицей, поэтому формулировки — «проверьте», и показываются
 * они только ПОСЛЕ отказа сервера, а не пока человек печатает.
 *
 * Вынесено из страницы, чтобы правила проверялись без браузера
 * (`web/tests/loginHints.test.mjs`).
 */

const CYRILLIC = /[а-яё]/i
const UPPER = /[A-ZА-ЯЁ]/
const LOWER = /[a-zа-яё]/

/**
 * Ключи подсказок по порядку важности. Пустой список — назвать нечего.
 *   caps             — включён Caps Lock (самое частое и самое невидимое);
 *   passwordCyrillic — в пароле русские буквы: скорее всего не переключён язык клавиатуры;
 *   loginCyrillic    — то же в логине;
 *   loginCapital     — в логине есть заглавные (телефон сам ставит первую букву большой);
 *   loginSpace       — пробел внутри логина;
 *   passwordSpace    — пароль начинается или кончается пробелом (вставили из сообщения).
 */
export function loginHints({ login = '', password = '', capsLock = false } = {}) {
  const out = []
  const name = String(login).trim()
  const pass = String(password)
  if (capsLock) out.push('caps')
  if (CYRILLIC.test(pass)) out.push('passwordCyrillic')
  if (CYRILLIC.test(name)) out.push('loginCyrillic')
  //Заглавные при включённом Caps Lock уже объяснены первой подсказкой — не дублируем.
  if (!capsLock && UPPER.test(name) && LOWER.test(name)) out.push('loginCapital')
  if (/\s/.test(name)) out.push('loginSpace')
  if (pass !== pass.trim()) out.push('passwordSpace')
  return out
}

/** Включён ли Caps Lock по событию клавиатуры; `null` — событие этого не знает. */
export function capsLockState(event) {
  if (!event || typeof event.getModifierState !== 'function') return null
  return !!event.getModifierState('CapsLock')
}
