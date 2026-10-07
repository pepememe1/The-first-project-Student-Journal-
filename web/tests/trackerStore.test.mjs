/**
 * trackerStore.test.mjs — трекер задач: на сервер уходит ТОЛЬКО по кнопке «Сохранить».
 *
 * ━━ ЗАЧЕМ ━━
 * Требование Ярослава (05.10.2026): «чтобы уведомления из трекера не спамили, если кучу
 * задач делят на кучу людей, — сделать кнопку сохранить, при нажатии на которую сохранятся
 * все действия и придут уведомления тем, кого назначили». Письмо исполнителю сервер шлёт
 * на КАЖДОЕ сохранение, поэтому правило держится на одном свойстве клиента: ни одно
 * действие, кроме `save()`, не пишет на сервер. Появись такое — «одно письмо на
 * сохранение» перестало бы действовать именно на нём, молча и при зелёных тестах сервера.
 *
 * ━━ ЧТО ПРОВЕРЯЕТСЯ ━━
 *   • поведение НАСТОЯЩЕГО стора (Pinia, без браузера) с подменённым транспортом;
 *   • текстом — что мимо стора на сервер не пишет никто во всём `web/src`.
 *
 * ⚠️ Стор импортирует `@/…` — этого адреса node не знает. Ниже регистрируется разрешитель:
 * `@/api/endpoints` подменяется заглушкой (иначе потянулся бы axios с `import.meta.env`),
 * остальное `@/x` → `src/x.js`. Это единственный файл тестов с таким приёмом: остальные
 * проверяют чистые функции. Здесь же логика сохранения живёт в сторе, и вынести её в
 * чистую функцию значило бы проверять копию, а не продукт.
 *
 * ОБРАТНЫЙ ХОД ПРОВЕРЕН двенадцатью мутациями стора, каждая красит свой тест (06.10.2026):
 *   `this.ops = []` вместо среза после сохранения → «правка во время запроса»;
 *   очистка пачки в `catch` → «отказ сервера не стирает пачку»;
 *   убрать `|| this.saving` → «двойное нажатие»;
 *   убрать проверку `seq` у загрузки / не двигать `seq` при сохранении → «ответ загрузки,
 *   начатой до сохранения»;
 *   убрать `if (this.convId !== convId) return false` и не чистить пачку при смене беседы
 *   → «сохранение прежней беседы»;
 *   вызвать `messengerApi.trackerSave` из `stage()` → «ни одно действие, кроме save»;
 *   `this.skipped = []` → «операции, которые сервер пропустил»;
 *   `cloneState` вместо `rebase` → «чужое изменение с сервера»;
 *   убрать `isStaleSession` → «ответ прежней сессии»;
 *   не гасить `taskId` при битой ссылке → «ссылка из письма».
 * ⚠️ Тесты с отложенным ответом несут `timeout`: поломка обязана давать КРАСНЫЙ, а не
 * зависший прогон (первая версия «двойного нажатия» при мутации висела восемь минут).
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC_URL = new URL('../src/', import.meta.url)
const SRC = SRC_URL.pathname.replace(/^\/([A-Za-z]:)/, '$1')

// ── разрешитель `@/…` и заглушка транспорта ──────────────────────────────────────────
const STUB = `
const call = (name) => (...a) => {
  globalThis.__trackerCalls.push([name, ...a])
  const fn = globalThis.__trackerApi[name]
  if (!fn) throw new Error('неожиданный вызов messengerApi.' + name)
  return fn(...a)
}
export const messengerApi = new Proxy({}, { get: (_t, name) => call(String(name)) })
`
const HOOKS = `
const SRC = ${JSON.stringify(SRC_URL.href)}
const STUB = 'data:text/javascript,' + encodeURIComponent(${JSON.stringify(STUB)})
export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@/api/endpoints') return { url: STUB, shortCircuit: true }
  if (specifier.startsWith('@/')) {
    let rel = specifier.slice(2)
    if (!/\\.(js|mjs|json)$/.test(rel)) rel += '.js'
    return nextResolve(SRC + rel, context)
  }
  return nextResolve(specifier, context)
}
`
register('data:text/javascript,' + encodeURIComponent(HOOKS), import.meta.url)

const { createPinia, setActivePinia } = await import('pinia')
const { useTrackerStore } = await import('../src/stores/tracker.js')
const { compactOps } = await import('../src/utils/tracker.js')

// ── стенд ────────────────────────────────────────────────────────────────────────────
const clone = (x) => JSON.parse(JSON.stringify(x))
const task = (id, extra = {}) => ({
  id, project_id: 'trkp:1', column_id: 'trkc:todo', number: 1, key: 'WEB-1', kind: 'task',
  title: 'Задача', description: '', priority: 'normal', start_date: '', deadline: '',
  estimate: 0, spent: 0, position: 0, labels: [], checklist: [], parent_id: '', links: [],
  assignees: [], comment_count: 0, completed_at: '', ...extra,
})
const serverState = (tasks = [task('trkt:1')]) => ({
  enabled: true, open_edit: false, can_manage: true, can_configure: true, me: 'teach:t',
  members: [{ user_id: 'teach:t', full_name: 'Семёнова Анна' }, { user_id: 'stud:a', full_name: 'Иванов Пётр' }],
  projects: [{
    id: 'trkp:1', key: 'WEB', title: 'Сайт', description: '', color: '', position: 0, archived: false,
    labels: [],
    columns: [
      { id: 'trkc:todo', title: 'К выполнению', kind: 'todo', position: 0 },
      { id: 'trkc:done', title: 'Готово', kind: 'done', position: 1 },
    ],
  }],
  tasks,
})

/** Отложенный ответ: тест сам решает, когда «сервер» ответит. */
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

/** Свежий стор с открытым трекером беседы `conv`. Возвращает и журнал вызовов. */
async function opened(conv = 'c1', state = serverState()) {
  setActivePinia(createPinia())
  globalThis.__trackerCalls = []
  globalThis.__trackerApi = { tracker: async () => ({ data: clone(state) }) }
  const store = useTrackerStore()
  await store.openFor(conv)
  return store
}
const calls = (name) => globalThis.__trackerCalls.filter((c) => c[0] === name)
const writes = () => globalThis.__trackerCalls.filter((c) => c[0] !== 'tracker')

// ── главное правило ──────────────────────────────────────────────────────────────────
test('ни одно действие, кроме save, не ходит на сервер', async () => {
  const s = await opened()
  assert.equal(calls('tracker').length, 1, 'открытие трекера — одна загрузка')

  // Всё, что человек делает на доске и в окне задачи, — операции в пачку.
  s.stage({ op: 'task.create', id: 'trkt:new', column_id: 'trkc:todo', title: 'Новая', position: 1 })
  s.stage({ op: 'task.update', id: 'trkt:new', assignees: ['stud:a'], deadline: '2026-10-20' })
  s.stage({ op: 'task.move', id: 'trkt:1', column_id: 'trkc:done', position: 0 })
  s.stage([{ op: 'comment.add', id: 'c1', task_id: 'trkt:1', body: 'готово' },
    { op: 'project.update', id: 'trkp:1', title: 'Сайт колледжа' }])
  s.stage({ op: 'column.create', id: 'trkc:x', project_id: 'trkp:1', title: 'Отложено', kind: 'todo' })
  s.stage({ op: 'task.delete', id: 'trkt:new' })
  s.resetFilter()
  s.taskId = 'trkt:1'
  s.view = 'list'
  s.close()
  assert.deepEqual(writes(), [], 'правка ушла на сервер мимо кнопки «Сохранить»')
  assert.equal(s.dirty, true)

  // «Отменить» тоже ничего не шлёт — и после неё сохранять нечего.
  s.discard()
  assert.equal(s.dirty, false)
  assert.equal(await s.save(), false, 'пустую пачку не отправляют')
  assert.deepEqual(writes(), [])
})

test('одно нажатие «Сохранить» — один запрос со сжатой пачкой', async () => {
  const s = await opened()
  // Создал задачу, заполнил три поля по одному, перетащил дважды — семь действий.
  s.stage({ op: 'task.create', id: 'trkt:new', column_id: 'trkc:todo', title: 'Без названия', position: 1 })
  s.stage({ op: 'task.update', id: 'trkt:new', title: 'Свёрстать главную' })
  s.stage({ op: 'task.update', id: 'trkt:new', assignees: ['stud:a'] })
  s.stage({ op: 'task.update', id: 'trkt:new', deadline: '2026-10-20' })
  s.stage({ op: 'task.move', id: 'trkt:1', column_id: 'trkc:done', position: 0 })
  s.stage({ op: 'task.move', id: 'trkt:1', column_id: 'trkc:todo', position: 2 })
  const staged = clone(s.ops)

  const after = serverState([task('trkt:1', { position: 2 }),
    task('trkt:new', { number: 2, key: 'WEB-2', title: 'Свёрстать главную', assignees: ['stud:a'], deadline: '2026-10-20', position: 1 })])
  globalThis.__trackerApi.trackerSave = async () => ({ data: { applied: 2, skipped: [], notified: 1, state: after } })

  assert.equal(await s.save(), true)
  const sent = calls('trackerSave')
  assert.equal(sent.length, 1, 'пачка обязана уйти ОДНИМ запросом — письмо шлётся на каждое сохранение')
  assert.equal(sent[0][1], 'c1')
  // Сжатие — та же функция продукта: формулу у себя не повторяем, сверяем факт вызова.
  assert.deepEqual(sent[0][2], compactOps(staged))
  assert.equal(sent[0][2].length, 2, 'семь действий человека — две операции на сервер')
  assert.deepEqual(sent[0][2][0].assignees, ['stud:a'], 'назначение обязано доехать вместе с созданием')

  assert.equal(s.dirty, false)
  assert.equal(s.notified, 1)
  assert.equal(s.task, null)
  assert.equal(s.draft.tasks.find((t) => t.id === 'trkt:new').key, 'WEB-2', 'номер задаче выдаёт сервер')
})

test('отказ сервера не стирает пачку', async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Переименовал' })
  s.stage({ op: 'task.update', id: 'trkt:1', assignees: ['stud:a'] })
  // Причину называет сервер (заглушён в беседе, слишком часто, нет прав) — показываем её.
  globalThis.__trackerApi.trackerSave = async () => {
    throw Object.assign(new Error('403'), { response: { status: 403, data: { detail: 'Вы заглушены в этой беседе' } } })
  }
  assert.equal(await s.save(), false)
  assert.equal(s.ops.length, 2, 'минуты работы пропали из-за отказа сервера')
  assert.equal(s.dirty, true)
  assert.equal(s.error, 'Вы заглушены в этой беседе')
  assert.equal(s.saving, false, 'кнопка осталась заблокированной после отказа')
  assert.equal(s.draft.tasks[0].title, 'Переименовал', 'рабочая копия откатилась')

  // Нет сети — у ошибки нет ответа вовсе.
  globalThis.__trackerApi.trackerSave = async () => { throw new Error('Network Error') }
  assert.equal(await s.save(), false)
  assert.equal(s.ops.length, 2)
  assert.equal(s.error, 'save-failed')

  // Связь вернулась — та же пачка уходит целиком.
  globalThis.__trackerApi.trackerSave = async () => ({ data: { applied: 1, skipped: [], notified: 1, state: serverState([task('trkt:1', { title: 'Переименовал', assignees: ['stud:a'] })]) } })
  assert.equal(await s.save(), true)
  assert.equal(s.error, '')
  assert.equal(s.dirty, false)
})

test('правка, сделанная пока запрос шёл, не теряется и не уходит дважды', { timeout: 5000 }, async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Первая правка' })
  const d = deferred()
  globalThis.__trackerApi.trackerSave = () => d.promise
  const saving = s.save()
  assert.equal(s.saving, true)

  // Запрос в пути, а человек продолжает работать.
  s.stage({ op: 'task.update', id: 'trkt:1', deadline: '2026-11-01' })
  d.resolve({ data: { applied: 1, skipped: [], notified: 0, state: serverState([task('trkt:1', { title: 'Первая правка' })]) } })
  assert.equal(await saving, true)

  assert.deepEqual(s.ops, [{ op: 'task.update', id: 'trkt:1', deadline: '2026-11-01' }],
    'в пачке обязана остаться РОВНО поздняя правка')
  assert.equal(s.dirty, true, 'кнопка «Сохранить» погасла при несохранённой правке')
  assert.equal(s.draft.tasks[0].deadline, '2026-11-01', 'поздняя правка пропала с экрана')
  assert.equal(s.draft.tasks[0].title, 'Первая правка')

  // Второе сохранение везёт только её.
  globalThis.__trackerApi.trackerSave = async () => ({ data: { applied: 1, skipped: [], notified: 0, state: serverState([task('trkt:1', { title: 'Первая правка', deadline: '2026-11-01' })]) } })
  assert.equal(await s.save(), true)
  const sent = calls('trackerSave')
  assert.equal(sent.length, 2)
  assert.deepEqual(sent[1][2], [{ op: 'task.update', id: 'trkt:1', deadline: '2026-11-01' }])
  assert.equal(s.dirty, false)
})

test('двойное нажатие «Сохранить» не шлёт пачку дважды', { timeout: 5000 }, async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', assignees: ['stud:a'] })
  const d = deferred()
  globalThis.__trackerApi.trackerSave = () => d.promise
  const first = s.save()
  const second = s.save()
  // ⚠️ Счёт запросов сверяется ДО ответа сервера и БЕЗ `await` второго вызова. Первая
  // версия теста писала `await s.save()` — и без защиты в сторе не краснела, а ЗАВИСАЛА
  // навсегда: второй вызов ждал того же ответа, который тест собирался дать строкой ниже.
  // Зависший прогон хуже красного: в CI он выглядит как «сломалась машина», а не «сломали
  // защиту». Поймано обратным ходом — мутация провисела восемь минут.
  assert.equal(calls('trackerSave').length, 1,
    'второй запрос ушёл, пока шёл первый: исполнитель получил бы два письма')
  d.resolve({ data: { applied: 1, skipped: [], notified: 1, state: serverState([task('trkt:1', { assignees: ['stud:a'] })]) } })
  assert.equal(await first, true)
  assert.equal(await second, false)
  assert.equal(calls('trackerSave').length, 1)
})

test('операции, которые сервер пропустил, показываются, а не глотаются', async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Моя правка' })
  s.stage({ op: 'task.move', id: 'trkt:1', column_id: 'trkc:done', position: 0 })
  globalThis.__trackerApi.trackerSave = async () => ({
    data: {
      applied: 1, notified: 0, state: serverState([task('trkt:1', { title: 'Моя правка' })]),
      skipped: [{ i: 1, op: 'task.move', reason: 'Колонка удалена' }],
    },
  })
  assert.equal(await s.save(), true)
  assert.equal(s.skipped.length, 1, '«сохранено» при пропущенной половине пачки — неправда')
  assert.equal(s.skipped[0].reason, 'Колонка удалена')
  assert.deepEqual(s.skipped[0].source, { op: 'task.move', id: 'trkt:1', column_id: 'trkc:done', position: 0 },
    'человеку надо показать, КАКОЕ его действие не применилось')
})

// ── чужие изменения и гонки ──────────────────────────────────────────────────────────
test('чужое изменение с сервера не затирает мои несохранённые правки', async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Моя правка' })
  s.taskId = 'trkt:1'
  // Сосед тем временем завёл задачу и сохранил её.
  globalThis.__trackerApi.tracker = async () => ({ data: serverState([task('trkt:1'), task('trkt:2', { number: 2, key: 'WEB-2', title: 'Чужая' })]) })
  s.onRemoteChange('c1')
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(s.draft.tasks.length, 2, 'чужая задача не появилась')
  assert.equal(s.draft.tasks[0].title, 'Моя правка', 'моя правка стёрта чужим сохранением')
  assert.equal(s.ops.length, 1)
  assert.equal(s.remoteChanged, true, 'человек не узнал, что доску поменяли, пока он правил')

  // Сосед удалил задачу, которую я правлю: моя операция становится пустой, окно закрывается.
  globalThis.__trackerApi.tracker = async () => ({ data: serverState([task('trkt:2', { number: 2, key: 'WEB-2' })]) })
  s.onRemoteChange('c1')
  await new Promise((r) => setTimeout(r, 0))
  assert.deepEqual(s.draft.tasks.map((t) => t.id), ['trkt:2'])
  assert.equal(s.taskId, '', 'окно задачи осталось открытым на удалённой задаче')

  // Сигнал о ДРУГОЙ беседе и сигнал при закрытом трекере — не наше дело.
  const before = calls('tracker').length
  s.onRemoteChange('c-other')
  s.close()
  s.onRemoteChange('c1')
  assert.equal(calls('tracker').length, before)
})

test('ответ загрузки, начатой до сохранения, не откатывает сохранённое', { timeout: 5000 }, async () => {
  const s = await opened()
  // Страховочный опрос ушёл за миг до нажатия «Сохранить»…
  const poll = deferred()
  globalThis.__trackerApi.tracker = () => poll.promise
  const loading = s.load({ silent: true })
  // …человек назначил исполнителя и сохранил — сервер ответил первым.
  s.stage({ op: 'task.update', id: 'trkt:1', assignees: ['stud:a'] })
  globalThis.__trackerApi.trackerSave = async () => ({ data: { applied: 1, skipped: [], notified: 1, state: serverState([task('trkt:1', { assignees: ['stud:a'] })]) } })
  assert.equal(await s.save(), true)
  assert.deepEqual(s.draft.tasks[0].assignees, ['stud:a'])
  // Теперь доезжает ответ опроса — со снимком ДО сохранения.
  poll.resolve({ data: serverState([task('trkt:1')]) })
  await loading
  assert.deepEqual(s.draft.tasks[0].assignees, ['stud:a'],
    'устаревший ответ откатил доску: только что назначенный исполнитель пропал с экрана')
  assert.deepEqual(s.server.tasks[0].assignees, ['stud:a'])
})

test('из двух загрузок побеждает начатая позже, а не ответившая позже', { timeout: 5000 }, async () => {
  const s = await opened()
  const slow = deferred()
  const fast = deferred()
  globalThis.__trackerApi.tracker = () => slow.promise
  const a = s.load({ silent: true })
  globalThis.__trackerApi.tracker = () => fast.promise
  const b = s.load({ silent: true })
  fast.resolve({ data: serverState([task('trkt:1', { title: 'Свежее' })]) })
  await b
  slow.resolve({ data: serverState([task('trkt:1', { title: 'Старое' })]) })
  await a
  assert.equal(s.draft.tasks[0].title, 'Свежее')
})

test('сохранение прежней беседы не подменяет доску новой', { timeout: 5000 }, async () => {
  const s = await opened('c1')
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Правка в первой беседе' })
  const d = deferred()
  globalThis.__trackerApi.trackerSave = () => d.promise
  const saving = s.save()

  // Пока запрос шёл, открыли трекер ДРУГОЙ беседы.
  const other = serverState([task('trkt:9', { number: 9, key: 'WEB-9', title: 'Задача второй беседы' })])
  globalThis.__trackerApi.tracker = async () => ({ data: clone(other) })
  await s.openFor('c2')
  assert.deepEqual(s.ops, [], 'несохранённое первой беседы переехало во вторую')

  d.resolve({ data: { applied: 1, skipped: [], notified: 0, state: serverState([task('trkt:1', { title: 'Правка в первой беседе' })]) } })
  assert.equal(await saving, false)
  assert.equal(s.convId, 'c2')
  assert.deepEqual(s.draft.tasks.map((t) => t.id), ['trkt:9'], 'на доске второй беседы оказались задачи первой')
  assert.equal(s.saving, false)
})

test('ответ прежней сессии ничего не меняет', async () => {
  // Инвариант §4.23: выход → вход идёт без перезагрузки страницы, и ответ, пришедший
  // уже другому человеку, отклоняется транспортом с меткой `stale`.
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Правка' })
  globalThis.__trackerApi.trackerSave = async () => { throw Object.assign(new Error('stale'), { stale: true }) }
  assert.equal(await s.save(), false)
  assert.equal(s.error, '', 'чужой сессии показали ошибку сохранения, которого она не делала')
  globalThis.__trackerApi.tracker = async () => { throw Object.assign(new Error('stale'), { stale: true }) }
  await s.load()
  assert.equal(s.error, '')
})

test('выход из аккаунта не оставляет чужую доску и чужие правки в памяти', async () => {
  const s = await opened()
  s.stage({ op: 'task.update', id: 'trkt:1', title: 'Несохранённое' })
  s.reset()
  assert.equal(s.server, null)
  assert.equal(s.draft, null)
  assert.deepEqual(s.ops, [])
  assert.equal(s.open, false)
  assert.equal(s.convId, '')
})

test('ссылка из письма открывает именно ту задачу', async () => {
  setActivePinia(createPinia())
  globalThis.__trackerCalls = []
  const state = serverState([task('trkt:1'), task('trkt:2', { number: 2, key: 'WEB-2' })])
  state.projects.push({ id: 'trkp:2', key: 'DOC', title: 'Отчёт', archived: false, labels: [], position: 1,
    columns: [{ id: 'trkc:d1', title: 'К выполнению', kind: 'todo', position: 0 }] })
  state.tasks.push(task('trkt:3', { project_id: 'trkp:2', column_id: 'trkc:d1', number: 1, key: 'DOC-1' }))
  globalThis.__trackerApi = { tracker: async () => ({ data: clone(state) }) }
  const s = useTrackerStore()
  // Работа в ссылке названа одна, а задача лежит в другой — верим задаче.
  await s.openFor('c1', { projectId: 'trkp:1', taskId: 'trkt:3' })
  assert.equal(s.taskId, 'trkt:3')
  assert.equal(s.project.id, 'trkp:2', 'окно задачи открылось поверх чужой работы')
  // Задачу успели удалить — трекер открывается, окно задачи нет.
  await s.openFor('c1', { taskId: 'trkt:gone' })
  assert.equal(s.open, true)
  assert.equal(s.task, null)
})

// ── никто не пишет мимо стора ────────────────────────────────────────────────────────
function sourceFiles(dir = SRC, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) sourceFiles(p, out)
    else if (/\.(vue|js)$/.test(name)) out.push(p)
  }
  return out
}
const FILES = sourceFiles().map((p) => ({ rel: relative(SRC, p).replace(/\\/g, '/'), text: readFileSync(p, 'utf8') }))
/** Исполняемая часть: без комментариев — в них ручки названы словами. */
const code = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')

test('записывающую ручку трекера зовёт только save() стора', () => {
  const callers = FILES.filter((f) => f.rel !== 'api/endpoints.js' && /\btrackerSave\s*\(/.test(code(f.text))).map((f) => f.rel)
  assert.deepEqual(callers, ['stores/tracker.js'], 'пачку на сервер отправляет кто-то, кроме стора')
  const store = code(FILES.find((f) => f.rel === 'stores/tracker.js').text)
  assert.equal((store.match(/\btrackerSave\s*\(/g) || []).length, 1, 'в сторе больше одного места записи')
  // И это место — внутри save(): от её объявления до следующего действия.
  const body = store.slice(store.indexOf('async save()'), store.indexOf('discard()'))
  assert.match(body, /\btrackerSave\s*\(/, 'запись уехала из save() в другое действие')
})

test('у трекера ровно две записывающие ручки, и вторая — не про задачи', () => {
  // Отдельная «создать задачу» или «назначить» обошла бы пачку целиком: письмо ушло бы
  // на каждое действие. Сверяем по адресам: всё, что пишет в `/tracker`, перечислено.
  const src = code(FILES.find((f) => f.rel === 'api/endpoints.js').text)
  const found = []
  for (const m of src.matchAll(/(\w+):\s*\([^)]*\)\s*=>\s*api\.(post|put|patch|delete)\(`([^`]*)`/g)) {
    if (m[3].includes('/tracker')) found.push(`${m[2]} ${m[1]}`)
  }
  assert.deepEqual(found.sort(), ['post trackerSave', 'put trackerSettings'])
})

test('компоненты трекера сами на сервер не пишут', () => {
  // Читать подробности задачи (комментарии, историю) можно; писать — только через стор.
  const offenders = []
  for (const f of FILES.filter((x) => x.rel.startsWith('components/tracker/'))) {
    const src = code(f.text)
    for (const m of src.matchAll(/\bmessengerApi\.(\w+)/g)) {
      if (m[1] !== 'trackerTaskDetails') offenders.push(`${f.rel}: messengerApi.${m[1]}`)
    }
    if (/from\s+'@\/api\/client'|\baxios\b|\bfetch\s*\(/.test(src)) offenders.push(`${f.rel}: свой транспорт`)
  }
  assert.deepEqual(offenders, [])
})

test('проводка: кнопка зовёт save(), выход из аккаунта — reset()', () => {
  // Обещание без вызывающего — наш самый частый дефект: поведение под тестом, а в
  // продукте функцию не зовёт никто.
  const overlay = code(FILES.find((f) => f.rel === 'components/tracker/TrackerOverlay.vue').text)
  assert.match(overlay, /await tracker\.save\(\)/, 'кнопка «Сохранить» больше не сохраняет')
  assert.match(overlay, /tracker\.dirty[\s\S]{0,400}confirm\(/, 'закрытие с несохранённым больше не спрашивает')
  // Трекер сбрасывается везде, где сбрасывается переписка: это одно и то же событие.
  const auth = code(FILES.find((f) => f.rel === 'stores/auth.js').text)
  const messenger = (auth.match(/useMessengerStore\(\)\.reset\(\)/g) || []).length
  const tracker = (auth.match(/useTrackerStore\(\)\.reset\(\)/g) || []).length
  assert.ok(messenger > 0)
  assert.equal(tracker, messenger, 'в одном из путей выхода доска трекера остаётся в памяти')
  // Сигнал сокета доезжает до стора.
  const msg = code(FILES.find((f) => f.rel === 'stores/messenger.js').text)
  assert.match(msg, /onRemoteChange\(/, 'сигнал «в трекере поменяли» некому принять')
})

// ── окно трекера — отдельным чанком ──────────────────────────────────────────────────
// Замер 06.10.2026: статический импорт окна держал в чанке страницы сообщений 81 КБ кода
// трекера (310 → 230 КБ после выноса). Их качал каждый, кто открыл чат, хотя трекер
// включён в немногих беседах. Откат вносится ОДНОЙ строкой и молча: сборка проходит, всё
// работает, просто страница сообщений снова тяжелее на четверть.
const staticTrackerImports = (rel, text) =>
  [...code(text).matchAll(/^\s*import\s+[^'"\n]*from\s+['"]@\/components\/tracker\/[^'"]+['"]/gm)].map(() => rel)

test('окно трекера грузится отдельным чанком', () => {
  const offenders = FILES.filter((f) => !f.rel.startsWith('components/tracker/'))
    .flatMap((f) => staticTrackerImports(f.rel, f.text))
  assert.deepEqual(offenders, [], 'экраны трекера снова вшиты в чужой чанк статическим импортом')
  const page = code(FILES.find((f) => f.rel === 'pages/MessengerPage.vue').text)
  assert.match(page, /await import\('@\/components\/tracker\/TrackerOverlay\.vue'\)/,
    'окно трекера не подключено вовсе')
  // Чанк мог не доехать: без обработчика окно не появилось бы, а `tracker.open` осталось
  // бы истиной — повторное нажатие кнопки ничего не меняло бы.
  assert.match(page, /catch \(e\) \{\s*tracker\.close\(\)[\s\S]{0,200}?reloadOnceForChunk\([\s\S]{0,120}?toast\.error\(/,
    'сбой загрузки чанка оставляет трекер «открытым» без окна')
  // Готовая обёртка ленивого компонента запоминает отказ: после первой неудачи окно не
  // открылось бы до перезагрузки страницы, и кнопка молчала бы (живой прогон 07.10.2026).
  assert.doesNotMatch(page, /defineAsyncComponent/, 'окно трекера снова в обёртке, которая помнит отказ')
})

test('режим «кто ведёт задачи» читается заново при смене беседы под открытой панелью', () => {
  // Панель «О беседе» может пережить смену беседы (переход по ссылке на общую группу).
  // Режим прежней беседы на тумблере новой — это первый щелчок, который шлёт значение,
  // обратное показанному (нашёл Полковник 07.10.2026).
  const info = code(FILES.find((f) => f.rel === 'components/messenger/ConversationInfo.vue').text)
  assert.match(info, /watch\(\[\(\) => m\.activeId, isOwner, trackerEnabled\], readTrackerMode, \{ immediate: true \}\)/,
    'смена беседы больше не перечитывает режим трекера')
  assert.match(info, /if \(trackerModeOf !== m\.activeId\) \{ trackerModeOf = m\.activeId; trackerOpenEdit\.value = null \}/,
    'режим прежней беседы не забывается при смене')
  // И пока режим не прочитан, тумблера нет вовсе: «выключено» наугад было бы неправдой.
  assert.match(info, /v-if="isOwner && trackerEnabled && trackerOpenEdit !== null"/)
})

test('самопроверка: дословная строка статического импорта считается нарушением', () => {
  const was = "import TrackerOverlay from '@/components/tracker/TrackerOverlay.vue'\n"
  assert.deepEqual(staticTrackerImports('pages/MessengerPage.vue', was), ['pages/MessengerPage.vue'])
  const lazy = "  T.value = (await import('@/components/tracker/TrackerOverlay.vue')).default\n"
  assert.deepEqual(staticTrackerImports('pages/MessengerPage.vue', lazy), [])
})
