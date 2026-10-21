// messengerLive.test.mjs — правила «живости» мессенджера и слияния входящих сообщений.
//
// Заведён 24.08.2026 по итогам замеров на стенде (400 сообщений, живой сервер):
//   • 9 запросов за 10 секунд ПОЛНОГО покоя — опрос крутился с частотой 3.5 с при живом
//     сокете, хотя всё, что он мог принести, сокет уже принёс. После правки — 0 запросов
//     за те же 10 секунд, доставка сообщения 76 мс;
//   • открытие чата — 7 ПОСЛЕДОВАТЕЛЬНЫХ волн запросов (на боевой сети ≈700 мс, в течение
//     которых экран дорисовывается кусками). После правки — 1 волна плюс два фоновых;
//   • своё сообщение появлялось только после ответа сервера. Теперь рисуется черновиком
//     за 19 мс и подменяется настоящим.
//
// Здесь проверяются ПРАВИЛА, вынесенные из стора: их можно исполнить без браузера, а
// правило, живущее внутри Pinia-стора, проверить нечем — и потому оно тихо разъезжается.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { pollInterval, reconnectDelay, shellBadgeTickDue, POLL_MS_WS, POLL_MS_NO_WS, RECONNECT_MAX_MS, RECONNECT_MIN_MS } from '../src/utils/livePolling.js'
import { resolveIncoming } from '../src/utils/messageMerge.js'

const WEB = dirname(dirname(fileURLToPath(import.meta.url)))
const store = readFileSync(join(WEB, 'src/stores/messenger.js'), 'utf8')

// ── частота опроса ──────────────────────────────────────────────────────────────
test('при живом сокете опрос заметно реже, чем без него', () => {
  const сСокетом = pollInterval({ wsAlive: true, hidden: false })
  const безСокета = pollInterval({ wsAlive: false, hidden: false })
  assert.equal(сСокетом, POLL_MS_WS)
  assert.equal(безСокета, POLL_MS_NO_WS)
  assert.ok(сСокетом >= безСокета * 4, 'сверочный тик обязан быть в разы реже транспортного')
})

test('без сокета опрос остаётся частым — он и есть транспорт', () => {
  assert.ok(pollInterval({ wsAlive: false, hidden: false }) <= 5000,
    'без сокета редкий опрос означал бы, что сообщения приходят с задержкой в полминуты')
})

test('в скрытой вкладке не опрашиваем вовсе', () => {
  assert.equal(pollInterval({ wsAlive: true, hidden: true }), 0)
  assert.equal(pollInterval({ wsAlive: false, hidden: true }), 0)
})

// ── переподключение ─────────────────────────────────────────────────────────────
test('интервал переподключения растёт вдвое и упирается в потолок', () => {
  // rand → 1: верхняя граница интервала — та самая лестница 1, 2, 4 … с.
  const top = () => 0.999999
  assert.equal(reconnectDelay(0, top), 999)
  assert.equal(reconnectDelay(1, top), 1999)
  assert.equal(reconnectDelay(2, top), 3999)
  assert.ok(reconnectDelay(3, top) < reconnectDelay(4, top), 'интервал должен расти')
  assert.ok(reconnectDelay(50, top) < RECONNECT_MAX_MS + 1, 'без потолка упавший сервер получил бы шквал попыток')
})

test('пауза — случайная внутри интервала (разброс Брукера, 20.10.2026)', () => {
  // Обратный ход дефекта: без разброса все вкладки колледжа после перезапуска сервера
  // стучались в одну и ту же секунду. Сто вкладок обязаны разойтись по интервалу.
  const delays = new Set(Array.from({ length: 100 }, () => reconnectDelay(5)))
  assert.ok(delays.size > 50, `пауза почти не разбросана: ${delays.size} разных из 100`)
  for (const d of delays) assert.ok(d >= RECONNECT_MIN_MS && d <= 32000)
  assert.equal(reconnectDelay(3, () => 0), RECONNECT_MIN_MS, 'ноль — это цикл без паузы')
})

// ── слияние входящих ────────────────────────────────────────────────────────────
test('настоящее сообщение подменяет свой черновик, а не ложится рядом', () => {
  const лента = [{ id: -1, pending: true, client_nonce: 'n1', body: 'привет' }]
  const r = resolveIncoming(лента, { id: 42, client_nonce: 'n1', body: 'привет' })
  assert.deepEqual(r, { action: 'replace', index: 0 })
})

test('повторная доставка того же сообщения не затирает принятое', () => {
  //У настоящего сообщения nonce тоже есть — без проверки pending эта же ветка
  //перезаписала бы уже принятое сообщение и снесла проставленные на нём реакции.
  const лента = [{ id: 42, client_nonce: 'n1', body: 'привет', reactions: [{ emoji: '👍', count: 1 }] }]
  const r = resolveIncoming(лента, { id: 42, client_nonce: 'n1', body: 'привет', reactions: [] })
  assert.equal(r.action, 'skip')
})

test('чужое сообщение добавляется в конец', () => {
  const r = resolveIncoming([{ id: 1 }], { id: 2, body: 'ответ' })
  assert.deepEqual(r, { action: 'append', index: 1 })
})

test('черновик с другой меткой не трогаем', () => {
  const лента = [{ id: -1, pending: true, client_nonce: 'n1' }]
  const r = resolveIncoming(лента, { id: 7, client_nonce: 'ДРУГАЯ' })
  assert.equal(r.action, 'append')
})

// ── правила должны быть ВЫЗВАНЫ, а не просто существовать ───────────────────────
// Наш самый частый класс дефекта: функция есть, тесты её поведения зелёные, а в продукте
// её не зовёт никто. Поэтому сторож смотрит на вызовы в сторе, а не только на поведение.
test('стор действительно пользуется этими правилами', () => {
  assert.match(store, /import \{ pollInterval, reconnectDelay \} from '@\/utils\/livePolling'/)
  assert.match(store, /import \{ resolveIncoming \} from '@\/utils\/messageMerge'/)
  assert.match(store, /pollInterval\(\{ wsAlive/, 'интервал опроса перестал считаться правилом')
  assert.match(store, /reconnectDelay\(wsRetry/, 'пауза переподключения перестала считаться правилом')
  assert.match(store, /resolveIncoming\(messages\.value, msg\)/, 'слияние входящих перестало идти через правило')
})

test('сокет переподключается после разрыва', () => {
  //Без этого один разрыв (уснул ноутбук, сменилась сеть) убивал живость до перезахода в
  //раздел, и мессенджер незаметно возвращался к опросу как единственному транспорту.
  assert.match(store, /ws\.onclose\s*=\s*\(\)\s*=>\s*\{[^}]*_scheduleReconnect\(\)/,
    'onclose больше не назначает переподключение')
  assert.match(store, /function _disconnectWS\(\)[\s\S]{0,400}ws\.onclose = null/,
    'при закрытии раздела обработчик не снимается — переподключимся к закрытому мессенджеру')
})

test('своё сообщение рисуется до ответа сервера', () => {
  assert.match(store, /_optimisticMessage\(/, 'черновик собственного сообщения исчез')
  assert.match(store, /messages\.value\.push\(черновик\)/, 'черновик больше не попадает в ленту сразу')
  assert.match(store, /pending: true/, 'у черновика нет признака неподтверждённости')
})

test('открытие чата идёт ОДНОЙ волной запросов, а не лесенкой', () => {
  //Семь `await` подряд — это семь кругов до сервера и семь ступеней дорисовки экрана.
  assert.match(store, /await Promise\.all\(дела\)/, 'запросы открытия снова выполняются по очереди')
  assert.match(store, /markReadActive\(\)\.then\(loadChats\)/, 'хвост открытия снова блокирует показ чата')
})

// ── история вверх ───────────────────────────────────────────────────────────────
// Сервер умел `?before=<id>` с самого начала, и endpoints.js прямо обещал «history
// (before=<id>)» — а вызова не было НИ ОДНОГО: в вебе переписку глубже последних 50
// сообщений нельзя было прочитать вовсе. Сторож смотрит именно на ВЫЗОВ и на его
// потребителя: поведение функции, которую никто не зовёт, ничего не значит.
const thread = readFileSync(join(WEB, 'src/components/messenger/ChatThread.vue'), 'utf8')

test('клиент запрашивает историю вверх', () => {
  assert.match(store, /messengerApi\.messages\(convId, \{ before: первое\.id \}\)/,
    'запрос истории с before пропал — переписка снова обрывается на 50 сообщениях')
  assert.match(store, /function loadOlder\(/)
  assert.match(store, /loadOlder,/, 'loadOlder не экспортирован из стора — его нечем позвать')
})

test('прокрутка вверх действительно зовёт подгрузку', () => {
  assert.match(thread, /if \(el\.scrollTop < 200\) подтянутьИсторию\(\)/,
    'подгрузка истории больше не привязана к прокрутке — функция осталась без вызывающего')
})

test('позиция прокрутки удерживается при подгрузке', () => {
  //Без этого подгрузка сама становится дефектом: вставленные сверху сообщения уносят
  //прочитанное место вниз, и лента прыгает под руками.
  assert.match(thread, /el\.scrollTop = сверхуДо \+ \(el\.scrollHeight - высотаДо\)/,
    'потеряна компенсация прокрутки — лента будет прыгать при догрузке истории')
})

test('дошли до начала переписки — больше не просим', () => {
  assert.match(store, /if \(старые\.length < PAGE\) hasOlder\.value = false/,
    'без этого клиент бесконечно долбит сервер запросами в пустоту')
})

// ── находки Полковника, 24.08.2026 ──────────────────────────────────────────────
// Все три ниже — дефекты, ВНЕСЁННЫЕ этим же заходом и не пойманные ни одним замером.
// Первый особенно поучителен: проверка «дублей в ленте нет» его пропускала, потому что
// дублей и правда не было — ломался ПОРЯДОК.
const shell = readFileSync(join(WEB, 'src/layouts/AppShell.vue'), 'utf8')

test('граница опроса не берётся с неподтверждённого черновика', () => {
  //У черновика id ОТРИЦАТЕЛЬНЫЙ. Уйдя в `?after=-1756…`, он превращает дельту в «отдай
  //всё с начала беседы»: сервер честно возвращает первые 50 сообщений, и они ложатся
  //в КОНЕЦ ленты, под свежие.
  assert.match(store, /function _lastId\(\)[\s\S]{0,400}!m0\.pending && m0\.id > 0/,
    '_lastId снова смотрит на последний элемент ленты, включая черновик')
  assert.doesNotMatch(store, /function _lastId\(\) \{\s*return messages\.value\.length \? messages\.value\[messages\.value\.length - 1\]\.id : 0/,
    'вернулась старая реализация _lastId')
})

test('анимация появления не срабатывает на подставленной сверху истории', () => {
  //Пятьдесят одновременно всплывающих пузырей под рукой у прокручивающего — та же рябь,
  //которую запрещает комментарий в компоненте; «новое» это только хвост ленты.
  assert.match(thread, /for \(let i = ids\.length - 1; i >= 0; i--\)[\s\S]{0,200}знакомыеId\.has\(ids\[i\]\)\) break/,
    'анимация снова считает новым всё, чего не было в прошлом списке — включая prepend')
})

test('счётчик непрочитанного молчит в свёрнутой вкладке', () => {
  //Этот таймер живёт ВНЕ стора (значок нужен и вне мессенджера), поэтому stopPolling его
  //не гасит, и замер «0 запросов за 10 с» его в принципе не мог увидеть — период 20 с.
  assert.match(shell, /document\.hidden\) return/,
    'таймер счётчика непрочитанного снова ходит на сервер в скрытой вкладке')
  assert.match(shell, /_unreadTimer = setInterval\(\(\) => \{/,
    'таймер счётчика перестал быть проверяемым — вернулась однострочная форма без гварда')
  assert.match(shell, /visibilitychange', _onVisible/, 'при возврате на вкладку счётчик не обновляется')
})

// ── 07.10.2026: значок в меню дублировал опрос раздела и просил заявки, которые не показывает ──
// Замер на стенде, вкладка в покое, 62 с: в разделе сообщений 10 запросов (6 — дубль
// оболочки), на главной 6 (список бесед и заявки). После правки — 4 и 3.
test('значок в меню не опрашивает, пока раздел сообщений опрашивает сам', () => {
  assert.equal(shellBadgeTickDue({ hidden: false, storePolling: false }), true)
  assert.equal(shellBadgeTickDue({ hidden: false, storePolling: true }), false,
    'оболочка снова дублирует тик раздела сообщений')
  assert.equal(shellBadgeTickDue({ hidden: true, storePolling: false }), false)
})

test('оболочка действительно спрашивает это правило и стор на него отвечает', () => {
  //Правило без вызывающего — наш самый частый дефект: функция верна, а зовут не её.
  assert.match(shell, /shellBadgeTickDue\(\{ hidden, storePolling: messenger\.isPolling\(\) \}\)/,
    'оболочка решает о тике значка мимо shellBadgeTickDue')
  assert.match(store, /function isPolling\(\) \{ return !!pollTimer \}/,
    'стор не сообщает, что опрашивает сам, — оболочке не у кого спросить')
  assert.match(store, /startPolling, stopPolling, isPolling,/, 'isPolling не отдан наружу из стора')
  //Оба входа — таймер и возврат на вкладку — идут через одну функцию: забытый второй
  //вход вернул бы дубль ровно в момент, когда человек переключился обратно.
  assert.match(shell, /_onVisible = \(\) => \{ if \(!document\.hidden\) badgeTick\(\) \}/)
  const bare = shell.split('\n').filter((l) => /messenger\.loadChats\(\)/.test(l) && !l.trim().startsWith('//'))
  assert.equal(bare.length, 1, 'в оболочке должен остаться один полный loadChats() — при входе; '
    + `сейчас их ${bare.length}`)
})

test('значок не запрашивает заявки, а раздел сообщений — запрашивает', () => {
  assert.match(shell, /messenger\.loadChats\(\{ invites: false \}\)/, 'значок снова просит заявки')
  assert.match(store, /if \(!opts \|\| opts\.invites !== false\) loadInvites\(\)/,
    'loadChats перестал различать «без заявок»')
  //Тик самого раздела — с заявками: их показывает он, и без них приглашение в беседу
  //не появилось бы, пока человек не перезайдёт.
  assert.match(store, /await loadConvInfo\(false\)\s*\}\s*await loadChats\(\)/,
    'тик раздела сообщений зовёт loadChats с аргументом — заявки могли пропасть')
})

// ── Жалобы 25.08.2026: «пустое окно, потом сообщения» и «гифки грузятся после» ──────
const gifImage = readFileSync(join(WEB, 'src/components/messenger/GifImage.vue'), 'utf8')

test('при переходе в другую беседу лента гасится ДО похода на сервер', () => {
  //Шапка меняется мгновенно (имя есть в уже загруженном списке чатов), а сообщения
  //ехали сетевым кругом — и всё это время под НОВЫМ именем висели сообщения ПРЕДЫДУЩЕЙ
  //беседы. Скелет ленты при этом не показывался вовсе: его условие `!messages.length`
  //было ложным, потому что старые сообщения ещё лежали в сторе.
  const enter = store.slice(store.indexOf('async function _enterChat'),
                            store.indexOf('async function loadConvInfo'))
  assert.match(enter, /if \(activeId\.value !== convId\) \{[\s\S]{0,300}messages\.value = \[\]/,
    'лента больше не гасится при смене беседы — вернётся «чужие сообщения под новым именем»')
  assert.match(enter, /if \(activeId\.value !== convId\)/,
    'гашение должно стоять ПОД условием смены: повторный вход в ту же беседу мигал бы пустотой')
  //Порядок значим: гасим ДО присвоения activeId, иначе условие всегда ложно.
  assert.ok(enter.indexOf('messages.value = []') < enter.indexOf('activeId.value = convId'),
    'гашение стоит ПОСЛЕ activeId.value = convId — условие смены беседы никогда не сработает')
})

test('скелет ленты показывается именно при первой загрузке беседы', () => {
  assert.match(thread, /v-if="loadingMessages && !messages\.length"/,
    'условие скелета изменилось — проверь, что он вообще успевает показаться')
})

test('под гифку зарезервировано место, а не пустота', () => {
  //У <img> без размеров высота до загрузки равна нулю: на месте гифки пустота, а когда
  //файл доезжает — лента дёргается и уносит строку, которую человек читал.
  assert.match(gifImage, /\.gb-gif--loading[\s\S]{0,200}height:\s*200px/,
    'резерв места под гифку пропал — вернётся прыжок ленты на догрузке')
  assert.match(gifImage, /background:\s*#0b0b10/, 'тёмная подложка под гифкой пропала')
  assert.match(gifImage, /@error="state = 'error'"/,
    'без обработки ошибки битая гифка навсегда останется чёрным квадратом')
  assert.match(gifImage, /prefers-reduced-motion/, 'дыхание заглушки не гаснет при reduced-motion')
})

test('обе гифки в ленте рисуются одним компонентом', () => {
  //Их две: msg.kind==='gif' (через пикер) и голая ссылка на CDN в обычном тексте.
  //Пока это были два одинаковых <img>, починка одного из них молча не касалась второго.
  const imgs = thread.match(/<img[^>]*\bsrc="(?:msg\.body|g\.sourceUrl)"/g) || []
  assert.equal(imgs.length, 0, 'гифка снова рисуется голым <img> мимо GifImage.vue')
  assert.equal((thread.match(/<GifImage /g) || []).length, 2,
    'ожидались ровно два места с GifImage (пикер и голая ссылка)')
})
