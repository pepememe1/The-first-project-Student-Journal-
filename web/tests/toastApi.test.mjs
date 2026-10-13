/**
 * toastApi.test.mjs — всплывающие сообщения: метод существует, и текст успевают прочитать
 * (13.10.2026).
 *
 * 🔥 ЧТО СЛУЧИЛОСЬ. Одиннадцать мест звали `toast.show(...)`, а у `useToast()` такого
 * метода не было НИКОГДА: только `success`, `error`, `info`. Вызов падал с TypeError.
 * В форме модераторов это ловил тот же `catch`, что и отказ сервера: модератор ЗАВЕДЁН, а
 * форма пишет «Не удалось сохранить». В мессенджере «Заблокирован» не показывалось вовсе,
 * хотя комментарий рядом требовал «молчать нельзя ни в успехе, ни в отказе».
 * Ни сборка, ни линтер этого не видят: `toast` — обычный объект, метод ищется на ходу.
 *
 * Поэтому проверяется СВОЙСТВО по всему `src`: каждый `toast.<имя>(` обязан быть методом,
 * который `useToast()` действительно возвращает.
 * ⚠️ ОБРАТНЫЙ ХОД: `unknownCalls` натравливается на строку с выдуманным методом.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { useToast, toastDuration, toasts, dismissToast } from '../src/composables/useToast.js'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, acc)
    else if (/\.(vue|js)$/.test(name)) acc.push(full)
  }
  return acc
}

const API = new Set(Object.keys(useToast()))

/** Вызовы `toast.<имя>(`, которых нет среди методов. */
function unknownCalls(text, api = API) {
  return [...text.matchAll(/\btoast\.([A-Za-z_]+)\(/g)].map((m) => m[1]).filter((n) => !api.has(n))
}

test('каждый вызов toast.<метод>() существует', () => {
  const bad = []
  for (const file of walk(SRC)) {
    const hits = unknownCalls(readFileSync(file, 'utf8'))
    if (hits.length) bad.push(`${file.slice(SRC.length)}: ${[...new Set(hits)].join(', ')}`)
  }
  assert.deepEqual(bad, [], `вызовы несуществующих методов:\n${bad.join('\n')}`)
})

test('обратный ход: выдуманный метод проверка находит', () => {
  assert.deepEqual(unknownCalls("toast.notify('x'); toast.error('y')"), ['notify'])
  // Именно так выглядел дефект: без `show` среди методов вызов считался бы ошибкой.
  assert.deepEqual(unknownCalls("toast.show('Модератор заведён')", new Set(['success', 'error', 'info'])), ['show'])
})

test('сообщения об исходе названы по исходу, а не нейтрально', () => {
  //После починки `show` остался рабочим, но успех и отказ обязаны различаться цветом и
  //чтением с экрана (у ошибки role="alert"): в продукте нейтральных `show` быть не должно.
  const left = walk(SRC)
    .filter((f) => !f.replace(/\\/g, '/').endsWith('composables/useToast.js'))
    .filter((f) => /\btoast\.show\(/.test(readFileSync(f, 'utf8')))
    .map((f) => f.slice(SRC.length))
  assert.deepEqual(left, [])
})

test('ошибку держим дольше успеха, длинный текст — дольше короткого', () => {
  const short = 'Сохранено'
  const long = 'Не удалось сохранить: итоговая оценка уже выставлена — снимите её в окне аттестации, чтобы открыть семестр.'
  assert.ok(toastDuration('error', short) > toastDuration('success', short))
  assert.ok(toastDuration('error', long) > toastDuration('error', short))
  assert.ok(toastDuration('error', short) >= 8000, 'короткая ошибка гаснет раньше восьми секунд')
  assert.ok(toastDuration('success', short) >= 4000)
  //Длинную ошибку успевает прочитать и тот, кто читает десять знаков в секунду.
  assert.ok(toastDuration('error', long) >= long.length * 100)
  //…но навсегда на экране не остаётся ничего.
  assert.equal(toastDuration('error', 'я'.repeat(5000)), 30000)
})

test('показанное сообщение можно убрать, и таймер за ним не остаётся', () => {
  const id = useToast().info('проверка')
  assert.ok(toasts.some((t) => t.id === id))
  dismissToast(id)
  assert.ok(!toasts.some((t) => t.id === id))
  dismissToast(id)        //повторное снятие не падает
})
