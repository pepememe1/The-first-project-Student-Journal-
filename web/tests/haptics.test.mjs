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

// ─────────────────────────────────────────────────────────────────────────────────
// ГДЕ РАЗДЕЛ «ВИБРАЦИЯ» ВООБЩЕ ПОКАЗЫВАЕТСЯ (правка 02.09.2026, жалоба Ярослава)
//
// 🔥 Дефект, ради которого заведены проверки ниже, был не в вибрации, а в ПРИЗНАКЕ её
// наличия: `typeof navigator.vibrate === 'function'` истинно на настольном Chrome и
// Firefox — метод объявлен, вызывается без ошибки, возвращает true и не делает ничего.
// То есть признак описывал поддержку API браузером, а не наличие вибромотора, и раздел
// с РАБОЧИМ тумблером показывался в десктопной программе и в браузере на компьютере.
// Настройка, которую можно включить и которая заведомо не сработает, — тот же класс,
// что переводчик без установленных моделей: продукт притворяется, что умеет.
//
// ⚠️ Проверяем ПОВЕДЕНИЕ функции на подставленном окружении, а не текст файла: текстовая
// проверка зеленела бы от одного присутствия слова `pointer: coarse` в комментарии.
// ─────────────────────────────────────────────────────────────────────────────────
import { supported } from '../src/utils/haptics.js'

/** Подставить окружение «устройство такое-то» и вернуть вердикт supported(). */
function verdict({ vibrate = true, touch = 1, coarse = true }) {
  const saved = { nav: globalThis.navigator, win: globalThis.window }
  Object.defineProperty(globalThis, 'navigator', {
    value: { maxTouchPoints: touch, ...(vibrate ? { vibrate: () => true } : {}) },
    configurable: true, writable: true,
  })
  globalThis.window = { matchMedia: (q) => ({ matches: q.includes('coarse') ? coarse : false }) }
  try {
    return supported()
  } finally {
    Object.defineProperty(globalThis, 'navigator', { value: saved.nav, configurable: true, writable: true })
    globalThis.window = saved.win
  }
}

test('телефон: раздел вибрации показывается', () => {
  assert.equal(verdict({ vibrate: true, touch: 5, coarse: true }), true,
    'на телефоне вибрация есть, а раздел спрятался — человек не сможет её выключить')
})

test('обратный ход: настольный браузер с объявленным navigator.vibrate НЕ считается умеющим', () => {
  // Дословно то состояние, в котором дефект и жил: метод есть, сенсора нет, указатель точный.
  assert.equal(verdict({ vibrate: true, touch: 0, coarse: false }), false,
    'настольный Chrome снова сочтён вибрирующим — вернулся тумблер несуществующей функции ' +
    'на компьютере (жалоба Ярослава 02.09.2026)')
})

test('ноутбук с сенсорным экраном тоже не показывает раздел', () => {
  // maxTouchPoints > 0, но основной указатель — мышь. Одного сенсора мало.
  assert.equal(verdict({ vibrate: true, touch: 10, coarse: false }), false,
    'сенсорный ноутбук сочтён телефоном — признак снова опирается на один сигнал из трёх')
})

test('без самого метода вибрации раздела нет никогда', () => {
  assert.equal(verdict({ vibrate: false, touch: 5, coarse: true }), false)
})

test('карточка и пункт рельса гаснут по ОДНОМУ условию', () => {
  /*
   * 🔥 Наш обычный тихий отказ: спрятали карточку, а пункт в списке слева оставили —
   * человек нажимает «Вибрация» и попадает в пустую категорию. Ни ошибки, ни следа.
   * Поэтому условие должно быть одно и то же в обоих местах.
   */
  const settings = readFileSync(new URL('../src/pages/Settings.vue', import.meta.url), 'utf8')
  assert.match(settings, /<Card v-if="hapticsSupported"\s*\n\s*id="set-haptics"/,
    'карточка вибрации показывается безусловно — на компьютере вернулся раздел-пустышка')
  assert.match(settings, /catsForRole\(auth\.role,\s*\{\s*haptics:\s*hapticsSupported\s*\}\)/,
    'рельс настроек больше не знает про способности устройства — пункт «Вибрация» ' +
    'останется на компьютере и откроет пустую категорию')

  const cfg = readFileSync(new URL('../src/config/settingsSections.js', import.meta.url), 'utf8')
  assert.match(cfg, /\{ id: 'haptics',[^}]*device: 'haptics'[^}]*\}/,
    'у подкатегории вибрации пропал признак device — отбор по устройству перестал её видеть')
  assert.match(cfg, /caps\[s\.device\] === true/,
    'отбор подкатегорий по способностям устройства исчез из catsForRole')
})
