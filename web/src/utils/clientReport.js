/**
 * clientReport.js — ошибки интерфейса и время старта уходят на наш сервер
 * (server/app/client_metrics.py, видно админу в разделе «Сервер»).
 *
 * Зачем (разбор мобильной версии 23.10.2026). Необработанная ошибка на телефоне студента
 * печаталась в консоль, которую никто не видит. Ни доли сбоев, ни времени старта у людей
 * мы не знали, а проверяли приложение на флагмане.
 *
 * Уходит только то, по чему ищут дефект: тип ошибки, сообщение без строк в кавычках, чисел
 * и почты, первый кадр стека нашего бандла, шаблон маршрута (`/teacher/journal`, без
 * параметров и запроса), платформа и версия сборки. Логина, адреса страницы и её текста нет.
 *
 * Отправка — `sendBeacon` прямо на боевой адрес: не ждёт ответа, переживает закрытие
 * страницы и одинаково работает на сайте, в программе и в приложении. Внутри программы
 * отчёт идёт мимо локального сервера: запись через него запускала бы обновление зеркала.
 */
import { isChunkLoadError } from './buildFreshness.js'

//Одна сломанная страница в цикле перерисовки не должна засыпать сервер отчётами.
export const MAX_ERRORS = 10

//Апостроф внутри слова («Can't find variable») — не кавычка: иначе всё после него
//пропадало, и разные ошибки сливались в одну (Полковник 23.10.2026). Граница слова —
//явным классом, а не \w: в JS \w не знает кириллицы, а правило одно с сервером.
const QUOTED = /(?<![A-Za-zА-Яа-яЁё0-9_])'[^']*'|"[^"]*"|`[^`]*`|«[^»]*»/g
const UNCLOSED = /(?<![A-Za-zА-Яа-яЁё0-9_])['"`«][^'"`»]*$/
const EMAIL = /\S+@\S+/g
const NUMBER = /\d{2,}/g

/**
 * Сообщение без того, что может оказаться данными человека (то же правило — на сервере).
 * Сначала обрезка: поиск почты на длинной строке без пробелов работает квадратично.
 * Кавычка, закрытие которой обрезано, тоже скрывает всё после себя.
 */
export function scrubMessage(text) {
  return String(text || '').replace(/[\r\n\t]+/g, ' ').slice(0, 640)
    .replace(QUOTED, '…').replace(UNCLOSED, '…').replace(EMAIL, '…').replace(NUMBER, 'N')
    .slice(0, 160)
}

/** Первый кадр стека из нашего бандла: `assets/index-abc.js:1:2345`, без адреса сайта. */
export function topFrame(stack) {
  const m = String(stack || '').match(/(assets\/[\w.-]+\.js):(\d+):(\d+)/)
  return m ? `${m[1]}:${m[2]}:${m[3]}` : ''
}

/** Шаблон маршрута (`/teacher/journal`, `/messages/:id`) — без значений параметров. */
export function routeTemplate(route) {
  const matched = route && route.matched
  const last = matched && matched.length ? matched[matched.length - 1].path : ''
  return last || '/'
}

/** Не дефект кода: сеть, отменённый запрос, старый чанк после выкладки, шум браузера. */
export function isNoise(err) {
  if (!err) return true
  const name = err.name || ''
  if (name === 'AxiosError' || name === 'CanceledError' || err.isAxiosError) return true
  if (isChunkLoadError(err)) return true
  return /ResizeObserver loop/.test(String(err.message || err))
}

/**
 * Отчётчик одного запуска. `send(payload)` передаёт вызывающий: в приложении это маячок,
 * в тесте — запись в массив.
 */
export function makeReporter({ send, platform, version, max = MAX_ERRORS }) {
  const seen = new Set()
  let sent = 0
  let startupSent = false
  return {
    error(err, route) {
      if (isNoise(err) || sent >= max) return false
      const e = {
        name: String((err && err.name) || 'Error').slice(0, 40),
        message: scrubMessage(err && err.message ? err.message : err),
        frame: topFrame(err && err.stack),
        route: routeTemplate(route),
      }
      const key = `${e.name}|${e.message}|${e.frame}|${e.route}`
      if (seen.has(key)) return false
      seen.add(key)
      sent += 1
      send({ platform, version, errors: [e] })
      return true
    },
    startup(ms, route, device = {}) {
      if (startupSent) return false
      startupSent = true
      send({ platform, version,
             startup: { ms: Math.round(ms), route: routeTemplate(route), ...device } })
      return true
    },
  }
}

function beacon(url, payload) {
  const body = JSON.stringify(payload)
  try {
    //text/plain — «простой» запрос: без предварительного OPTIONS, ответ не нужен.
    if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([body], { type: 'text/plain' }))) return
  } catch { /* маячка нет — ниже обычный запрос */ }
  try {
    fetch(url, { method: 'POST', body, keepalive: true, mode: 'no-cors',
                 headers: { 'Content-Type': 'text/plain' } }).catch(() => {})
  } catch { /* отчёт — не повод для ещё одной ошибки */ }
}

/**
 * Куда слать отчёт. Программа и телефон — на публичный сайт, мимо локального сервера
 * программы (§4.50). Обычный браузер шлёт к себе: на 127.0.0.1 в браузере работает стенд
 * или разработчик, и `publicSiteOrigin()` увёл бы их отчёты в боевую статистику (живой
 * прогон 27.10.2026: со стенда на бой уходил POST и получал 405).
 */
export function reportOrigin({ desktop, native, here, publicOrigin }) {
  return desktop || native || !here ? publicOrigin : here
}

/**
 * Подключить отчёты: обработчик ошибок Vue, необработанные ошибки и отказы промисов,
 * время до первого экрана. Зовётся один раз из main.js до `app.mount`.
 */
export function installClientReport(app, router, { platform, version, origin }) {
  const reporter = makeReporter({
    platform, version, send: (p) => beacon(`${origin}/app/client-report`, p),
  })
  const route = () => router.currentRoute.value
  const prev = app.config.errorHandler
  app.config.errorHandler = (err, instance, info) => {
    if (prev) prev(err, instance, info)
    reporter.error(err, route())
  }
  window.addEventListener('error', (e) => reporter.error(e.error || e.message, route()))
  window.addEventListener('unhandledrejection', (e) => reporter.error(e.reason, route()))
  //«Первый экран готов» — первый кадр после того, как маршрутизатор дождался ленивой
  //страницы. Отсчёт `performance.now()` идёт от начала загрузки документа, то есть
  //нативный запуск WebView сюда не входит: его меряет `adb shell am start -W`.
  router.isReady().then(() => requestAnimationFrame(() => {
    const nav = typeof navigator !== 'undefined' ? navigator : {}
    reporter.startup(performance.now(), route(),
      { mem: nav.deviceMemory || null, cores: nav.hardwareConcurrency || null })
  })).catch(() => {})
  return reporter
}
