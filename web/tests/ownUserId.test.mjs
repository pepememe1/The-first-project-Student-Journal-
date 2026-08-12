/**
 * ownUserId.test.mjs — сторож против «клиент спросил свой id у auth».
 *
 * ━━ ЗАЧЕМ ━━
 * «Визитка», которую стор авторизации кладёт после входа, состоит из ЛОГИНА, РОЛИ и
 * ФИО — id пользователя в ней нет и никогда не было (сервер отдаёт его только в
 * /me/prefs и в составе беседы). Прочитать `auth.user.id` синтаксически можно, ошибки
 * не будет — получится `undefined`, тихо превращающийся в пустую строку.
 *
 * Так уже случилось: карточка профиля брала свой id именно оттуда, подставляла пустую
 * строку в путь `/messenger/users/{id}/note` и молча не отправляла запрос. Со стороны
 * это выглядело как «кнопка „Сохранить“ не работает» — заметка про себя не сохранялась
 * вообще, при том что и сервер, и его тесты были исправны. Ошибка этого класса не
 * ловится ни сборкой, ни линтером, ни серверными тестами: неправильно здесь не то, ЧТО
 * написано, а то, что источник пуст.
 *
 * ⚠️ Проверка узкая НАМЕРЕННО — одно конкретное чтение одного конкретного поля. Свой id
 * берётся из стора профиля (`profile.userId`), и пока это так, сторож молчит.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(fileURLToPath(new URL('../src', import.meta.url)))

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (/\.(vue|js)$/.test(name)) out.push(p)
  }
  return out
}

// `auth.user?.id`, `auth.user.id`, `authStore.user.id` — но НЕ `auth.user?.login` и не
// чужие id (`peer.id`, `msg.sender_id`): ловим ровно обращение к id внутри визитки.
const BAD = /\bauth(?:Store)?\.user\s*\??\.\s*id\b/

// ⚠️ Строки-комментарии пропускаем. Первый же прогон споткнулся о ПОЯСНЕНИЕ к этой самой
// починке («карточка читала auth.user?.id») — то есть сторож обвинил текст, объясняющий,
// почему так делать нельзя. Разбирать JS целиком ради этого не нужно: достаточно не
// считать нарушением строку, которая целиком является комментарием.
const COMMENT = /^\s*(?:\/\/|\/?\*)/

function offenders(text) {
  return text.split('\n')
    .map((line, i) => ({ line: i + 1, text: line }))
    .filter(({ text: t }) => !COMMENT.test(t) && BAD.test(t))
}

test('свой id не берут из «визитки» auth — там его нет', () => {
  const bad = []
  for (const file of walk(SRC)) {
    for (const hit of offenders(readFileSync(file, 'utf8'))) {
      bad.push(`${relative(SRC, file)}:${hit.line} — ${hit.text.trim()}`)
    }
  }
  assert.deepEqual(bad, [],
    'auth.user содержит login/role/name и НЕ содержит id: чтение даст пустую строку и '
    + 'запрос по пути /users/{id}/… уйдёт в никуда. Свой id — profile.userId (/me/prefs).')
})

// ⚠️ Обратная проверка. Без неё сторож нельзя отличить от сломанного: правило, которое
// не срабатывает ни на чём, выглядит ровно так же, как правило, которое всё пропускает.
// Строка ниже — дословно та, что стояла в карточке профиля и стоила живого бага.
test('правило срабатывает на разметке, которая и вызвала баг', () => {
  const real = "      id: auth.user?.id || '', full_name: auth.user?.name || '',"
  assert.equal(offenders(real).length, 1)
  // …и молчит на соседних, законных обращениях к той же визитке и к ЧУЖИМ id.
  const ok = [
    "const login = computed(() => (auth.user?.login || '').trim())",
    "const myUserId = computed(() => profile.userId)",
    "map[p.user_id] = p",
    "if (activePeer.value?.id) map[activePeer.value.id] = activePeer.value",
    "// раньше карточка читала auth.user?.id — это и был баг (пояснение, а не код)",
  ]
  assert.deepEqual(ok.flatMap(offenders), [])
})
