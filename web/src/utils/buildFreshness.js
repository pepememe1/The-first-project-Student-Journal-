/**
 * buildFreshness.js — ПРАВИЛА «пора ли перезагрузить вкладку». Чистые, без окружения.
 *
 * Вынесены из `appVersion.js` не ради красоты: тот тянет `@/api/server` и `window`, и
 * проверить его обычным `node --test` нельзя. А проверять тут есть что — оба правила
 * умеют отказать молча и в обе стороны: не перезагрузиться, когда надо («ломается веб»),
 * и перезагружаться вечно, когда не надо (это хуже исходной жалобы).
 *
 * Тот же приём, что у `pollResult.js`, `menuPlacement.js` и `draftSync.js`.
 */

/**
 * Перезагружаться ли: у нас метка `running`, на сервере `server`, ради `reloadedFor`
 * перезагрузка уже была.
 *
 * ⚠️ Незнание — не повод действовать. Пустая серверная метка означает «не спросили» или
 * «нет связи», а не «вышла новая версия»: перезагрузка в офлайне выкинула бы человека из
 * работающего кабинета в пустой экран.
 *
 * ⚠️ Одна перезагрузка на метку. Если сервер продолжит отдавать старое (кэш прокси,
 * недокатившийся деплой), без этого условия вкладка перезагружалась бы бесконечно.
 */
export function shouldReload(running, server, reloadedFor) {
  if (!running || !server) return false
  if (running === server) return false
  return reloadedFor !== server
}

/**
 * Похожа ли ошибка роутера на «чанка нет на сервере».
 *
 * ⚠️ Текст сообщения у браузеров РАЗНЫЙ, единого кода ошибки нет. Поэтому набор
 * признаков, а не одна строка: промах в сторону лишней перезагрузки безопасен (её всё
 * равно ограничивает разовый замок), промах в другую сторону возвращает ровно тот
 * дефект, ради которого всё написано, — нажатие, после которого не происходит ничего.
 */
export function isChunkLoadError(err) {
  const msg = String(err?.message || err || '').toLowerCase()
  return msg.includes('dynamically imported module')
    || msg.includes('importing a module script failed')
    || msg.includes('failed to fetch dynamically')
    || (msg.includes('loading chunk') && msg.includes('failed'))
}

/**
 * Что делать с отказом загрузки чанка: `'reload'` — перезагрузить вкладку, `'tell'` —
 * оставить как есть и сказать человеку.
 *
 * `locked` — в этой вкладке ради чанка уже перезагружались; `canLock` — замок удаётся
 * записать (в приватном режиме хранилище бывает недоступно); `needLock` — без записанного
 * замка не перезагружаться.
 *
 * ⚠️ `needLock` — для загрузок, которые случаются САМИ, без нажатия: окно, открываемое по
 * ссылке (`?tracker=1`), после перезагрузки попросит тот же чанк снова, и без замка круг
 * «не доехал → перезагрузка → не доехал» не кончился бы никогда. У перехода по меню такого
 * круга нет — после перезагрузки человек остаётся на прежней странице, — поэтому там
 * перезагрузка без замка допустима (прежнее поведение роутера, не меняем).
 */
export function chunkFailureAction(err, { locked = false, canLock = true, needLock = false } = {}) {
  if (!isChunkLoadError(err)) return 'tell'     //не наш случай: перезагрузка его не вылечит
  if (locked) return 'tell'                     //одна перезагрузка на вкладку
  if (needLock && !canLock) return 'tell'
  return 'reload'
}

/**
 * 🔒 У ДВУХ ЗАМКОВ — ДВА КЛЮЧА (нашёл Полковник 07.10.2026).
 *
 * Замок «ради этой метки сборки уже перезагружались» и замок «ради недоехавшего чанка
 * уже перезагружались» лежали в ОДНОМ ключе хранилища и стирали друг друга: метка
 * затирала слово «chunk», слово «chunk» — метку. Пока сервер отдаёт старый index при
 * новой `version.json` (кэш прокси, недокатившийся деплой), вкладка с окном, которое
 * открывается само по ссылке, перезагружалась по кругу: проверка сборки → перезагрузка →
 * чанка нет → перезагрузка → проверка сборки → … — по две на каждый круг, без конца.
 * Раздельные ключи рвут круг на втором шаге: каждый замок помнит своё.
 */
export const STAMP_LOCK_KEY = 'gb.reloaded_for'
export const CHUNK_LOCK_KEY = 'gb.reloaded_for_chunk'

/**
 * Перезагружаться ли ради новой сборки — вместе с записью замка. `storage` — хранилище
 * вкладки или `null`, если оно недоступно (приватный режим): тогда решаем как прежде,
 * без памяти.
 */
export function stampReloadDue(running, server, storage) {
  let done = ''
  try { done = storage?.getItem(STAMP_LOCK_KEY) || '' } catch { /* недоступно */ }
  if (!shouldReload(running, server, done)) return false
  try { storage?.setItem(STAMP_LOCK_KEY, server) } catch { /* приватный режим */ }
  return true
}

/**
 * Перезагружаться ли ради недоехавшего чанка — вместе с записью замка. Решение —
 * `chunkFailureAction`; здесь только хранилище, и оно передаётся снаружи, чтобы правило
 * проверялось без браузера.
 */
export function chunkReloadDue(err, storage, { needLock = false } = {}) {
  let locked = false
  let canLock = !!storage
  try { locked = storage?.getItem(CHUNK_LOCK_KEY) === '1' } catch { canLock = false }
  if (chunkFailureAction(err, { locked, canLock, needLock }) !== 'reload') return false
  try {
    if (!storage) throw new Error('нет хранилища')
    storage.setItem(CHUNK_LOCK_KEY, '1')
  } catch {
    if (needLock) return false           //замок не записался — перезагрузка стала бы кругом
  }
  return true
}
