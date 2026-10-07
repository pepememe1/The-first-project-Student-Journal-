// composerMirror.test.mjs — набранный текст обязан быть ВИДЕН.
//
// 🔥 РЕГРЕССИЯ, ДОЕХАВШАЯ ДО БОЯ (06.09.2026, жалоба Влада: «когда набираем текст, его
// вообще не видно»). Приглушение символов разметки сделано зеркалом: текст поля
// прозрачный, рисует его div под полем. Но у поля остался НЕПРОЗРАЧНЫЙ фон (`bg-card2`),
// и оно закрывало зеркало собой. Свой текст прозрачный, чужой перекрыт — видно ничего.
//
// ⚠️ Урок общий: делая элемент прозрачным, проверь, что под ним ВИДНО. Фон соседа — такая
// же преграда, как непрозрачный текст, и ни сборка, ни линтер, ни тесты этого не
// показывают. Здесь проверяется ровно связка, на которой сломалось.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/components/messenger/ChatThread.vue', import.meta.url), 'utf8')
const composerTag = src.match(/<textarea ref="composer"[\s\S]*?\/>/)?.[0] || ''
const styles = src.split('<style')[1] || ''

test('поле композера в разметке найдено', () => {
  assert.ok(composerTag, 'не нашли <textarea ref="composer"> — тест ослеп, чинить его')
})

test('у поля с ПРОЗРАЧНЫМ текстом не может быть непрозрачного фона', () => {
  // Ровно то, что сломалось: `color: transparent` + `bg-card2` = не видно ничего.
  assert.ok(/\.gb-composer-input[\s\S]*?color:\s*transparent/.test(styles),
    'текст поля больше не прозрачный — тогда зеркало рисует ВТОРУЮ копию текста поверх')
  const opaqueBg = composerTag.match(/\bbg-(card2?|bg2?|white|surface)\b/)
  assert.equal(opaqueBg, null,
    `у поля непрозрачный фон (${opaqueBg?.[0]}) — он закроет зеркало, и текста не будет видно`)
})

test('фон и рамку рисует ОБЁРТКА, а не поле', () => {
  // Иначе их некому нарисовать: поле обязано быть прозрачным, а зеркало лежит под ним.
  assert.ok(/gb-composer-wrap[^"]*"[^>]*?\bbg-card2\b/.test(src)
    || /class="gb-composer-wrap[^"]*bg-/.test(src),
    'обёртка композера потеряла фон — поле станет прозрачным окном в страницу')
  assert.ok(/\.gb-composer-wrap:focus-within/.test(styles),
    'без focus-within подсветка фокуса пропадёт: рамку рисует уже не поле')
})

test('зеркало и поле делят ОДИН класс раскладки', () => {
  // Разъедутся метрики — приглушённые символы съедут с настоящих, и это будет рябь.
  assert.ok(/ref="mirror"[\s\S]{0,400}gb-composer-box/.test(src), 'у зеркала нет общего класса')
  assert.ok(/gb-composer-box/.test(composerTag), 'у поля нет общего класса')
})

// ━━ ПОЛЕ РАСТЁТ С ТЕКСТОМ, А ПРОКРУТКА У ЗЕРКАЛА И ПОЛЯ ОДНА (05.10.2026) ━━━━━━━━━━━━━
// Две жалобы Ярослава с ПК, причина у обеих одна — зеркало и поле прокручивались и
// переносили строки по отдельности:
//   • «сообщение длиннее ячейки — идёт перенос, но вниз не пролистывается, ничего не
//     видно»: `scrollTop` зеркала выставлялся раньше, чем Vue его дорисовывал;
//   • «выделяется до прошлой/следующей строки»: полоса прокрутки сужала поле
//     относительно зеркала, и строки переносились в разных местах.
// Проверяется СВЯЗКА, на которой сломалось, а не внешний вид (его видно только глазами).
const boxRule = styles.match(/\.gb-composer-box\s*\{[\s\S]*?\n\}/)?.[0] || ''
const inputRule = styles.match(/\.gb-composer-input\s*\{[\s\S]*?\n\}/)?.[0] || ''
const scrollRule = styles.match(/\.gb-composer-scroll\s*\{[\s\S]*?\n\}/)?.[0] || ''

test('правила стилей поля найдены', () => {
  assert.ok(boxRule && inputRule && scrollRule, 'не нашли правила композера — тест ослеп, чинить его')
})

test('🔥 у поля нет СВОЕЙ прокрутки — её ведёт общее окно', () => {
  assert.ok(/overflow:\s*hidden/.test(inputRule),
    'поле снова прокручивается само: у переполненного поля появится полоса, сузит его '
    + 'относительно зеркала, и подсветка выделения ляжет не на те слова, что видны')
  assert.ok(!/overflow-y:\s*(auto|scroll)/.test(inputRule), 'у поля вернулась своя полоса прокрутки')
  assert.ok(/overflow-y:\s*auto/.test(scrollRule), 'общее окно не прокручивается — длинный текст обрежется')
  assert.ok(/max-height/.test(scrollRule), 'у окна нет потолка — поле вырастет на весь экран')
  assert.ok(!/max-height/.test(boxRule),
    'потолок высоты вернулся на само поле: оно перестанет расти вместе с зеркалом')
})

test('🔥 зеркало и поле лежат в ОДНОЙ ячейке внутри ОДНОГО окна прокрутки', () => {
  const block = src.match(/ref="composerScroll"[\s\S]*?<\/textarea>|ref="composerScroll"[\s\S]*?<textarea ref="composer"[\s\S]*?\/>/)?.[0] || ''
  assert.ok(block, 'поле больше не лежит в общем окне прокрутки')
  assert.ok(/gb-composer-stack/.test(block) && /ref="mirror"/.test(block),
    'зеркало вынесено из общего окна — оно снова будет прокручиваться отдельно от поля')
  assert.ok(/\.gb-composer-stack\s*\{[^}]*display:\s*grid/.test(styles)
    && /\.gb-composer-stack\s*>\s*\*\s*\{[^}]*grid-area:\s*1\s*\/\s*1/.test(styles),
    'слои не сложены в одну ячейку сетки — поле не растянется на высоту зеркала')
  // Зеркало НЕ абсолютное: высоту ячейки задаёт именно оно.
  const mirrorTag = src.match(/<div ref="mirror"[^>]*>/)?.[0] || ''
  assert.ok(!/\babsolute\b/.test(mirrorTag),
    'зеркало снова абсолютное — оно перестало задавать высоту, и поле не вырастет')
})

test('🔒 прежней синхронизации прокрутки больше нет', () => {
  // Она и была дефектом: копировала scrollTop в зеркало, которое ещё не дорисовано.
  assert.ok(!/syncMirrorScroll/.test(src),
    'вернулась раздельная прокрутка зеркала — видимый текст снова отстанет от курсора')
})

test('перенос строк задан ЯВНО и общим классом', () => {
  // У textarea эти значения из стилей браузера, у div — наследуются. Общий класс —
  // единственное место, где они гарантированно совпадают.
  assert.ok(/white-space:\s*pre-wrap/.test(boxRule), 'перенос не задан общим классом')
  assert.ok(/overflow-wrap:\s*break-word/.test(boxRule), 'разрыв длинных слов не задан общим классом')
  const mirrorTag = src.match(/<div ref="mirror"[^>]*>/)?.[0] || ''
  assert.ok(!/whitespace-|break-words/.test(mirrorTag),
    'у зеркала свои утилиты переноса поверх общего класса — они разойдутся с полем')
})

test('последняя ПУСТАЯ строка имеет высоту', () => {
  // Shift+Enter в конце текста: без хвостового символа блок не даёт пустой строке
  // высоты — поле не вырастет, и курсор уйдёт под нижний край.
  assert.ok(/gb-composer-tail/.test(src), 'у зеркала нет хвостового символа')
})

test('курсор держат в виду ПОСЛЕ перерисовки зеркала', () => {
  // Порядок и был причиной: мерить надо уже выросшее зеркало, то есть после nextTick.
  assert.ok(/watch\(draft,\s*\(\)\s*=>\s*nextTick\(revealCaret\)\)/.test(src),
    'прокрутка к курсору не привязана к смене текста через nextTick')
  assert.ok(/function revealCaret[\s\S]{0,1600}?scrollToRevealCaret\(/.test(src),
    'revealCaret не пользуется проверенным расчётом из utils/composerKeys.js')
})

test('клавиши исполняются по решению composerKeyAction', () => {
  assert.ok(/function onComposerKeydown[\s\S]{0,900}?composerKeyAction\(/.test(src),
    'обработчик клавиш поля решает сам — правила из utils/composerKeys.js не действуют')
  assert.ok(/@keydown="onComposerKeydown"/.test(composerTag) && /@paste="onComposerPaste"/.test(composerTag),
    'обработчики клавиш или вставки не подключены к полю')
})
