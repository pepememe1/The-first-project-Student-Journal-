/**
 * haptics.test.mjs — ТАКТИЛЬНАЯ ОТДАЧА: правила, а не список вызовов.
 *
 * ━━ ЧТО ЗДЕСЬ ЗАЩИЩАЕТСЯ ━━
 * У этой функции главный риск не «сломается», а «расползётся»: вибрацию удобно повесить
 * на любую кнопку, каждый такой вызов по отдельности выглядит безобидно, а вместе они
 * превращают телефон в дёргающийся кирпич и жгут батарею (вибромотор тратит заметно
 * больше экрана). Поэтому тест следит за ДИСЦИПЛИНОЙ: сколько всего мест, и не появилась
 * ли отдача там, где палец и так всё видит.
 *
 * ⚠️ Порог намеренно НЕ «сколько сейчас», а с запасом: тест не должен краснеть на каждом
 * законном добавлении, иначе его начнут «просто обновлять» — то есть ровно то, от чего он
 * защищает (наш урок про сторожа со снимком значения).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|js)$/.test(name)) out.push(p)
  }
  return out
}

/** Файл без комментариев: пояснения про отдачу не должны считаться её вызовами. */
function code(path) {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/<!--[\s\S]*?-->/g, '')
}

const FILES = walk(SRC).filter((p) => !p.endsWith('utils\\haptics.js') && !p.endsWith('utils/haptics.js'))

function callSites() {
  const hits = []
  for (const p of FILES) {
    const src = code(p)
    for (const m of src.matchAll(/haptics\.(tap|success|error|alert)\s*\(/g)) {
      hits.push({ file: p.slice(SRC.length), kind: m[1] })
    }
  }
  return hits
}

test('отдача не расползлась по интерфейсу', () => {
  const hits = callSites()
  //Запас есть, но не бесконечный: два десятка мест — это уже «на каждый чих».
  assert.ok(
    hits.length <= 20,
    `мест с вибрацией стало ${hits.length}. Это не «отзывчиво», а раздражение и расход ` +
      `батареи. Критерий в haptics.js: палец действует вслепую ИЛИ действие значимо. ` +
      `Список: ${hits.map((h) => `${h.file}:${h.kind}`).join(', ')}`,
  )
})

test('отдача не висит на навигации и прокрутке', () => {
  //Самый частый способ испортить ощущение — вибрация на переходах и скролле.
  const forbidden = [/router\.(push|replace)[^\n]*haptics\./, /scroll[^\n]*haptics\./i]
  for (const p of FILES) {
    const src = code(p)
    for (const re of forbidden) {
      assert.ok(!re.test(src), `${p.slice(SRC.length)}: вибрация на навигации/прокрутке`)
    }
  }
})

test('успех и отказ различимы на ощупь, а не длительностью', () => {
  //Если оба узора — одиночные импульсы, вслепую их не различить, и вся затея теряет смысл.
  const src = readFileSync(new URL('../src/utils/haptics.js', import.meta.url), 'utf8')
  const success = src.match(/success:\s*(\d+)/)
  const error = src.match(/error:\s*\[([^\]]+)\]/)
  assert.ok(success, 'узор успеха пропал')
  assert.ok(error, 'узор отказа перестал быть РИТМОМ — вслепую его не отличить от успеха')
  assert.ok(Number(success[1]) <= 40, 'подтверждение длиннее 40 мс читается как «дёрнулся телефон»')
})

test('системное «уменьшить движение» сильнее нашего тумблера', () => {
  const src = readFileSync(new URL('../src/utils/haptics.js', import.meta.url), 'utf8')
  assert.match(
    src,
    /prefers-reduced-motion/,
    'вибрация игнорирует системную просьбу уменьшить движение — а её включают в том числе ' +
      'при вестибулярных расстройствах, где тряска это не «эффект», а плохое самочувствие',
  )
})

test('вибрация переживает заблокированное хранилище', () => {
  //Приватный режим и политики браузера бросают на localStorage. Настройка отдачи —
  //не тот случай, ради которого можно уронить экран.
  const src = readFileSync(new URL('../src/utils/haptics.js', import.meta.url), 'utf8')
  const reads = src.match(/localStorage\.(getItem|setItem)/g) || []
  const guards = src.match(/try\s*\{/g) || []
  assert.ok(reads.length > 0, 'настройка перестала сохраняться')
  assert.ok(guards.length >= reads.length, 'обращение к localStorage без try — упадёт в приватном режиме')
})
