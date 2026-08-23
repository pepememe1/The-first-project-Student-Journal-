// Работоспособность пасхалок: проверки СВОЙСТВ, а не поведения отдельной сцены.
//
// ⚠️ Все три правила ниже куплены дефектами одного захода (23.08.2026), и у всех троих
// общая черта: ошибка НЕ ДАЁТ НИ ИСКЛЮЧЕНИЯ, НИ СТРОКИ В КОНСОЛИ. Код просто не
// выполняется, пасхалка «сработала» на сервере, шанс потрачен, а человек не увидел
// ничего. Ровно поэтому здесь нужны сторожа, а не «протестируем руками».
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const EASTER = join(ROOT, 'src/components/easter')
const files = readdirSync(EASTER).filter((f) => f.endsWith('.vue'))
const read = (f) => readFileSync(join(EASTER, f), 'utf8')

test('каждый ассет, на который ссылается сцена, лежит на диске', () => {
  // Тот же класс, что и «шрифт, которого нет»: путь есть, файла нет, браузер молчит.
  const missing = []
  for (const f of files) {
    const src = read(f)
    for (const m of src.matchAll(/['"(](\/easter\/[^'")\s]+)/g)) {
      // ⚠️ Имя, СОБИРАЕМОЕ строкой ('…/narrator-' + key + …), статически не проверить.
      // У таких ссылок свой сторож ниже — сверка таблицы озвучки с файлами. Молча
      // ругаться на них значит приучить читать этот тест по диагонали.
      if (/^\s*\+/.test(src.slice(m.index + m[0].length + 1))) continue
      if (!existsSync(join(ROOT, 'public', m[1]))) missing.push(`${f}: ${m[1]}`)
    }
  }
  assert.deepEqual(missing, [], 'сцена ссылается на несуществующий файл:\n' + missing.join('\n'))
})

test('таблица озвучки рассказчика совпадает с файлами на диске', () => {
  // Имя файла у Stanley СОБИРАЕТСЯ строкой ('narrator-' + key + '-' + n), поэтому
  // предыдущая проверка его не видит. Разъедется число — часть выпадений будет немой.
  const src = read('StanleyNarrator.vue')
  const table = [...src.matchAll(/\{\s*files:\s*(\d+),\s*key:\s*'(\w+)'/g)]
  assert.ok(table.length >= 3, 'разбор таблицы VARIANTS сломался')
  const missing = []
  for (const [, count, key] of table) {
    for (let n = 1; n <= Number(count); n++) {
      const rel = `public/easter/snd/narrator-${key}-${n}.mp3`
      if (!existsSync(join(ROOT, rel))) missing.push(rel)
    }
  }
  assert.deepEqual(missing, [], 'в таблице обещан файл озвучки, которого нет:\n' + missing.join('\n'))
  // И обратно: лишний файл на диске значит, что его никогда не выберут.
  const onDisk = readdirSync(join(ROOT, 'public/easter/snd')).filter((f) => f.startsWith('narrator-'))
  const promised = table.reduce((n, [, c]) => n + Number(c), 0)
  assert.equal(onDisk.length, promised,
    `на диске ${onDisk.length} файлов озвучки, в таблице обещано ${promised}`)
})

test('сценарий сцены не заводится ГОЛЫМ событием загрузки звука', () => {
  // 🔥 Дефект: Stanley и Far Cry раскладывали реплики по длительности mp3 и ждали
  // 'loadedmetadata'. Не доехал звук — событие не приходит НИКОГДА, и вместе с ним не
  // приходят ни реплики, ни claim, ни закрытие сцены.
  const bad = []
  for (const f of files) {
    const src = read(f)
    for (const m of src.matchAll(/addEventListener\('loadedmetadata'/g)) {
      // Допустим только внутри общего помощника — у него есть запасной срок.
      if (!src.includes('whenAudioReady')) bad.push(`${f} (позиция ${m.index})`)
    }
  }
  assert.deepEqual(bad, [],
    'сцена ждёт loadedmetadata без запасного срока — без звука она не закроется:\n' + bad.join('\n'))
  assert.match(readFileSync(join(ROOT, 'src/utils/audioReady.js'), 'utf8'), /setTimeout/,
    'у самого помощника обязан быть запасной таймер, иначе он ничего не решает')
})

test('у полноэкранной сцены есть предохранитель от залипания', () => {
  // Занятый слот `active` запрещает выпадать всем остальным пасхалкам до конца сессии.
  const store = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
  assert.match(store, /STUCK_MS/, 'предохранителя нет вовсе')
  assert.match(store, /clearTimeout\(stuckTimer\)/, 'предохранитель не снимается при закрытии')
})

test('обратный ход: несуществующий ассет и голый loadedmetadata ловятся', () => {
  assert.ok(!existsSync(join(ROOT, 'public/easter/img/нет-такого.png')),
    'проверка ассетов обязана опираться на реальное наличие файла')
  const fake = "audio.addEventListener('loadedmetadata', start, { once: true })"
  assert.match(fake, /addEventListener\('loadedmetadata'/,
    'правило обязано ловить дословную строку, из-за которой оно и заведено')
})

test('редкость есть у каждой ачивки и она из известной шкалы', () => {
  // ⚠️ Незнакомая ступень роняет карточку в профиле: код читает `RARITY[a.rarity].color`
  // и на опечатке падает на неопределённом. Ошибка при этом ВИДНА только тому, у кого
  // эта ачивка открыта, — то есть может доехать до боя незамеченной.
  const cfg = readFileSync(join(ROOT, 'src/config/achievements.js'), 'utf8')
  const tiers = new Set([...cfg.split('export const RARITY = {')[1].split('\n}')[0]
    .matchAll(/^\s{2}(\w+):/gm)].map(m => m[1]))
  assert.ok(tiers.size >= 3, 'разбор шкалы редкостей сломался')
  const bad = [...cfg.matchAll(/id: '(\w+)',[^\n]*?rarity: '(\w+)'/g)]
    .filter(m => !tiers.has(m[2]))
    .map(m => `${m[1]} → ${m[2]}`)
  assert.deepEqual(bad, [], 'ачивка с неизвестной редкостью:\n' + bad.join('\n'))
})

test('лестница редкостей не выродилась в одну ступень', () => {
  // Смысл шкалы в РАЗЛИЧИИ: если всё «обычное» или всё «легендарное», она ничего не
  // сообщает. Проверяем, что заняты и низ, и верх.
  const cfg = readFileSync(join(ROOT, 'src/config/achievements.js'), 'utf8')
  const used = new Set([...cfg.matchAll(/rarity: '(\w+)'/g)].map(m => m[1]))
  assert.ok(used.has('common'), 'нет ни одной обычной — «редкое» перестаёт быть редким')
  assert.ok(used.size >= 4, `занято всего ${used.size} ступеней из пяти`)
})
