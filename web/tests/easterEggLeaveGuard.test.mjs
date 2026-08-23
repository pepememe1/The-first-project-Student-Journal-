// Сторож подтверждения ухода со страницы, пока на экране пасхалка.
//
// ⚠️ Проверять надо ОБЕ стороны правила, и вторая важнее первой. «Спрашивает, когда
// есть что терять» сломается заметно — человек пожалуется. А вот «НЕ спрашивает про
// постоянные пасхалки» сломается катастрофически и тихо: кольцо Detroit, состояние
// DOOM и счётчик ULTRAKILL висят у студента ВСЁ ВРЕМЯ, и попади они в список
// пропускаемых, продукт задавал бы «точно уйти?» на каждом переходе между вкладками.
// Это уже не пасхалка, а сломанная навигация всему колледжу.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const store = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
const router = readFileSync(join(ROOT, 'src/router/index.js'), 'utf8')
const desktop = readFileSync(join(ROOT, '..', 'desktop/webview2_app.py'), 'utf8')

const missable = new Set([...store.split('const MISSABLE_IN_PAGE = new Set([')[1]
  .split('])')[0].matchAll(/'([a-z0-9_]+)'/g)].map(m => m[1]))

// Постоянные — те, что живут на аватарке и в журнале всё время, пока человек в системе.
const ALWAYS_ON = ['detroit_led', 'doom_avatar', 'ultrakill_rank']

test('постоянные пасхалки НЕ считаются пропускаемыми', () => {
  const wrong = ALWAYS_ON.filter(id => missable.has(id))
  assert.deepEqual(wrong, [],
    'из-за этого «точно уйти?» спрашивалось бы на КАЖДОМ переходе:\n' + wrong.join('\n'))
})

test('разовые пасхалки страницы сторожатся', () => {
  for (const id of ['binding_of_isaac_d6', 'papers_please_stamp', 'undertale_save']) {
    assert.ok(missable.has(id), `${id} можно пропустить, но переход не сторожится`)
  }
})

test('страж стоит ПОСЛЕ перенаправлений и не трогает выход из аккаунта', () => {
  assert.match(router, /confirmLeavingEasterEgg/, 'страж вообще не подключён к роутеру')
  // Выход уводит на /login, и вопрос поверх уже начатого logout — это ловушка.
  assert.match(router, /to\.path === '\/login'/, 'выход из аккаунта обязан быть исключением')
  // Вопрос — последним: иначе спрашивали бы перед переходом, который не состоится.
  // ⚠️ Ищем именно ВЫЗОВ (await …), а не определение функции: определение стоит в
  // начале файла, и первая версия этой проверки цеплялась за него и краснела на
  // исправном коде.
  const guardAt = router.indexOf('await confirmLeavingEasterEgg(to, from)')
  const roleAt = router.lastIndexOf("to.meta.role")
  assert.ok(guardAt > roleAt, 'страж обязан стоять после проверок роли и авторизации')
})

test('закрытие окна и вкладки тоже перехвачено', () => {
  assert.match(router, /beforeunload/, 'закрытие вкладки не сторожится')
  assert.match(router, /__gbEasterPending/, 'нет моста для оболочки программы')
  assert.match(desktop, /__gbEasterPending/, 'десктоп не спрашивает страницу перед закрытием')
  assert.match(desktop, /events\.closing/, 'десктоп не подписан на закрытие окна')
})

test('обратный ход: правило ловит постоянную пасхалку в списке пропускаемых', () => {
  const broken = new Set([...missable, 'doom_avatar'])
  assert.ok(ALWAYS_ON.some(id => broken.has(id)),
    'проверка обязана краснеть, если постоянную добавят в список')
})

test('у каждой пропускаемой пасхалки СВОЯ реплика при уходе', () => {
  // ⚠️ Общее «вы уверены?» читается как ошибка формы и ничего не сообщает. Реплика в
  // голосе игры сама и есть подсказка, что на экране пасхалка и её стоит поискать
  // глазами — то есть вопрос делает две работы сразу. Забыть её легко и незаметно:
  // запасной текст подставится молча.
  const phrases = new Set([...store.split('const LEAVE_ASK = {')[1].split('\n}')[0]
    .matchAll(/^\s{2}([a-z0-9_]+):\s*\{/gm)].map(m => m[1]))
  const noPhrase = [...missable].filter(id => !phrases.has(id))
  assert.deepEqual(noPhrase, [],
    'пасхалку можно пропустить, а сказать при уходе нечего:\n' + noPhrase.join('\n'))
})

test('полноэкранные сцены с триггером «зашёл во вкладку» тоже спрашивают', () => {
  // Дерево и G-Man выпадают на обычном переходе — уйти от них проще всего.
  const phrases = store.split('const LEAVE_ASK = {')[1].split('\n}')[0]
  for (const id of ['deltarune_tree', 'gman_observer', 'hotline_miami']) {
    // ⚠️ Простое вхождение, без \\b: в шаблонной строке `\\b` — это символ «забой»,
    // а не граница слова, и такая проверка не находит НИЧЕГО, молча зеленея на
    // пустом месте. Поймано на себе в этом же заходе.
    assert.ok(phrases.includes(`  ${id}: {`), `нет реплики для ${id}`)
  }
})

test('про уже полученную ачивку вопрос не задаётся', () => {
  // ⚠️ Смысл вопроса — «останьтесь, а то не заберёте находку». Когда забирать нечего,
  // он превращается в помеху, и человек, нашедший всё, получал бы его до конца учёбы.
  // Проверяем НАЛИЧИЕ фильтра в вычислении pending, а не поведение сцены: сломать это
  // можно ровно одним способом — убрать проверку, и тогда тест краснеет.
  assert.match(store, /function stillWorthIt/, 'фильтра «уже получено» нет вовсе')
  assert.match(store, /owned\.value\.has\(aid\)/, 'фильтр не смотрит в список полученных')
  const pendingBody = store.split('const pending = computed(')[1].split('})')[0]
  assert.ok(pendingBody.includes('stillWorthIt'),
    'pending обязан пропускать через фильтр ОБА канала — и сцену, и слой страницы')
  // Оба вхождения: полноэкранная сцена и пасхалка внутри страницы.
  assert.equal((pendingBody.match(/stillWorthIt/g) || []).length, 2,
    'фильтр применён только к одному каналу из двух')
})

test('копия списка ачивок пополняется при выдаче', () => {
  // Иначе вопрос задавался бы ещё раз про ту же находку — до перезагрузки страницы.
  const claimBody = store.split('async function claim(')[1].split('\n  }')[0]
  assert.match(claimBody, /owned\.value = new Set\(owned\.value\)\.add\(achievement\)/,
    'после claim список полученных не пополняется')
})

test('бросок одной пасхалки не глушит бросок другой', () => {
  // 🔥 Общий флаг busy глушил почти всё: сторож маршрута просит дерево, через
  // миллисекунды страница просит свою пасхалку — и её молча отбрасывало. Hotline,
  // Papers Please, Undertale и G-Man почти никогда не бросались вовсе.
  assert.ok(!/\bbusy\.value\b/.test(store), 'вернулся общий флаг занятости')
  assert.match(store, /const inFlight = new Set\(\)/, 'нет поштучного флага')
  const rollBody = store.split('async function roll(egg)')[1].split('\n  }')[0]
  assert.ok(rollBody.includes('inFlight.has(key)'), 'бросок не защищён от самозадвоения')
  assert.ok(rollBody.includes('inFlight.delete(key)'), 'флаг не снимается — второй бросок не пройдёт')
})
