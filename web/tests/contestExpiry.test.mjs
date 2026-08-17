// contestExpiry.test.mjs — у истечения вопроса соревнования ОБЯЗАН быть толкающий.
//
// 🔥 Зачем такой странный тест. Сервер подметает истёкшее при обращении к API — своего
// таймера у него нет (фоновый планировщик на одноядерном VPS не заводим). У тайм-бокса
// толчок был, а у соревнования его не было ВООБЩЕ: отсчёт доходил до нуля, и всё
// замирало — ни следующего вопроса, ни завершения. Серверные тесты при этом были
// зелёными: они дёргали `/running` руками, то есть проверяли подметание, а не то, что
// его кто-то вызывает в продукте.
//
// Проверяем ФАКТ вызова в коде плеера, а не поведение: поведение покрыто на сервере.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// ⚠️ fileURLToPath, а не new URL().pathname: на Windows тот даёт «/C:/…», и join
// склеивает «C:\C:\…» — обход падает и тест молча не проверяет ничего (эта грабля в
// проекте уже была со сторожем вёрстки).
const here = dirname(fileURLToPath(import.meta.url))
const player = readFileSync(join(here, '..', 'src', 'components', 'activity', 'quiz',
                                 'QuizPlayer.vue'), 'utf8')

test('истечение времени вопроса толкает сервер', () => {
  const watcher = player.match(/watch\(qLeft[\s\S]{0,900}?\n\}\)/)
  assert.ok(watcher, 'нет наблюдателя за отсчётом вопроса — истечение никто не заметит')
  assert.match(watcher[0], /refreshRunning/,
    'наблюдатель есть, но сервер он не толкает: подметание истёкшего не запустится, ' +
    'и соревнование замрёт на нуле')
})

test('ведущий толкает сразу, участники — с задержкой', () => {
  const watcher = player.match(/watch\(qLeft[\s\S]{0,900}?\n\}\)/)[0]
  assert.match(watcher, /isHost\s*\?\s*0\s*:/,
    'без разной задержки тридцать участников ударят по серверу в одну секунду')
})
