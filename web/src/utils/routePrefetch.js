// routePrefetch.js — тихая догрузка страниц СВОЕЙ роли после первой отрисовки.
//
// ━━ ЗАЧЕМ ━━
// Страницы разрезаны по маршрутам (`router/index.js`, `() => import(...)`), и первая
// загрузка похудела с 1 468 кБ до 347 кБ. Но у нарезки есть цена, и она реальная:
//   • в браузере service worker кладёт чанк в кэш ТОЛЬКО когда за ним обратились, а
//     значит страница, куда человек ни разу не заходил, в офлайне не откроется вовсе —
//     раньше весь код лежал в одном файле и был доступен всегда;
//   • первый переход на страницу стоит сетевого круга, и на плохой связи он заметен.
// Прогрев закрывает оба: экран уже показан, человек читает — а страницы его роли тем
// временем тихо доезжают и оседают в кэше.
//
// ⚠️ Только СВОЯ роль. Тянуть студенту админку значило бы вернуть ровно тот единый
// мегабайт, ради избавления от которого всё и делалось.
//
// ⚠️ Прогрев идёт в ПРОСТОЕ время (`requestIdleCallback`) и по одной странице за раз.
// Пачка параллельных запросов сразу после входа отобрала бы канал у того, что человек
// ждёт прямо сейчас: у ленты сообщений и у журнала.
//
// ⚠️ На экономном режиме и на медленной сети НЕ ГРЕЕМ ВООБСЕ. `navigator.connection`
// говорит и про 2G, и про включённый «экономия трафика»: качать впрок мегабайт тому,
// кто попросил не тратить его трафик, — ровно то, о чём просили не делать.

/** Когда браузер свободен. `requestIdleCallback` есть не везде (Safari) — запасной таймер. */
function whenIdle(fn) {
  if (typeof requestIdleCallback === 'function') requestIdleCallback(fn, { timeout: 4000 })
  else setTimeout(fn, 1500)
}

/** Стоит ли вообще качать впрок. */
function allowed() {
  const c = navigator.connection
  if (!c) return true
  if (c.saveData) return false
  return !['slow-2g', '2g'].includes(c.effectiveType || '')
}

/**
 * Достаёт ленивые загрузчики страниц роли из таблицы маршрутов.
 *
 * ⚠️ Берём именно `component` У ДЕТЕЙ ветки роли: у самой ветки компонент — это
 * оболочка `AppShell`, она уже загружена, и её «прогрев» ничего бы не дал.
 */
export function lazyLoadersForRole(routes, role) {
  const out = []
  for (const r of routes || []) {
    if (r.meta?.role && r.meta.role !== role) continue
    for (const child of r.children || []) {
      const c = child.component
      //Ленивый маршрут — это ФУНКЦИЯ. У статических (`AppShell`, `LoginPage`) component
      //это объект компонента, и звать его нельзя.
      if (typeof c === 'function') out.push(c)
    }
  }
  return out
}

/**
 * Прогреть страницы роли. Возвращает промис — он нужен тестам и ничему больше:
 * вызывающий ничего не ждёт, в этом весь смысл.
 */
export function prefetchRoutes(routes, role) {
  if (!role || !allowed()) return Promise.resolve(0)
  const loaders = lazyLoadersForRole(routes, role)
  return new Promise((resolve) => {
    let i = 0
    let done = 0
    const step = () => {
      if (i >= loaders.length) { resolve(done); return }
      const load = loaders[i++]
      //Сбой прогрева — не событие: страница просто доедет при переходе, как и до него.
      Promise.resolve()
        .then(load)
        .then(() => { done += 1 })
        .catch(() => {})
        .finally(() => whenIdle(step))
    }
    whenIdle(step)
  })
}
