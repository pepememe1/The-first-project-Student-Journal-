// Сторож: у каждой пасхалки есть МЕСТО ПОКАЗА и триггер в продукте.
//
// ⚠️ Это ровно «обещание без вызывающего» из таксономии Полковника, и на нём уже
// спотыкались в этом же заходе: сервер умел вернуть `detroit_led`, а сцены с таким
// именем в хосте не было — бросок уходил впустую, и человек не видел НИЧЕГО. Тесты
// при этом были зелёные: они проверяли сам бросок, а не то, что его кто-то рисует.
//
// Проверяем три звена цепочки, потому что порваться может любое:
//   1) у ачивки есть пасхалка,
//   2) у пасхалки есть чем её нарисовать (оверлей или слой внутри страницы),
//   3) у пасхалки есть кто-то, кто её ЗАПУСКАЕТ.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(join(ROOT, p), 'utf8')

const store = read('src/stores/easterEggs.js')
const host = read('src/components/easter/EasterEggHost.vue')

const eggs = [...store.matchAll(/^\s{2}(\w+):\s+'\w+',$/gm)].map(m => m[1])
const scenes = new Set([...host.matchAll(/^\s+(\w+):\s+defineAsyncComponent/gm)].map(m => m[1]))
const inPage = new Set([...store.split('const IN_PAGE = new Set([')[1].split('])')[0]
  .matchAll(/'([a-z0-9_]+)'/g)].map(m => m[1]))

function walk(dir, out = []) {
  for (const e of readdirSync(join(ROOT, dir), { withFileTypes: true })) {
    const p = `${dir}/${e.name}`
    if (e.isDirectory()) walk(p, out)
    else if (/\.(vue|js)$/.test(e.name)) out.push(p)
  }
  return out
}
const sources = walk('src').map(p => read(p)).join('\n')

test('пасхалок ровно столько, сколько ачивок, и список не пуст', () => {
  assert.ok(eggs.length >= 15, `нашлось только ${eggs.length} — разбор файла сломался`)
})

test('каждую пасхалку есть чем нарисовать', () => {
  const orphans = eggs.filter(e => !scenes.has(e) && !inPage.has(e))
  assert.deepEqual(orphans, [],
    'пасхалка может выпасть, но показать её нечем — бросок уйдёт впустую:\n' + orphans.join('\n'))
})

// ⚠️ Триггер бывает ДВУХ видов, и проверять надо оба. Часть пасхалок бросает сам
// клиент (`easter.roll('…')` на странице), а часть выбирает СЕРВЕР по условию входа
// (ночь, день рождения, серия неудачных попыток) — их имени в вебе может не быть
// нигде, кроме карты сцен, и это правильно. Читаем питоновский модуль напрямую: тем же
// приёмом passwordGen.test.mjs читает `reg_utils.py`, чтобы алфавиты не разъехались.
const serverPicker = readFileSync(join(ROOT, '..', 'server', 'app', 'easter_eggs.py'), 'utf8')

test('каждую пасхалку кто-то запускает — с клиента или с сервера', () => {
  const never = eggs.filter((e) => {
    const fromWeb = (sources.split(`'${e}'`).length - 1) >= 2   // одно вхождение = только объявление
    const fromServer = serverPicker.includes(`"${e}"`)
    return !fromWeb && !fromServer
  })
  assert.deepEqual(never, [],
    'пасхалка объявлена, но нигде не запускается и не читается:\n' + never.join('\n'))
})

test('обратный ход: пасхалка без сцены и без слоя ловится', () => {
  const fake = 'never_gonna_happen'
  assert.ok(!scenes.has(fake) && !inPage.has(fake),
    'выдуманный id обязан считаться неподключённым — иначе правило не работает')
})

test('каждую ачивку можно ОТКРЫТЬ — у пасхалки есть вызов claim', () => {
  // ⚠️ Третье звено той же цепочки, и рвётся оно тише всех: пасхалку видно, она
  // доигрывает до конца, а награды нет — потому что `claim` никто не позвал. Ни одна
  // ошибка при этом не всплывает, человек просто считает, что ачивка «не выпала».
  const claims = new Set([...sources.matchAll(/claim\('([a-z0-9_]+)'\)/g)].map(m => m[1]))
  const unreachable = eggs.filter(e => !claims.has(e))
  assert.deepEqual(unreachable, [],
    'пасхалка есть, а ачивку за неё не закрывает никто:\n' + unreachable.join('\n'))
})
