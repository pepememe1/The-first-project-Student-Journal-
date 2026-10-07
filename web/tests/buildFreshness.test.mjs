// buildFreshness.test.mjs — «пора ли перезагрузить вкладку после деплоя».
//
// 🔥 ЖАЛОБА (Влад, 07.09.2026): «после каждого деплоя ломается веб на телефоне,
// показывается старая версия, а новую видно после перезагрузки страницы».
//
// Правило умеет отказать МОЛЧА В ОБЕ СТОРОНЫ, и обе дороги плохие:
//   • не перезагрузиться, когда сборка сменилась → тот самый дефект;
//   • перезагружаться при каждой проверке → вкладка мигает бесконечно, и это ХУЖЕ
//     исходной жалобы, потому что работать становится нельзя вовсе.
// Поэтому проверяем не «функция что-то вернула», а обе границы поимённо.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  shouldReload, isChunkLoadError, chunkFailureAction, stampReloadDue, chunkReloadDue,
  STAMP_LOCK_KEY, CHUNK_LOCK_KEY,
} from '../src/utils/buildFreshness.js'

test('сборка сменилась — перезагружаемся', () => {
  assert.equal(shouldReload('100', '200', ''), true)
})

test('та же сборка — не трогаем вкладку', () => {
  assert.equal(shouldReload('100', '100', ''), false)
})

test('🔒 ради этой метки уже перезагружались — второй раз НЕ идём', () => {
  // Ровно защита от вечного круга: сервер может продолжать отдавать старое (кэш прокси,
  // недокатившийся деплой), и без этого условия человек получил бы мигающий экран.
  assert.equal(shouldReload('100', '200', '200'), false)
  // А вот СЛЕДУЮЩАЯ сборка должна пройти: замок держит одну метку, а не все.
  assert.equal(shouldReload('100', '300', '200'), true)
})

test('🔒 незнание — не повод перезагружаться', () => {
  // Пустая серверная метка = «не спросили» либо «нет связи». Перезагрузка в офлайне
  // выкинула бы человека из работающего кабинета в пустой экран.
  assert.equal(shouldReload('100', '', ''), false)
  assert.equal(shouldReload('', '200', ''), false)
})

test('ошибку загрузки чанка узнаём во ВСЕХ формулировках браузеров', () => {
  // Единого кода ошибки нет, текст у всех свой. Проверяем живые формулировки.
  for (const msg of [
    'Failed to fetch dynamically imported module: https://esstu-gradebook.ru/assets/x.js',
    'error loading dynamically imported module',
    'Importing a module script failed.',
    'Loading chunk 42 failed.',
  ]) {
    assert.equal(isChunkLoadError(new Error(msg)), true, `не узнали: ${msg}`)
  }
})

test('обычную ошибку роутера за устаревший чанк НЕ принимаем', () => {
  // Иначе любая ошибка навигации превращалась бы в перезагрузку — и человек терял бы
  // работу на ровном месте.
  for (const msg of ['Network Error', 'Navigation aborted', 'Redirected when going from /a to /b']) {
    assert.equal(isChunkLoadError(new Error(msg)), false, `ложное срабатывание: ${msg}`)
  }
  assert.equal(isChunkLoadError(null), false)
  assert.equal(isChunkLoadError(undefined), false)
})

// ── недоехавший чанк: перезагрузить или сказать человеку ────────────────────────────
// Одно правило на ленивые страницы (роутер) и ленивые окна (трекер, 07.10.2026). Ошибается
// оно тоже в обе стороны: не перезагрузиться — «нажал, и ничего»; перезагружаться без
// замка там, где окно открывается само по ссылке, — вечный круг.
const CHUNK = new Error('Failed to fetch dynamically imported module: https://x/assets/T-1.js')

test('чанк не доехал — одна перезагрузка на вкладку', () => {
  assert.equal(chunkFailureAction(CHUNK, { locked: false, canLock: true }), 'reload')
  assert.equal(chunkFailureAction(CHUNK, { locked: true, canLock: true }), 'tell')
})

test('не отказ загрузки чанка — перезагрузка его не вылечит', () => {
  assert.equal(chunkFailureAction(new Error('x is not a function'), { locked: false }), 'tell')
  assert.equal(chunkFailureAction(null), 'tell')
})

test('🔒 окно, открываемое само по ссылке, без записанного замка не перезагружается', () => {
  // Приватный режим: хранилище недоступно, замок не записать. По ссылке `?tracker=1`
  // перезагрузка без замка повторялась бы бесконечно.
  assert.equal(chunkFailureAction(CHUNK, { locked: false, canLock: false, needLock: true }), 'tell')
  // У перехода по меню круга нет — прежнее поведение роутера сохранено.
  assert.equal(chunkFailureAction(CHUNK, { locked: false, canLock: false, needLock: false }), 'reload')
})

test('проводка: роутер и окно трекера идут через одну дверь', () => {
  const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
  const app = read('../src/utils/appVersion.js')
  assert.match(app, /router\.onError\(\(err\) => \{ reloadOnceForChunk\(err, \{ reload \}\) \}\)/,
    'отказ загрузки страницы больше не доходит до общего правила')
  assert.match(app, /if \(!chunkReloadDue\(err, tabStorage\(\), \{ needLock \}\)\) return false/,
    'решение о перезагрузке ради чанка принимается мимо проверяемой функции')
  assert.match(app, /if \(!stampReloadDue\(BUILD_STAMP, server, tabStorage\(\)\)\) return false/,
    'решение о перезагрузке ради сборки принимается мимо проверяемой функции')
  assert.doesNotMatch(app, /sessionStorage\.(getItem|setItem)/,
    'замок читают или пишут в обход правил из buildFreshness.js — так два замка и стёрли друг друга')
  const page = read('../src/pages/MessengerPage.vue')
  assert.match(page, /reloadOnceForChunk\(e, \{ needLock: true \}\)/,
    'окно трекера перезагружает вкладку без замка — по ссылке из письма это вечный круг')
})

// ── два замка не стирают друг друга ─────────────────────────────────────────────────
// 🔥 Нашёл Полковник (07.10.2026). Оба замка лежали в одном ключе. Сервер отдаёт старый
// index при новой `version.json`, вкладка открыта по ссылке, которая сама открывает окно
// с ленивым чанком: проверка сборки → перезагрузка → чанка нет → перезагрузка → проверка
// сборки → … Каждый шаг был «законной единственной перезагрузкой» своего замка.
const fakeStorage = () => {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)) }, m }
}

/** Жизнь одной вкладки: сколько перезагрузок случится за `rounds` кругов «проверка сборки
 * + окно по ссылке просит чанк», пока сервер отдаёт старый код. */
function reloadsWhileServerIsStale(storage, rounds, { stampKey, chunkKey } = {}) {
  let reloads = 0
  for (let i = 0; i < rounds; i++) {
    //`stampKey`/`chunkKey` — только для обратного хода: прежняя раскладка в одном ключе.
    const stampDue = stampKey
      ? (() => { const done = storage.getItem(stampKey) || ''; if (!shouldReload('S1', 'S2', done)) return false; storage.setItem(stampKey, 'S2'); return true })()
      : stampReloadDue('S1', 'S2', storage)
    if (stampDue) reloads++
    const chunkDue = chunkKey
      ? (() => { if (storage.getItem(chunkKey) === 'chunk') return false; storage.setItem(chunkKey, 'chunk'); return true })()
      : chunkReloadDue(CHUNK, storage, { needLock: true })
    if (chunkDue) reloads++
  }
  return reloads
}

test('🔒 старый index при новой метке и окно по ссылке: две перезагрузки, а не круг', () => {
  assert.notEqual(STAMP_LOCK_KEY, CHUNK_LOCK_KEY, 'замки снова в одном ключе')
  assert.equal(reloadsWhileServerIsStale(fakeStorage(), 10), 2)
})

test('обратный ход: в одном ключе та же вкладка перезагружается на каждом круге', () => {
  // Дословно прежняя раскладка: метка и слово «chunk» в одном ключе.
  const n = reloadsWhileServerIsStale(fakeStorage(), 10, { stampKey: 'k', chunkKey: 'k' })
  assert.equal(n, 20, 'сторож не отличает починенное от сломанного')
})

test('замки пишутся в свои ключи и переживают друг друга', () => {
  const s = fakeStorage()
  assert.equal(chunkReloadDue(CHUNK, s, { needLock: true }), true)
  assert.equal(stampReloadDue('S1', 'S2', s), true)
  assert.equal(s.getItem(CHUNK_LOCK_KEY), '1')
  assert.equal(s.getItem(STAMP_LOCK_KEY), 'S2')
  assert.equal(chunkReloadDue(CHUNK, s, { needLock: true }), false)
  assert.equal(stampReloadDue('S1', 'S2', s), false)
  assert.equal(stampReloadDue('S1', 'S3', s), true, 'следующая сборка обязана пройти')
})

test('хранилище недоступно: страница перезагружается, окно по ссылке — нет', () => {
  const broken = { getItem() { throw new Error('private') }, setItem() { throw new Error('private') } }
  for (const storage of [null, broken]) {
    assert.equal(chunkReloadDue(CHUNK, storage, { needLock: false }), true)    //прежнее поведение роутера
    assert.equal(chunkReloadDue(CHUNK, storage, { needLock: true }), false)
    assert.equal(stampReloadDue('S1', 'S2', storage), true)
    assert.equal(stampReloadDue('S1', 'S1', storage), false)
  }
})
