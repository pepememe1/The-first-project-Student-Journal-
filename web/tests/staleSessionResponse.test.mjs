// staleSessionResponse.test.mjs — ответ ПРЕЖНЕЙ сессии не доезжает до сторов нового человека.
//
// 🔥 Дефект (ревью 30.09.2026). Метка владельца (`__owner`/`__gen`) проверялась только
// перед записью в офлайн-кэш, а сам ответ отдавался вызывающему. Выход → вход идёт без
// перезагрузки страницы, Pinia живёт дальше, и запоздавший `profile.load()` или опрос
// списка чатов человека A перезаписывал аватар, «о себе» и названия бесед A поверх
// экрана B. Проверяем решение (чистая функция) и то, что интерсепторы им ПОЛЬЗУЮТСЯ
// на обоих путях; у проверки проводки есть обратный ход.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { isOwnResponse } from '../src/api/responseOwner.js'

const CLIENT = readFileSync(new URL('../src/api/client.js', import.meta.url), 'utf8')

test('ответ той же сессии — наш', () => {
  assert.equal(isOwnResponse({ __owner: 'ivanov', __gen: 3 }, 'ivanov', 3), true)
})

test('ответ другого человека — чужой', () => {
  assert.equal(isOwnResponse({ __owner: 'ivanov', __gen: 3 }, 'petrova', 3), false)
})

test('тот же логин после выхода и нового входа — уже другая сессия', () => {
  assert.equal(isOwnResponse({ __owner: 'ivanov', __gen: 3 }, 'ivanov', 4), false)
})

test('вышел и ещё никто не вошёл — ответ прежнего тоже чужой', () => {
  assert.equal(isOwnResponse({ __owner: 'ivanov', __gen: 3 }, '', 4), false)
})

test('запрос без меток (ушёл мимо нашего интерсептора) не судим', () => {
  assert.equal(isOwnResponse({}, 'ivanov', 9), true)
  assert.equal(isOwnResponse(undefined, 'ivanov', 9), true)
})

// ── Проводка: интерсепторы обязаны звать проверку ДО того, как отдать ответ ─────────
function wiredCorrectly(src) {
  const at = src.indexOf('api.interceptors.response.use(')
  if (at < 0) return false
  const body = src.slice(at)
  const ok = body.indexOf('(resp) =>')
  const bad = body.indexOf('async (error) =>')
  if (ok < 0 || bad < 0) return false
  const success = body.slice(ok, bad)
  const failure = body.slice(bad, body.indexOf('status !== 401'))
  const rejectOnSuccess = /if \(!ownsResponse\(config\)\) return Promise\.reject\(/.test(success)
  //Отказ обязан стоять ДО записи в кэш и до `return resp`.
  const beforeCache = success.search(/if \(!ownsResponse\(config\)\)/) < success.indexOf('writeCache(')
  const rejectOnError = /!ownsResponse\(config\)\)\s*\{\s*return Promise\.reject\(/.test(failure)
  return rejectOnSuccess && beforeCache && rejectOnError
}

test('интерсепторы отказывают ответу прежней сессии на обоих путях', () => {
  assert.equal(wiredCorrectly(CLIENT), true)
})

test('обратный ход: без отказа на успешном пути проверка краснеет', () => {
  const broken = CLIENT.replace(/\n\s*if \(!ownsResponse\(config\)\) return Promise\.reject\([^\n]*/, '')
  assert.notEqual(broken, CLIENT, 'обратный ход не нашёл строку, которую ломает')
  assert.equal(wiredCorrectly(broken), false)
})

test('обратный ход: без отказа на пути ошибки проверка краснеет', () => {
  const broken = CLIENT.replace(/if \(config && !ownsResponse\(config\)\) \{/, 'if (false) {')
  assert.notEqual(broken, CLIENT, 'обратный ход не нашёл строку, которую ломает')
  assert.equal(wiredCorrectly(broken), false)
})

// ── Ветки «нет ответа = нет сети» обязаны отличать отказ прежней сессии ─────────────
// У отказа прежней сессии нет `response`. Ветка, которая по отсутствию ответа кладёт
// правку в офлайн-очередь или откатывает поле стора, без этой проверки положила бы
// оценку человека A в очередь под вошедшим B. Проверяем СВОЙСТВО по всему web/src:
// каждое `!e?.response` стоит в catch, где раньше спрошено `isStaleSession(e)`.
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { isStaleSession } from '../src/api/responseOwner.js'

function* sources(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* sources(p)
    else if (/\.(js|vue)$/.test(name)) yield p
  }
}

//Любое имя переменной ошибки: `!e?.response`, `!err.response`, `!error?.response`.
const OFFLINE = /!(\w+)\??\.response\b/

function unguardedOfflineBranches(text) {
  const lines = text.split('\n')
  const bad = []
  lines.forEach((line, i) => {
    const m = OFFLINE.exec(line)
    if (!m) return
    const guard = new RegExp(`isStaleSession\\(${m[1]}\\)`)
    const start = new RegExp(`catch\\s*\\(${m[1]}\\)`)
    //Ищем вверх до начала catch: проверка обязана быть ВНУТРИ того же catch.
    for (let j = i; j >= Math.max(0, i - 12); j--) {
      if (guard.test(lines[j])) return
      if (start.test(lines[j])) break
    }
    bad.push(i + 1)
  })
  return bad
}

test('isStaleSession узнаёт только помеченный отказ', () => {
  assert.equal(isStaleSession({ stale: true }), true)
  assert.equal(isStaleSession(new Error('Network Error')), false)
  assert.equal(isStaleSession(undefined), false)
})

test('каждая офлайн-ветка сначала отбрасывает отказ прежней сессии', () => {
  const root = new URL('../src/', import.meta.url)
  const found = []
  for (const p of sources(root.pathname.replace(/^\/([A-Za-z]:)/, '$1'))) {
    if (p.endsWith('client.js')) continue
    const bad = unguardedOfflineBranches(readFileSync(p, 'utf8'))
    if (bad.length) found.push(`${p}: ${bad.join(', ')}`)
  }
  assert.deepEqual(found, [], 'офлайн-ветка без isStaleSession: ' + found.join('; '))
})

test('обратный ход: офлайн-ветка без проверки находится', () => {
  const src = `try { await x() } catch (e) {\n  if (!e?.response) { enqueueGrade(g) }\n}`
  assert.deepEqual(unguardedOfflineBranches(src), [2])
  const other = `try { await x() } catch (err) {\n  if (!err.response) { enqueueGrade(g) }\n}`
  assert.deepEqual(unguardedOfflineBranches(other), [2], 'другое имя переменной не спасает')
  const ok =`try { await x() } catch (e) {\n  if (isStaleSession(e)) return\n  if (!e?.response) { enqueueGrade(g) }\n}`
  assert.deepEqual(unguardedOfflineBranches(ok), [])
})
