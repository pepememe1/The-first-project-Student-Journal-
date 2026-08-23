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

test('пасхалка выхода закрывается ДО logout, а не в самой сцене', () => {
  // 🔥 Ачивку за Dark Souls не выдавали никогда: сцена звала claim через 700 мс после
  // показа, а `auth.logout()` стирает токен немедленно — запрос уходил без авторизации
  // и получал 401. Человек видел пасхалку и справедливо считал, что его обманули.
  const settings = readFileSync(join(ROOT, 'src/pages/Settings.vue'), 'utf8')
  const scene = readFileSync(join(ROOT, 'src/components/easter/DarkSoulsFarewell.vue'), 'utf8')

  // ⚠️ Комментарии выбрасываем ДО поиска. Первая версия этой проверки нашла
  // `auth.logout()` в ПОЯСНЕНИИ к правке — оно стоит выше самого вызова — и покраснела
  // на исправном коде. Тот же промах уже был со сторожем шрифтов; повторяется он
  // потому, что искать подстроку в исходнике проще, чем в коде.
  const logoutBody = settings.split('async function onLogout()')[1].split('\n}')[0]
    .replace(/\/\/.*$/gm, '')
  const claimAt = logoutBody.indexOf("claim('dark_souls_logout')")
  const logoutAt = logoutBody.indexOf('auth.logout()')
  assert.ok(claimAt >= 0, 'ачивка не закрывается в onLogout вовсе')
  assert.ok(logoutAt >= 0, 'разбор onLogout сломался')
  assert.ok(claimAt < logoutAt, 'claim обязан идти ДО logout — после него токена уже нет')

  // Комментарии выбрасываем и здесь — по той же причине: пояснение «здесь стоял
  // claim(...)» само содержит искомую строку. Проверка обязана смотреть на КОД.
  const sceneCode = scene.replace(/\/\/.*$/gm, '')
  assert.ok(!sceneCode.includes('claim('),
    'в сцене снова появился claim — он там уходит в пустоту и создаёт видимость работы')
})

test('стор пасхалок обнуляется при выходе из аккаунта', () => {
  // ⚠️ Выход на общем компьютере колледжа — это СМЕНА ВЛАДЕЛЬЦА. Без обнуления тост
  // «достижение открыто» от прошлого человека всплывал на экране входа у следующего,
  // а его список ачивок продолжал глушить вопросы. Тот же принцип, которым уже чистятся
  // черновики мессенджера и оффлайн-кэш.
  const store = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
  const auth = readFileSync(join(ROOT, 'src/stores/auth.js'), 'utf8')
  assert.match(store, /function reset\(\)/, 'в сторе пасхалок нет reset()')
  for (const field of ['active.value', 'inPage.value', 'owned.value', 'lastUnlocked.value']) {
    const body = store.split('function reset()')[1].split('\n  }')[0]
    assert.ok(body.includes(field), `reset() не чистит ${field}`)
  }
  assert.match(auth.replace(/\/\/.*$/gm, ''), /useEasterStore\(\)\.reset\(\)/,
    'logout не обнуляет стор пасхалок')
})

test('полноэкранная сцена запирает переход на пару секунд, слой страницы — нет', () => {
  // ⚠️ У пасхалок два разных механизма, и обращаться с ними одинаково неправильно.
  // Штамп ПОЯВЛЯЕТСЯ НА странице — его легко не заметить, там уместен вопрос. Дерево
  // и Hotline ЗАМЕНЯЮТ собой экран: пропустить их невозможно, а опасен только первый
  // миг, когда рука уже нажимает соседнюю вкладку. Отсюда беззвучная задержка вместо
  // вопроса — но ТОЛЬКО для полноэкранных.
  assert.match(store, /const NAV_LOCK_MS = \d+/, 'нет задержки перехода')
  assert.match(store, /function navLocked\(\)/, 'нет признака «сейчас уходить нельзя»')

  const placeBody = store.split('function place(egg)')[1].split('\n  }')[0]
  const lockAt = placeBody.indexOf('lockedUntil.value = Date.now()')
  const inPageReturn = placeBody.indexOf('IN_PAGE.has(egg)')
  assert.ok(lockAt >= 0, 'замок не ставится вовсе')
  assert.ok(inPageReturn >= 0 && inPageReturn < lockAt,
    'слой внутри страницы обязан выходить ДО замка — иначе он тоже запрёт навигацию')
})

test('замок снимается вместе со сценой', () => {
  // Переживи он сцену — навигация осталась бы запертой на пустом экране, и человек
  // решил бы, что продукт завис. Проверяем все три выхода.
  const store2 = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
  for (const fn of ['function close()', 'function dismissPending()', 'function reset()']) {
    const body = store2.split(fn)[1].split('\n  }')[0]
    assert.ok(body.includes('lockedUntil.value = 0'), `${fn} не снимает замок`)
  }
})

test('страж проверяет замок РАНЬШЕ вопроса', () => {
  // Иначе диалог всплывёт поверх только что появившейся сцены и закроет её собой.
  const code = router.replace(/\/\/.*$/gm, '')
  const lockAt = code.indexOf('easter.navLocked()')
  const askAt = code.indexOf('easter.pending')
  assert.ok(lockAt >= 0 && askAt >= 0, 'разбор стража сломался')
  assert.ok(lockAt < askAt, 'замок обязан проверяться до вопроса')
})

test('список полученных ачивок грузится НЕ под замком броска', () => {
  // 🔥 Он лежал внутри afterLogin(), то есть под замком «один раз на вкладку». После
  // обычного F5 замок уже стоял, список оставался пустым, и правило «не спрашивать про
  // уже полученную ачивку» не работало ВООБЩЕ. Человек, давно закрывший находку, снова
  // получал «останьтесь, а то не заберёте» — притом что забирать нечего.
  const shell = readFileSync(join(ROOT, 'src/layouts/AppShell.vue'), 'utf8')
    .replace(/\/\/.*$/gm, '')
  const body = shell.split('async function askLoginEggs()')[1].split('\n}')[0]
  const loadAt = body.indexOf('easter.loadOwned()')
  const lockAt = body.indexOf('sessionStorage.getItem')
  assert.ok(loadAt >= 0, 'список ачивок вообще не грузится в оболочке')
  assert.ok(lockAt >= 0, 'разбор замка сломался')
  assert.ok(loadAt < lockAt, 'загрузка списка снова оказалась ПОД замком броска')

  const store2 = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
  //⚠️ Ищем по ОТКРЫВАЮЩЕЙ скобке, без списка параметров: у `afterLogin` появился
  //признак «нужен ли бросок сцены», и привязка к точной сигнатуре роняла тест на
  //законной правке. Сторож должен реагировать на СУТЬ, а не на форму объявления.
  const after = store2.split('async function afterLogin(')[1].split('\n  }')[0]
  assert.ok(!after.includes('loadOwned('),
    'loadOwned вернулся внутрь afterLogin — он снова будет пропускаться после F5')
})

test('поздний ответ броска не садится на покинутую страницу', () => {
  // Бросок уходит на сервер после загрузки журнала. Уйдёшь за это время — ответ поднимет
  // флаг пасхалки на странице, которой уже нет, и продукт будет спрашивать «тут пасхалка»
  // там, где её нечем показать, а «Прислушаться» ничего не покажет.
  const page = readFileSync(join(ROOT, 'src/pages/student/StudentJournal.vue'), 'utf8')
  assert.match(page, /onBeforeUnmount\(\(\) => \{ alive = false \}\)/,
    'страница не отмечает, что её покинули')
  const mounted = page.split('onMounted(async () => {')[1].split('\n})')[0]
  assert.ok((mounted.match(/if \(!alive\)/g) || []).length >= 2,
    'проверка «страница ещё жива» нужна и до броска, и после ответа')
  assert.ok(mounted.includes('closeInPage'),
    'поздний ответ не прибирается — флаг уедет на другую страницу')
})

test('замок пасхалок входа снимается при выходе из аккаунта', () => {
  // 🔥 Ключ `gb.egg.login:<логин>` живёт в sessionStorage и переживает выход. Пока его
  // не снимали, «вошёл → вышел → вошёл» в одной вкладке давало ОДИН бросок за всю её
  // жизнь: Cyberpunk, Detroit, Skyrim и ночной FNAF становились недостижимы после
  // первой же попытки, пока вкладку не закроешь.
  // ⚠️ Замок нужен против F5 — перезагрузка не должна давать новый шанс. Но выход это
  // не перезагрузка, а конец сессии, и следующий вход обязан быть полноценным.
  const body = store.split('function reset()')[1].split('\n  }')[0]
  assert.ok(body.includes("startsWith('gb.egg.login:')"),
    'reset() не снимает замок пасхалок входа — они станут одноразовыми на вкладку')
  assert.ok(body.includes('removeItem'), 'ключи находятся, но не удаляются')
})
