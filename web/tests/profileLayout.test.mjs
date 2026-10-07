/**
 * profileLayout.test.mjs — редактор профиля в настройках не уезжает за край окна (06.10.2026).
 *
 * ━━ ЗАЧЕМ ━━
 * Снимок Ярослава: «Настройки → Профиль» на ПК, живая карточка справа обрезана, внизу
 * окна горизонтальная полоса прокрутки. Причин было две, и вторая пережила первую починку:
 *   1) окно настроек было не шире 1024 px — увеличено 05.10;
 *   2) сетка редактора была `lg:grid-cols-[280px_1fr]`. Голое `1fr` — это
 *      `minmax(auto, 1fr)`: столбец не может стать уже самого широкого НЕРАЗРЫВНОГО куска
 *      внутри. Таким куском было ФИО (`truncate` — одна строка без переноса), и у длинного
 *      имени столбец распирало до предела карточки (608 px): на окне 1160 px — 56 лишних
 *      пикселей, на 1024 — 192.
 *
 * ⚠️ На стенде дефект НЕ ВИДЕН: «Семёнова Анна Петровна» помещается, «Овсянкина
 * Александра Иннокентьевна» — нет. Ни сборка, ни линтер, ни снимок экрана с коротким
 * именем его не ловят, поэтому свойство закреплено текстом.
 *
 * ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `lg:grid-cols-[280px_1fr]` — краснеет первый тест;
 * вернуть имени `truncate` — краснеет второй. Плюс самопроверка разбора в конце файла.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

/** Дорожки вида «голое Nfr» в произвольных шаблонах сетки одной строки классов. */
function bareFrTracks(classString) {
  const bad = []
  for (const m of classString.matchAll(/(?:^|\s)((?:[a-z0-9]+:)*grid-cols-\[([^\]]+)\])/g)) {
    // Дорожки разделены подчёркиванием, но ВНУТРИ скобок minmax(…) его нет — делим по
    // подчёркиванию и склеиваем то, что оказалось внутри незакрытой скобки.
    const tracks = []
    let depth = 0
    let cur = ''
    for (const ch of m[2]) {
      if (ch === '(') depth += 1
      if (ch === ')') depth -= 1
      if (ch === '_' && depth === 0) { tracks.push(cur); cur = '' } else cur += ch
    }
    tracks.push(cur)
    if (tracks.some((t) => /^\d*\.?\d+fr$/.test(t))) bad.push(m[1])
  }
  return bad
}

/** Строка классов сетки, в которой лежат редактор и живая карточка профиля. */
function profileGridClasses(text) {
  // Это та сетка, у которой с `lg` первый столбец — колонка редактора в 280 px.
  const m = /<div class="([^"]*\blg:grid-cols-\[280px_[^"]*)"/.exec(text)
  return m ? m[1] : null
}

test('у сетки редактора профиля нет столбца, который не умеет сжиматься', () => {
  const cls = profileGridClasses(read('pages/Profile.vue'))
  assert.ok(cls, 'сетка редактора профиля не найдена — разбор устарел, проверь Profile.vue')
  assert.deepEqual(bareFrTracks(cls), [],
    'голое `1fr` = minmax(auto,1fr): длинное ФИО распирает столбец, карточка уезжает за край окна')
})

test('ФИО в карточке профиля переносится, а не режется многоточием', () => {
  const card = read('components/messenger/PeerProfileCard.vue')
  const m = /<p class="([^"]*)" v-bind="nameDecoration">/.exec(card)
  assert.ok(m, 'строка с именем в PeerProfileCard.vue не найдена — разбор устарел')
  const tokens = m[1].split(/\s+/)
  assert.ok(!tokens.includes('truncate'),
    'имя снова в одну строку: в профиле «Овсянкина Александра Иннокентьеві…» хуже второй строки')
  assert.ok(tokens.includes('break-words'), 'имени не разрешён перенос длинного слова')
})

test('самопроверка: разбор видит дословную форму дефекта и не ругается на починенную', () => {
  // Сторож, зелёный и без починки, неотличим от исправного кода.
  const before = 'grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr] xl:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]'
  const after = 'grid grid-cols-1 gap-5 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]'
  assert.deepEqual(bareFrTracks(before), ['lg:grid-cols-[280px_1fr]'])
  assert.deepEqual(bareFrTracks(after), [])
  // Дробные и кратные доли — та же беда; minmax с запятой внутри — не дорожка `fr`.
  assert.deepEqual(bareFrTracks('grid-cols-[2fr_1.5fr]'), ['grid-cols-[2fr_1.5fr]'])
  assert.deepEqual(bareFrTracks('md:grid-cols-[minmax(0,2fr)_auto_minmax(0,1fr)]'), [])
  assert.equal(profileGridClasses('<div class="grid lg:grid-cols-[280px_1fr]">'), 'grid lg:grid-cols-[280px_1fr]')
})
