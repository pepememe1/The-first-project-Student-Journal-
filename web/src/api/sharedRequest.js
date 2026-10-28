// sharedRequest.js — одновременные одинаковые GET делят один запрос (28.10.2026).
//
// На старте пять сторов (тема, язык, профиль, гифки, перевод) спрашивают /me/prefs почти
// разом, и каждый вход стоил серверу на одном ядре три-четыре одинаковых запроса.
//
// Ключ — адрес И поколение сессии: запрос прежнего владельца новому не достаётся, иначе
// вошедший получил бы чужой ответ, отклонённый как stale (§4.23). Готовый ответ не
// хранится — следующий вызов идёт на сервер заново. Данные каждый получает своей копией:
// сторы правят то, что им пришло, и общий объект перетекал бы из одного в другой.

const copy = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)))

/** fetch(url) → промис ответа с полем data; generation() → текущее поколение сессии. */
export function makeShared(fetch, generation) {
  const inFlight = new Map()
  return (url) => {
    const key = `${generation()}|${url}`
    let p = inFlight.get(key)
    if (!p) {
      p = fetch(url).finally(() => inFlight.delete(key))
      inFlight.set(key, p)
    }
    return p.then((r) => ({ ...r, data: copy(r?.data) }))
  }
}
