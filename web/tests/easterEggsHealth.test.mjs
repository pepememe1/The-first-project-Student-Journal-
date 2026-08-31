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
  // ⚠️ Расширение берём ИЗ САМОГО КОДА, а не держим здесь копию. Когда звук пасхалок
  // пережали (28.08.2026, .mp3/.mp4 → .m4a), захардкоженный «.mp3» покраснел не на
  // дефекте, а на законной правке — то есть сторож стал требовать вернуть старый формат.
  // Проверять надо СВЯЗЬ «что обещано в таблице ↔ что лежит на диске», а не формат.
  // ⚠️ Форма вызова сменилась 31.08.2026: путь больше не пишется литералом, его строит
  // `easterSound('narrator-' + key + '-' + n + '.m4a')` — иначе в приложении звук вёл бы
  // внутрь бандла, откуда его вырезает упаковщик (см. utils/easterAssetUrl.js). Ищем
  // расширение в ОБЕИХ формах: старая осталась в истории, а сторож не должен краснеть
  // от того, что вызов стал правильнее.
  const extMatch = src.match(/(?:'\/easter\/snd\/narrator-'|easterSound\('narrator-')[^\n]*?\+\s*'(\.[a-z0-9]+)'/)
  assert.ok(extMatch, 'не нашёл, каким расширением Stanley собирает имя файла')
  const ext = extMatch[1]
  const missing = []
  for (const [, count, key] of table) {
    for (let n = 1; n <= Number(count); n++) {
      const rel = `public/easter/snd/narrator-${key}-${n}${ext}`
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

test('обратный ход: правила ловят дефект на СИНТЕТИЧЕСКОМ файле', () => {
  // 🔥 Прежняя версия этого теста объявляла строку тут же и тут же сверяла её с
  // регуляркой — то есть проверяла сама себя и осталась бы зелёной, даже если бы сторож
  // выше деградировал до нуля проверок (нашёл Полковник). Настоящий обратный ход обязан
  // прогонять ПРАВИЛО по заведомо плохому входу и убеждаться, что оно его находит.
  //
  // Правила вынесены сюда как чистые функции от текста файла — ровно те же выражения,
  // что применяются выше к настоящим сценам.
  const findsBareListener = (src) =>
    /addEventListener\('loadedmetadata'/.test(src) && !src.includes('whenAudioReady')
  const findsAsset = (src) => [...src.matchAll(/['"(](\/easter\/[^'")\s]+)/g)]
    .map((m) => m[1])
    .filter((rel) => !existsSync(join(ROOT, 'public', rel)))

  const BAD = "audio.addEventListener('loadedmetadata', start, { once: true })\n"
    + "<img src=\"/easter/img/нет-такого.png\" />"
  const GOOD = "import { whenAudioReady } from '@/utils/audioReady'\n"
    + "cancelReady = whenAudioReady(audio, start)\n"
    + "<img src=\"/easter/img/d6.png\" />"

  assert.ok(findsBareListener(BAD), 'правило НЕ видит голый loadedmetadata — оно бесполезно')
  assert.ok(!findsBareListener(GOOD), 'правило ругается на исправный код')
  assert.deepEqual(findsAsset(BAD), ['/easter/img/нет-такого.png'],
    'правило НЕ видит ссылку на отсутствующий файл')
  assert.deepEqual(findsAsset(GOOD), [], 'правило ругается на существующий файл')
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

test('состояние из сети проверяется наблюдением, а не одноразовым if', () => {
  // 🔥 Этот дефект повторился ТРИЖДЫ подряд (штамп Papers Please, голос Disco Elysium,
  // счётчик ULTRAKILL) и каждый раз выглядел одинаково: пасхалка «выпала», стор про неё
  // знает, подтверждение при уходе честно про неё говорит — а на экране НЕТ НИЧЕГО.
  // Причина всегда одна: `onMounted` выполняется РАНЬШЕ, чем приходит ответ сервера,
  // и проверка `if (inPage.xxx)` в нём ложна всегда. Ни исключения, ни следа в консоли.
  const bad = []
  for (const f of files) {
    const src = read(f)
    const mounted = src.split('onMounted(')[1]
    if (!mounted) continue
    const body = mounted.split('\n})')[0]
    if (/\b(?:easter\.)?(?:inPage|armed)\.\w+/.test(body)) bad.push(f)
  }
  assert.deepEqual(bad, [],
    'в onMounted читается состояние, которое приходит по сети — оно там ещё пустое:\n'
    + bad.join('\n'))
})

test('пасхалка страницы прибирается за собой при уходе', () => {
  // Иначе флаг уезжает вместе с человеком на страницу, где показать его нечем, и
  // продукт спрашивает «на экране пасхалка» там, где её нет и быть не может.
  for (const f of ['JournalEggs.vue', 'ProfileEggs.vue']) {
    const src = read(f)
    assert.match(src, /onBeforeUnmount/, `${f}: нет уборки вовсе`)
    assert.match(src, /closeInPage/, `${f}: при уходе флаг не снимается`)
  }
})

test('сценарий Stanley по секундам соблюдён', () => {
  // Тайминги заданы Владом словами: «дёргается несколько секунд», «за 2 секунды до
  // речи становится 427», «речь на 15-й секунде». Числа связаны между собой, и правка
  // одного молча ломает договорённость — например, подмена цифры уезжает ПОСЛЕ начала
  // речи, и вся отсылка теряет смысл. Проверяем ОТНОШЕНИЯ, а не только значения.
  const src = read('StanleyNarrator.vue')
  const num = (name) => {
    const m = src.match(new RegExp(`const ${name} = (\\d+)`))
    assert.ok(m, `нет константы ${name} — тайминги снова разбросаны по коду`)
    return Number(m[1])
  }
  const shakeAt = num('SHAKE_AT'), shakeMs = num('SHAKE_MS')
  const switchAt = num('SWITCH_AT'), speechAt = num('SPEECH_AT')

  assert.ok(shakeAt <= 600, `первое движение через ${shakeAt} мс — человек уйдёт, не дождавшись`)
  assert.ok(shakeMs >= 2000, 'дрожь короче двух секунд не читается как «несколько секунд»')
  assert.equal(speechAt - switchAt, 2000, 'подмена цифры обязана быть ровно за 2 с до речи')
  assert.equal(speechAt, 15000, 'речь начинается на 15-й секунде')
  assert.ok(shakeAt + shakeMs < switchAt, 'дрожь обязана стихнуть ДО подмены цифры')
})

test('полноэкранная сцена перехватывает мышь, а не пропускает клики насквозь', () => {
  // 🔥 Правило Влада: сцена ведёт себя как окно про cookie — выйти мимо кнопок нельзя.
  // Раньше корневой слой был прозрачным для мыши, и промах мимо дерева попадал в кнопку
  // страницы ПОД сценой: страница уходила, находка исчезала. Так терялись ачивки у тех,
  // кто ловил дерево специально.
  //
  // ⚠️ Исключения ЯВНЫЕ и с причиной. G-Man лишь проявляется поверх работающего
  // интерфейса — запирать из-за него мышь нельзя; Far Cry и Stanley это подписи внизу
  // экрана входа и страницы 404, они обязаны пропускать клики к форме под ними.
  const TRANSPARENT_OK = new Set(['GmanWatcher.vue', 'FarCryQuote.vue', 'StanleyNarrator.vue'])
  const bad = []
  for (const f of files) {
    if (TRANSPARENT_OK.has(f)) continue
    const src = read(f)
    if (/class="[^"]*pointer-events-none[^"]*fixed inset-0/.test(src)) bad.push(f)
  }
  assert.deepEqual(bad, [],
    'сцена прозрачна для мыши — промах уносит находку:\n' + bad.join('\n'))
})

test('у дерева Делтарун выход открывается только после последней реплики', () => {
  // Прокликивая диалог, легко проскочить в проход и уйти, не получив ачивку. Поэтому
  // проход не существует, пока `wayOut` не поднят — а поднимается он в самом конце
  // `advance`, ПОСЛЕ выдачи ачивки.
  const src = read('DeltaruneTree.vue')
  assert.ok(!/aria-label="Закрыть"/.test(src),
    'вернулась кнопка «закрыть на весь экран» — один промах снова унесёт находку')
  // ⚠️ Условие ДВОЙНОЕ, и вторая половина куплена ошибкой: выход появлялся прямо во
  // время разговора, человек жал «дальше» по реплике, попадал в него и вылетал не
  // дочитав. Поэтому проверяем оба условия, а не дословную строку — правило важнее её
  // написания.
  assert.match(src, /v-if="wayOut && !started"/,
    'проход виден во время диалога — по нему промахнутся, прокликивая реплики')
  assert.match(src, /v-if="escapeShown && !wayOut && !started"/,
    'поздний выход виден во время диалога — та же ловушка')

  const adv = src.split('async function advance()')[1].split('\n}')[0]
  const claimAt = adv.indexOf("claim('deltarune_tree')")
  const wayAt = adv.indexOf('wayOut.value = true')
  assert.ok(claimAt >= 0 && wayAt >= 0, 'разбор advance() сломался')
  assert.ok(claimAt < wayAt, 'проход открывается РАНЬШЕ выдачи ачивки — её можно потерять')

  // И предохранитель: модальная сцена без объяснённого выхода — ловушка.
  assert.match(src, /escapeShown/, 'нет позднего выхода на случай, если человек не понял')
})

test('область клика по дереву совпадает с самой картинкой', () => {
  // 🔥 Хитбокс стоял отдельным блоком «внизу по центру» и с картинкой не совпадал:
  // человек жал туда, где дерево нарисовано, и не попадал. Область клика обязана
  // совпадать с тем, что видно, иначе это не секрет, а угадайка.
  const src = read('DeltaruneTree.vue')
  const btn = src.split('aria-label="Осмотреть дерево"')[1] || ''
  assert.ok(btn.includes('tree.gif'),
    'картинка дерева больше не внутри кнопки — хитбокс снова разъедется с ней')
  assert.ok(!/bottom-\[18%\]/.test(src),
    'вернулся отдельный прямоугольник-хитбокс вместо самой картинки')
})
