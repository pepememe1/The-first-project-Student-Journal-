/**
 * deepLinks.js — ссылки, которые люди пересылают друг другу, и возврат после входа.
 *
 * 🔥 Вынесено из роутера, страницы входа и страницы сообщений 26.09.2026 после второго
 * захода Полковника по F-18. «Поделиться контактом» чинился ровно до того места, где
 * ссылка обычно и нужна: получатель без живой сессии попадал на вход, а после входа — на
 * главную своей роли, и `?peer=` терялся. Правила собраны здесь, чтобы их можно было
 * проверить ПОВЕДЕНИЕМ (`web/tests/deepLinks.test.mjs`), а не регуляркой по тексту
 * компонентов — такой сторож прошлый дефект пропустил.
 */

/**
 * Безопасный внутренний адрес возврата после входа ('' — возвращаться некуда).
 *
 * ⚠️ Только путь внутри сайта. `//evil.example` браузер считает адресом ДРУГОГО сайта
 * (схема-относительная ссылка), обратный слэш часть браузеров приравнивает к прямому, а
 * возврат на сам вход дал бы петлю. Открытое перенаправление после входа — классическая
 * заготовка фишинга: «войдите по нашей ссылке» уводит уже вошедшего человека наружу.
 */
export function safeRedirect(raw) {
  const s = typeof raw === 'string' ? raw.trim() : ''
  if (!s.startsWith('/') || s.startsWith('//') || s.includes('\\')) return ''
  if (/^\/login(\/|\?|$)/.test(s)) return ''
  return s
}

/** Куда вести после успешного входа: адрес возврата, иначе главная роли. */
export function afterLoginTarget(role, query, homeByRole) {
  return safeRedirect(query && query.redirect) || homeByRole[role] || '/'
}

/**
 * Нейтральный к роли адрес `/messages`: у получателя ссылки роль своя, и путь
 * `/{роль отправителя}/messages` вёл бы в чужой кабинет. Не вошёл — на вход, с возвратом
 * сюда же вместе с запросом (`?peer=`, `?chat=`).
 */
export function messagesRedirect(isAuthenticated, role, fullPath, query) {
  if (!isAuthenticated) return { path: '/login', query: { redirect: fullPath } }
  return { path: `/${role}/messages`, query }
}

/**
 * Что открыть по запросу страницы сообщений. `chat` главнее `peer`: ссылка на конкретное
 * сообщение точнее ссылки на человека, и открывать обе разом значило бы дёрнуть ленту дважды.
 */
export function linkAction(query) {
  const chat = String((query && query.chat) || '')
  if (chat) return { kind: 'chat', id: chat, msg: Number((query && query.msg) || 0) }
  const peer = String((query && query.peer) || '')
  if (peer) return { kind: 'peer', id: peer }
  return null
}
