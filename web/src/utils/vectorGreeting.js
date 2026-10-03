// vectorGreeting.js — первое сообщение Вектора в чате: по РОЛИ и по ИМЕНИ (28.09.2026).
//
// До этого приветствие было одно на всех: «Привет! Я Вектор. Спросите про средний балл,
// задолженности или пропуски…» — администратору предлагались вопросы студента, «привет»
// соседствовал с «спросите», а преподаватель ни разу не слышал своего имени. Требование
// Ярослава: преподавателя приветствовать по имени и отчеству.
//
// Решение вынесено в чистые функции, чтобы проверять их без Pinia и браузера.

const ROLES = ['student', 'teacher', 'admin', 'parent', 'moderator']

/** Ключ словаря приветствия для роли (неизвестная роль — как студент). */
export function greetingKey(role) {
  return `vectorGreet.${ROLES.includes(role) ? role : 'student'}`
}

/**
 * Как обратиться к человеку: сервер присылает готовое `greet` при входе (студенту — имя,
 * остальным — имя и отчество, см. webdata.address_name). Для сессий, открытых до этой
 * версии, `greet` нет — тогда разбираем полное ФИО «Фамилия Имя Отчество».
 */
export function greetingName(user) {
  if (!user) return ''
  if (user.greet) return String(user.greet).trim()
  const words = String(user.name || '').trim().split(/\s+/).filter(Boolean)
  if (words.length < 2) return ''
  return user.role === 'student' ? words[1] : words.slice(1, 3).join(' ')
}

/**
 * Вставка имени в шаблон «Здравствуйте{name}!». Без имени — просто «Здравствуйте!»,
 * а не «Здравствуйте, !». Китайский — со своей запятой.
 */
export function namePart(name, lang) {
  if (!name) return ''
  return (lang === 'zh' ? '，' : ', ') + name
}
