/**
 * appVersion.js — открытая вкладка узнаёт, что после деплоя её код устарел.
 *
 * 🔥 ЖАЛОБА, КОТОРАЯ ЭТО КУПИЛА (Влад, 07.09.2026): «после каждого деплоя ломается веб на
 * телефоне, показывается старая версия, а новую видно после перезагрузки страницы».
 *
 * ━━ ЧТО ИМЕННО ЛОМАЕТСЯ ━━
 * Страницы ленивые (`() => import(...)`), имя чанка содержит хеш содержимого, а деплой
 * выкладывает новый каталог статики и уносит старый. Вкладка, открытая ДО деплоя, живёт
 * старым кодом и на первом же переходе просит файл, которого на сервере уже нет: 404,
 * `import()` отклоняется, роутер остаётся на месте. Со стороны — нажал пункт меню, и не
 * произошло НИЧЕГО. Ни ошибки на экране, ни чего-либо заметного на телефоне.
 *
 * ━━ ДВЕ ПОЛОВИНЫ ЛЕЧЕНИЯ, И НУЖНЫ ОБЕ ━━
 * • `watchForNewBuild()` — замечает новую сборку ЗАРАНЕЕ и перезагружает страницу в
 *   безопасный момент (когда человек к ней возвращается). Это про «показывается старая».
 * • `reloadOnChunkError()` — ловит уже случившийся отказ загрузки чанка. Это про
 *   «ломается»: если человек не уходил из вкладки, предупредить было негде.
 *
 * ⚠️ ПОЧЕМУ НЕ ПРОСТО «ПЕРЕЗАГРУЖАТЬ ПРИ РАСХОЖДЕНИИ СРАЗУ». Перезагрузка посреди работы
 * уносит то, что человек делает прямо сейчас (открытый диалог, выбранная группа, набор
 * оценок в журнале). Возврат во вкладку — момент, когда он и так начинает заново.
 *
 * ⚠️ ЗАМОК ОТ ЦИКЛА ОБЯЗАТЕЛЕН. Если сервер по какой-то причине продолжит отдавать
 * СТАРЫЙ index.html (кэш прокси, недокатившийся деплой), «перезагрузить и снова увидеть
 * расхождение» — это бесконечная перезагрузка на глазах у человека, то есть отказ хуже
 * исходного. Поэтому на каждую замеченную метку приходится РОВНО ОДНА перезагрузка.
 *
 * ⚠️ В ПРИЛОЖЕНИИ НЕ РАБОТАЕТ И НЕ ДОЛЖНО. Там код приезжает бандлом Capgo (OTA), а
 * `version.json` лежит внутри того же бандла — то есть метка всегда совпадает с собой.
 * Перезагрузка WebView нового кода не принесёт: его ставит обновлялка, а не браузер.
 */
import { isNativeApp } from '@/api/server'
import { useLocaleStore } from '@/stores/locale'
//Решения вынесены в чистый модуль — только его и можно проверить `node --test`.
import { shouldReload, isChunkLoadError, chunkFailureAction, stampReloadDue, chunkReloadDue } from './buildFreshness'
export { shouldReload, isChunkLoadError, chunkFailureAction }

/** Метка текущей сборки. Подставляет Vite (см. build/buildStamp.js). */
export const BUILD_STAMP = typeof __BUILD_STAMP__ === 'string' ? __BUILD_STAMP__ : ''

/** Хранилище вкладки или `null`: в приватном режиме само обращение к нему бросает. */
function tabStorage() {
  try { return window.sessionStorage } catch { return null }
}
// Раз в четверть часа. Опрос тут — вторая линия: основной сигнал даёт возврат во
// вкладку. Чаще незачем, реже — человек может весь день не сворачивать браузер.
const POLL_MS = 15 * 60 * 1000

/**
 * Метка сборки, лежащей на сервере ('' — узнать не удалось).
 *
 * ⚠️ `cache: 'no-store'`: без него браузер (и наш service worker) с удовольствием
 * ответит копией того самого файла, ради свежести которого запрос и делается.
 */
/**
 * ⚠️ СВОЙ СРОК У ФОНОВОГО ЗАПРОСА (UX-аудит 17.10.2026: «сетевой журнал показал
 * таймаутный GET к /version.json»). У `fetch` своего таймаута НЕТ: на залипшем
 * соединении запрос висит столько, сколько решит сеть, и всё это время держит слот
 * соединения к нашему же домену — а слотов у браузера на домен шесть. Ответ здесь
 * никому не срочен (проверка идёт раз в четверть часа), поэтому лучше бросить и
 * спросить в следующий раз, чем ждать молча.
 *
 * ⚠️ `AbortSignal.timeout` проверяем на наличие: он появился в Chrome 103 и Safari 16,
 * а сборку открывают и из WebView2, и из Capacitor. Нет его — запрос уходит как
 * раньше: хуже прежнего не станет.
 */
const STAMP_TIMEOUT_MS = 10000

function stampSignal() {
  try {
    return typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(STAMP_TIMEOUT_MS)
      : undefined
  } catch { return undefined }
}

export async function fetchServerStamp() {
  try {
    const r = await fetch('/version.json',
      { cache: 'no-store', credentials: 'omit', signal: stampSignal() })
    if (!r.ok) return ''
    const j = await r.json()
    return typeof j?.stamp === 'string' ? j.stamp : ''
  } catch {
    return ''   //нет связи — это не «вышла новая версия»
  }
}

/** Проверить сервер и перезагрузиться, если сборка сменилась. */
export async function checkNow(reload = () => window.location.reload()) {
  const server = await fetchServerStamp()
  //Замок «ради этой метки уже перезагружались» — внутри правила, под тестом.
  if (!stampReloadDue(BUILD_STAMP, server, tabStorage())) return false
  reload()
  return true
}

/**
 * Следить за новой сборкой: при возврате во вкладку и раз в POLL_MS.
 *
 * Возврат во вкладку — главный сигнал: на телефоне приложение сворачивают десятки раз в
 * день, и почти любой деплой человек застаёт именно так.
 */
export function watchForNewBuild() {
  if (isNativeApp() || !BUILD_STAMP) return
  const tick = () => { if (document.visibilityState === 'visible') checkNow() }
  document.addEventListener('visibilitychange', tick)
  setInterval(tick, POLL_MS)
}

/**
 * Отказ загрузки чанка = наш код старше выложенного. Перезагружаемся ОДИН раз.
 *
 * Это вторая половина лечения: `watchForNewBuild` предупреждает заранее, но если человек
 * не уходил из вкладки, предупредить было негде — и он упирается в «нажал, ничего не
 * произошло». Здесь мы уже знаем наверняка: страница попросила файл, которого нет.
 */
export function reloadOnChunkError(router, reload = () => window.location.reload()) {
  router.onError((err) => {
    if (reloadOnceForChunk(err, { reload })) return
    if (isChunkLoadError(err)) showChunkFailure(reload)
  })
}

/**
 * Страница не загрузилась и после перезагрузки (файла нет на сервере или нет связи).
 * Раньше человек оставался на пустом белом экране без единого слова (живой прогон
 * 27.10.2026, кабинет родителя). Плашка рисуется прямо в DOM, мимо Vue: дерево
 * приложения в этот момент может быть сломано тем же отказом.
 */
export function showChunkFailure(reload = () => window.location.reload()) {
  if (typeof document === 'undefined' || document.getElementById('gb-chunk-failure')) return
  const t = (k, f) => { try { return useLocaleStore().t(k, f) } catch { return f } }
  const box = document.createElement('div')
  box.id = 'gb-chunk-failure'
  box.setAttribute('role', 'alert')
  box.style.cssText = 'position:fixed;inset:auto 16px 16px 16px;z-index:200;max-width:28rem;margin:0 auto;'
    + 'padding:16px;border-radius:12px;background:var(--gb-card,#fff);color:var(--gb-text,#0f1b22);'
    + 'border:1px solid var(--gb-border2,#d3dbe1);box-shadow:0 8px 30px rgba(0,0,0,.18);font:14px/1.45 inherit'
  const text = document.createElement('p')
  text.textContent = t('chunkFailure.text', 'Не удалось загрузить страницу. Проверьте связь с интернетом и обновите.')
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = t('chunkFailure.reload', 'Обновить')
  btn.style.cssText = 'margin-top:10px;min-height:44px;padding:0 20px;border-radius:8px;border:0;'
    + 'background:var(--gb-accent,#147c8b);color:#fff;font-weight:600;cursor:pointer'
  btn.addEventListener('click', () => reload())
  box.append(text, btn)
  document.body.append(box)
}

/**
 * Недоехавший чанк: перезагрузить вкладку ОДИН раз. Возвращает true, если перезагружаемся.
 *
 * Одна дверь для ленивых страниц (роутер) и ленивых окон (трекер): замок у них общий,
 * потому что и причина общая — код вкладки старше выложенного.
 *
 * Замок на метку сборки тут не годится: серверную мы в этот момент не знаем, а спрашивать
 * её поздно — человек уже нажал и ничего не увидел. Замок разовый, на жизнь вкладки, и
 * лежит в СВОЁМ ключе: в общем с замком сборки они стирали друг друга (см.
 * `buildFreshness.js`). Решение и запись замка — чистая `chunkReloadDue` (под тестом).
 */
export function reloadOnceForChunk(err, { reload = () => window.location.reload(), needLock = false } = {}) {
  if (!chunkReloadDue(err, tabStorage(), { needLock })) return false
  reload()
  return true
}
