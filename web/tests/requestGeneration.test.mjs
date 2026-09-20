// requestGeneration.test.mjs — у каждой независимой загрузки своё поколение запросов
// (находка ревью U01, 18.09.2026; починено 20.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// На публичном расписании ОДИН счётчик обслуживал ДВЕ независимые операции: расписание
// группы и список групп. При открытии страницы они стартуют подряд — список забирал
// следующий номер, ответ расписания приходил с прежним и объявлялся устаревшим. Данные
// выбрасывались, а `loading` не снимался: в `finally` стояла та же сверка. Страница
// ВЕЧНО крутила загрузку, и ровно у тех, кто пришёл по прямой ссылке с группой или с
// запомненным выбором, то есть у большинства.
//
// ⚠️ Проверяется И правило (фабрика), И его применение на странице. Одной фабрики мало:
// она была бы безупречной и при единственном экземпляре на две операции — то есть при
// исходном дефекте.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: свести обе операции страницы к одному генератору — краснеет
// последний тест; сделать `isCurrent` всегда истинной — краснеют первый и третий.
//
// ⚠️ И сразу честная граница, выясненная тем же обратным ходом: замена `===` на `>=`
// внутри `isCurrent` НЕ краснеет ни на одном тесте, и заводить под неё случай не за чем —
// токенов «из будущего» не бывает по построению (номер выдаёт тот же генератор). Пишу это
// прямо, чтобы следующий читатель не считал такой обратный ход проверенным.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { makeRequestGeneration } from '../src/utils/requestGeneration.js'

test('свежий запрос отменяет предыдущий в ТОЙ ЖЕ операции', () => {
  const req = makeRequestGeneration()
  const first = req.next()
  const second = req.next()
  assert.equal(req.isCurrent(first), false, 'устаревший ответ признан актуальным')
  assert.equal(req.isCurrent(second), true)
})

test('разные операции не отменяют друг друга', () => {
  const sched = makeRequestGeneration()
  const groups = makeRequestGeneration()
  const mySched = sched.next()
  groups.next()               //список групп стартовал следом — так и бывает при открытии
  assert.equal(sched.isCurrent(mySched), true,
    'соседняя загрузка объявила ответ расписания устаревшим — экран останется в загрузке')
})

test('один генератор на две операции — это и есть исходный дефект', () => {
  //Тест-объяснение: показывает, ЧТО именно ломалось, чтобы следующий читатель не
  //«упростил» страницу обратно к одному счётчику.
  const shared = makeRequestGeneration()
  const mySched = shared.next()
  shared.next()
  assert.equal(shared.isCurrent(mySched), false)
})

test('страница публичного расписания держит ДВА независимых генератора', () => {
  const src = readFileSync(new URL('../src/pages/PublicSchedule.vue', import.meta.url), 'utf8')
    //Комментарии вырезаем: они объясняют дефект и содержат его дословный вид, а разбор,
    //считающий пояснение кодом, краснел бы на исправном файле.
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '')

  const made = [...src.matchAll(/const\s+(\w+)\s*=\s*makeRequestGeneration\(\)/g)].map((m) => m[1])
  assert.equal(made.length, 2,
    `ожидались два генератора (расписание и список групп), найдено: ${made.join(', ') || 'ни одного'}`)

  //И они принадлежат РАЗНЫМ функциям, а не лежат оба в одной.
  const body = (name) => {
    const at = src.indexOf(`async function ${name}(`)
    assert.ok(at >= 0, `функция ${name} не найдена — сторож устарел вместе со страницей`)
    const next = src.indexOf('\nasync function ', at + 1)
    return src.slice(at, next < 0 ? src.length : next)
  }
  const usedIn = (name) => made.filter((g) => body(name).includes(`${g}.next()`))
  const inSchedule = usedIn('load')
  const inGroups = usedIn('loadGroupsList')
  assert.equal(inSchedule.length, 1, `расписание берёт номер у ${inSchedule.length} генераторов`)
  assert.equal(inGroups.length, 1, `список групп берёт номер у ${inGroups.length} генераторов`)
  assert.notEqual(inSchedule[0], inGroups[0],
    'расписание и список групп снова делят один генератор — страница зависнет в загрузке')
})
