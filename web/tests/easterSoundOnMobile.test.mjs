/**
 * easterSoundOnMobile.test.mjs — звук пасхалок обязан быть слышен В ПРИЛОЖЕНИИ.
 *
 * ━━ ЧТО ЗДЕСЬ ОХРАНЯЕТСЯ ━━
 * `tools/pack_ota_bundle.py` НАМЕРЕННО не кладёт `easter/snd/` в OTA-бандл: звук весит
 * 4.2 МБ при бандле в 4.9, то есть удваивал бы каждое обновление «по воздуху». Решение
 * верное и остаётся. Следствие: в приложении этих файлов ВНУТРИ бандла нет.
 *
 * 🔥 А страница в приложении отдаётся локальным сервером Capacitor из бандла (origin
 * `https://localhost`). Значит абсолютный путь `/easter/snd/x.m4a` ведёт туда, откуда
 * файл вырезали, — 404. Молча: проигрывание всюду обёрнуто в `.catch(() => {})` (и
 * правильно, autoplay режут браузеры), поэтому в консоли пусто, сцена идёт как обычно,
 * просто беззвучно. Так пасхалки были немыми в опубликованном приложении, и заметить
 * это можно было только с телефона в руках.
 *
 * ⚠️ Рядом с кодом при этом стоял комментарий «качается с сайта» — обещание, которого в
 * коде не было НИЧЕМ подкреплено. Третий случай в проекте, когда комментарий описывал
 * намерение как факт. Поэтому проверка смотрит на КОД, а не на слова.
 *
 * Правило: адрес звука строит только `utils/easterAssetUrl.js::easterSound` — он и
 * подставляет боевой адрес в приложении. Прямой литерал в компоненте запрещён.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = new URL('../src', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const HELPER = join(SRC, 'utils', 'easterAssetUrl.js')

function sourceFiles(dir = SRC, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) sourceFiles(p, out)
    else if (name.endsWith('.vue') || name.endsWith('.js')) out.push(p)
  }
  return out
}

test('ни один компонент не берёт звук пасхалки прямым путём', () => {
  const плохие = []
  for (const file of sourceFiles()) {
    if (file === HELPER) continue          // сам помощник этот путь и собирает
    const text = readFileSync(file, 'utf8')
    text.split('\n').forEach((line, i) => {
      if (/['"`]\/easter\/snd\//.test(line)) плохие.push(`${relative(SRC, file)}:${i + 1}`)
    })
  }
  assert.deepEqual(плохие, [],
    `прямой путь к звуку пасхалки (${плохие.join(', ')}). В приложении этих файлов в ` +
    'бандле НЕТ (их вырезает pack_ota_bundle.py ради веса), а origin там — сам бандл: ' +
    'получится 404, и он будет ТИХИМ, потому что проигрывание обёрнуто в catch. ' +
    "Адрес обязан строить easterSound() из '@/utils/easterAssetUrl'.")
})

test('помощник действительно уводит звук на боевой адрес в приложении', () => {
  const t = readFileSync(HELPER, 'utf8')
  assert.match(t, /isNativeApp\s*\(\)/,
    'помощник не различает приложение и сайт — значит в приложении вернёт тот же ' +
    'путь в бандл, и чинить было нечего')
  assert.match(t, /getApiBase\s*\(\)/,
    'помощник не берёт адрес сервера: неоткуда взяться звуку в приложении')
})

test('обратный ход: проверка ловит дословно ту строку, что вызвала дефект', () => {
  // Как было в CyberpunkGlitch.vue до починки.
  const строка = "  const guitar = new Audio('/easter/snd/guitar.m4a')"
  assert.ok(/['"`]\/easter\/snd\//.test(строка),
    'строка, из-за которой пасхалки молчали в приложении, не опознаётся — ' +
    'сторож не сработает и на следующей такой же')
  // И обратное: правильный вызов не должен считаться нарушением.
  const цело = "  const guitar = new Audio(easterSound('guitar.m4a'))"
  assert.equal(/['"`]\/easter\/snd\//.test(цело), false,
    'правильный вызов помечен как нарушение — сторож будет краснеть на исправном коде')
})
