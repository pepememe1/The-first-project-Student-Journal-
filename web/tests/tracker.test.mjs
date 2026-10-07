// tracker.test.mjs — логика трекера задач беседы (без интерфейса).
//
// Трекер правится у человека и уходит на сервер ОДНОЙ пачкой по кнопке «Сохранить»
// (требование Ярослава 05.10.2026). Значит клиент обязан: применять операцию к своей
// копии так же, как её применит сервер; сжимать пачку, не меняя её смысла; не терять
// чужие правки при перекладке своих. Всё это — `src/utils/tracker.js`, чистые функции.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  applyOp, rebase, compactOps, moveOps, tasksOfColumn, suggestKey, newId, smallId, KEY_RE,
  deadlineState, parseLocal, filterTasks, sortTasks, summarize, timeline, checklistProgress,
  fmtHours, defaultColumns, PRIORITIES, TASK_KINDS, COLUMN_KINDS, LINK_KINDS,
} from '../src/utils/tracker.js'

const server = readFileSync(
  new URL('../../server/app/routers/messenger/tracker.py', import.meta.url), 'utf8')

function board() {
  const s = { projects: [], tasks: [], members: [] }
  applyOp(s, {
    op: 'project.create', id: 'trkp:01', key: 'KR', title: 'Курсовая работа',
    columns: [
      { id: 'trkc:todo', title: 'К выполнению', kind: 'todo' },
      { id: 'trkc:doing', title: 'В работе', kind: 'doing' },
      { id: 'trkc:done', title: 'Готово', kind: 'done' },
    ],
  })
  return s
}
const create = (id, column = 'trkc:todo', extra = {}) =>
  ({ op: 'task.create', id, column_id: column, title: `Задача ${id}`, ...extra })

// ── наборы значений совпадают с сервером ──────────────────────────────────────────────

test('🔒 приоритеты, типы и виды колонок — те же, что знает сервер', () => {
  // Разойдись списки — задача с «новым» приоритетом сохранялась бы на экране и молча
  // пропускалась сервером: человек видел бы одно, а записано было бы другое.
  const tuple = (name) => {
    const m = new RegExp(`${name}\\s*=\\s*\\(([^)]*)\\)`).exec(server)
    assert.ok(m, `в серверном модуле нет ${name} — тест ослеп`)
    return [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]).sort()
  }
  assert.deepEqual([...PRIORITIES].sort(), tuple('_PRIORITIES'))
  assert.deepEqual([...TASK_KINDS].sort(), tuple('_TASK_KINDS'))
  assert.deepEqual([...COLUMN_KINDS].sort(), tuple('_COLUMN_KINDS'))
  assert.deepEqual([...LINK_KINDS].sort(), tuple('_LINK_KINDS'))
})

test('id нового объекта проходит серверную проверку формата', () => {
  for (const [kind, prefix] of [['project', 'trkp'], ['column', 'trkc'], ['task', 'trkt']]) {
    assert.match(newId(kind), new RegExp(`^${prefix}:[0-9a-f]{8,40}$`))
  }
  assert.match(smallId(), /^[0-9a-z_-]{1,40}$/)
  assert.notEqual(newId('task'), newId('task'))
})

test('ключ работы выводится так же, как на сервере', () => {
  // Та же таблица, что в server/tests/test_tracker.py::test_make_key.
  assert.equal(suggestKey('Курсовая работа'), 'KR')
  assert.equal(suggestKey('Диплом'), 'DIPLO')
  assert.equal(suggestKey('Web-проект 2026'), 'WP2')
  assert.equal(suggestKey('!!!'), 'TASK')
  assert.equal(suggestKey('Курсовая работа', ['KR', 'KR2']), 'KR3')
  for (const t of ['Курсовая работа', 'Диплом', '2026 год', 'я']) assert.match(suggestKey(t), KEY_RE)
})

// ── применение операций ───────────────────────────────────────────────────────────────

test('созданная задача видна сразу и помечена несохранённой', () => {
  const s = board()
  applyOp(s, create('trkt:1', 'trkc:todo', { assignees: ['u1'], priority: 'critical' }), { me: 'me' })
  const t = s.tasks[0]
  assert.equal(t.project_id, 'trkp:01')
  assert.equal(t.unsaved, true, 'у несохранённой задачи нет номера — интерфейс пишет «новая»')
  assert.equal(t.key, '')
  assert.deepEqual(t.assignees, ['u1'])
})

test('переход в колонку «готово» ставит завершение, обратно — снимает', () => {
  const s = board()
  applyOp(s, create('trkt:1'))
  applyOp(s, { op: 'task.move', id: 'trkt:1', column_id: 'trkc:done' }, { now: '2026-10-05T10:00' })
  assert.ok(s.tasks[0].completed_at)
  applyOp(s, { op: 'task.move', id: 'trkt:1', column_id: 'trkc:doing' })
  assert.equal(s.tasks[0].completed_at, '')
})

test('удаление задачи: подзадача остаётся, связи снимаются', () => {
  const s = board()
  applyOp(s, create('trkt:p'))
  applyOp(s, create('trkt:c', 'trkc:todo', { parent_id: 'trkt:p' }))
  applyOp(s, create('trkt:o', 'trkc:todo', { links: [{ type: 'blocks', task_id: 'trkt:p' }] }))
  applyOp(s, { op: 'task.delete', id: 'trkt:p' })
  assert.deepEqual(s.tasks.map((t) => t.id), ['trkt:c', 'trkt:o'])
  assert.equal(s.tasks[0].parent_id, '')
  assert.deepEqual(s.tasks[1].links, [])
})

test('колонку с задачами нельзя удалить, не сказав, куда их перенести', () => {
  const s = board()
  applyOp(s, create('trkt:1', 'trkc:doing'))
  applyOp(s, { op: 'column.delete', id: 'trkc:doing' })
  assert.equal(s.projects[0].columns.length, 3, 'колонка с задачей удалилась молча')
  applyOp(s, { op: 'column.delete', id: 'trkc:doing', move_to: 'trkc:todo' })
  assert.equal(s.projects[0].columns.length, 2)
  assert.equal(s.tasks[0].column_id, 'trkc:todo')
})

test('снятая с работы метка уходит и с задач', () => {
  const s = board()
  applyOp(s, { op: 'project.update', id: 'trkp:01', labels: [{ id: 'l1', title: 'Теория', color: '' }] })
  applyOp(s, create('trkt:1', 'trkc:todo', { labels: ['l1'] }))
  applyOp(s, { op: 'project.update', id: 'trkp:01', labels: [] })
  assert.deepEqual(s.tasks[0].labels, [])
})

test('операция над исчезнувшим объектом ничего не ломает', () => {
  const s = board()
  for (const op of [
    { op: 'task.update', id: 'trkt:нет', title: 'x' }, { op: 'task.move', id: 'trkt:нет', column_id: 'trkc:todo' },
    { op: 'task.delete', id: 'trkt:нет' }, { op: 'column.update', id: 'trkc:нет', title: 'x' },
    { op: 'project.update', id: 'trkp:нет', title: 'x' }, { op: 'что.это' },
    create('trkt:1', 'trkc:нет'),
  ]) applyOp(s, op)
  assert.equal(s.tasks.length, 0)
  assert.equal(s.projects.length, 1)
})

test('🔥 перекладка: чужая правка с сервера не затирается моей несохранённой', () => {
  // Я правлю приоритет задачи 1; в это время другой человек сохранил новую задачу 2 и
  // переименовал задачу 1. После перекладки на свежее состояние видно И его, И моё.
  const mine = [{ op: 'task.update', id: 'trkt:1', priority: 'blocker' }]
  const fresh = board()
  applyOp(fresh, create('trkt:1', 'trkc:todo', { title: 'Переименовано коллегой' }))
  applyOp(fresh, create('trkt:2'))
  const draft = rebase(fresh, mine)
  assert.equal(draft.tasks.length, 2)
  assert.equal(draft.tasks[0].title, 'Переименовано коллегой')
  assert.equal(draft.tasks[0].priority, 'blocker')
  // Серверное состояние перекладкой не тронуто: это копия, а не ссылка.
  assert.equal(fresh.tasks[0].priority, 'normal')
})

// ── сжатие пачки ──────────────────────────────────────────────────────────────────────

test('правки одной задачи склеиваются, от перестановок остаётся последняя', () => {
  const ops = compactOps([
    { op: 'task.update', id: 'a', title: '1' },
    { op: 'task.move', id: 'a', column_id: 'c1', position: 0 },
    { op: 'task.update', id: 'a', title: '2', priority: 'minor' },
    { op: 'task.move', id: 'a', position: 3 },
  ])
  assert.deepEqual(ops, [
    { op: 'task.update', id: 'a', title: '2', priority: 'minor' },
    { op: 'task.move', id: 'a', column_id: 'c1', position: 3 },
  ])
})

test('простые поля вливаются в создание задачи, ссылки — нет', () => {
  const ops = compactOps([
    create('trkt:1'),
    { op: 'task.update', id: 'trkt:1', title: 'Введение', deadline: '2026-10-20' },
    { op: 'task.update', id: 'trkt:1', parent_id: 'trkt:0' },
  ])
  assert.equal(ops.length, 2)
  assert.equal(ops[0].op, 'task.create')
  assert.equal(ops[0].title, 'Введение')
  assert.equal(ops[0].deadline, '2026-10-20')
  // Родитель мог появиться ПОЗЖЕ создания — эта правка остаётся отдельной и на своём месте.
  assert.deepEqual(ops[1], { op: 'task.update', id: 'trkt:1', parent_id: 'trkt:0' })
})

test('🔥 через структурную операцию пачка НЕ сжимается', () => {
  // «Вынес задачу из колонки → удалил колонку → сдвинул задачу ещё раз». Склей мы
  // перестановки, удаление колонки пришло бы на сервер РАНЬШЕ выноса задачи из неё.
  const src = [
    { op: 'task.move', id: 'a', column_id: 'c2', position: 0 },
    { op: 'column.delete', id: 'c1' },
    { op: 'task.move', id: 'a', column_id: 'c3', position: 1 },
  ]
  assert.deepEqual(compactOps(src), src)
})

test('правка работы склеивается на РАННЕМ месте — метки определены до задач', () => {
  const ops = compactOps([
    { op: 'project.update', id: 'p', labels: [{ id: 'l1', title: 'Т' }] },
    { op: 'task.update', id: 'a', labels: ['l1'] },
    { op: 'project.update', id: 'p', title: 'Новое имя' },
  ])
  assert.deepEqual(ops.map((o) => o.op), ['project.update', 'task.update'])
  assert.equal(ops[0].title, 'Новое имя')
  assert.ok(ops[0].labels, 'метки потерялись при склейке')
})

test('сжатая пачка даёт то же состояние, что исходная', () => {
  // Свойство, ради которого сжатие вообще допустимо.
  const ops = [
    create('trkt:1'), create('trkt:2'),
    { op: 'task.update', id: 'trkt:1', title: 'А' },
    { op: 'task.move', id: 'trkt:1', column_id: 'trkc:doing', position: 0 },
    { op: 'task.update', id: 'trkt:1', priority: 'critical', title: 'Б' },
    { op: 'task.move', id: 'trkt:1', column_id: 'trkc:done', position: 0 },
    { op: 'task.update', id: 'trkt:2', assignees: ['u1'] },
    { op: 'task.delete', id: 'trkt:2' },
    { op: 'project.update', id: 'trkp:01', title: 'Диплом' },
  ]
  const strip = (s) => JSON.parse(JSON.stringify(s))
  assert.deepEqual(strip(rebase(board(), compactOps(ops))), strip(rebase(board(), ops)))
  assert.ok(compactOps(ops).length < ops.length)
})

// ── перестановка ──────────────────────────────────────────────────────────────────────

test('ведущий трекер перенумеровывает колонку, исполнитель двигает только свою задачу', () => {
  const s = board()
  for (const [i, id] of ['trkt:1', 'trkt:2', 'trkt:3'].entries()) applyOp(s, create(id, 'trkc:todo', { position: i }))
  // Третью — на первое место.
  const ops = moveOps(s, 'trkt:3', 'trkc:todo', 0, true)
  for (const op of ops) applyOp(s, op)
  assert.deepEqual(tasksOfColumn(s, 'trkc:todo').map((t) => t.id), ['trkt:3', 'trkt:1', 'trkt:2'])
  // Исполнителю — одна операция и только про его задачу: чужие перестановки сервер отклонит.
  const own = moveOps(s, 'trkt:2', 'trkc:doing', 0, false)
  assert.deepEqual(own, [{ op: 'task.move', id: 'trkt:2', column_id: 'trkc:doing', position: 0 }])
})

test('перестановка на то же место операций не даёт', () => {
  const s = board()
  applyOp(s, create('trkt:1', 'trkc:todo', { position: 0 }))
  assert.deepEqual(moveOps(s, 'trkt:1', 'trkc:todo', 0, true), [])
})

// ── сроки ─────────────────────────────────────────────────────────────────────────────

test('срок без времени действует до конца дня', () => {
  const noon = new Date(2026, 9, 20, 12, 0)
  assert.equal(deadlineState({ deadline: '2026-10-20' }, noon), 'today',
    '«сдать 20-го» не значит «просрочено в полдень 20-го»')
  assert.equal(deadlineState({ deadline: '2026-10-20T10:00' }, noon), 'overdue')
  assert.equal(deadlineState({ deadline: '2026-10-19' }, noon), 'overdue')
  assert.equal(deadlineState({ deadline: '2026-10-22' }, noon), 'soon')
  assert.equal(deadlineState({ deadline: '2026-11-22' }, noon), 'ok')
  assert.equal(deadlineState({ deadline: '' }, noon), '')
  assert.equal(deadlineState({ deadline: 'не дата' }, noon), '')
})

test('сделанная задача не бывает просроченной', () => {
  const now = new Date(2026, 9, 20, 12, 0)
  assert.equal(deadlineState({ deadline: '2026-10-01', completed_at: '2026-10-02' }, now), 'done')
})

test('дата разбирается как МЕСТНОЕ время', () => {
  const d = parseLocal('2026-10-20T18:00')
  assert.equal(d.getHours(), 18)
  assert.equal(d.getDate(), 20)
  assert.equal(parseLocal('2026-13-45'), null)
  assert.equal(parseLocal(''), null)
})

// ── фильтр, сортировка, сводка ────────────────────────────────────────────────────────

function sample() {
  const s = board()
  applyOp(s, create('trkt:1', 'trkc:todo', { assignees: ['u1'], priority: 'blocker', deadline: '2026-10-01', estimate: 4 }))
  applyOp(s, create('trkt:2', 'trkc:doing', { assignees: ['u2'], priority: 'minor', kind: 'bug', spent: 1.5 }))
  applyOp(s, create('trkt:3', 'trkc:done', { assignees: ['u1'], deadline: '2026-10-01' }))
  applyOp(s, create('trkt:4', 'trkc:todo', { title: 'Обзор литературы' }))
  s.tasks.forEach((t, i) => { t.number = i + 1; t.key = `KR-${i + 1}` })
  return s
}

test('фильтр: исполнитель, без исполнителя, статус, просрочено, поиск', () => {
  const s = sample()
  const now = new Date(2026, 9, 20)
  const ids = (f) => filterTasks(s.tasks, f, now).map((t) => t.id)
  assert.deepEqual(ids({ assignee: 'u1' }), ['trkt:1', 'trkt:3'])
  assert.deepEqual(ids({ assignee: 'none' }), ['trkt:4'])
  assert.deepEqual(ids({ status: 'open' }), ['trkt:1', 'trkt:2', 'trkt:4'])
  assert.deepEqual(ids({ status: 'done' }), ['trkt:3'])
  // Сделанная задача с прошедшим сроком в «просрочено» не попадает.
  assert.deepEqual(ids({ status: 'overdue' }), ['trkt:1'])
  assert.deepEqual(ids({ kind: 'bug' }), ['trkt:2'])
  assert.deepEqual(ids({ q: 'литерат' }), ['trkt:4'])
  assert.deepEqual(ids({ q: 'kr-2' }), ['trkt:2'], 'задачу ищут и по номеру')
  assert.deepEqual(ids({}), ['trkt:1', 'trkt:2', 'trkt:3', 'trkt:4'])
})

test('сортировка по приоритету идёт от срочного', () => {
  const s = sample()
  assert.deepEqual(sortTasks(s.tasks, 'priority').map((t) => t.priority),
    ['blocker', 'normal', 'normal', 'minor'])
  assert.deepEqual(sortTasks(s.tasks, 'key', -1).map((t) => t.number), [4, 3, 2, 1])
  // Без срока — в конце при сортировке «что горит».
  assert.equal(sortTasks(s.tasks, 'deadline')[3].deadline, '')
})

test('сводка считает выполненное, просроченное и нагрузку по людям', () => {
  const sum = summarize(sample(), 'trkp:01', new Date(2026, 9, 20))
  assert.equal(sum.total, 4)
  assert.equal(sum.done, 1)
  assert.equal(sum.percent, 25)
  assert.equal(sum.overdue, 1)
  assert.equal(sum.unassigned, 1)
  assert.deepEqual(sum.byKind, { todo: 2, doing: 1, review: 0, done: 1 })
  assert.deepEqual(sum.byAssignee.u1, { total: 2, done: 1, overdue: 1 })
  assert.equal(sum.estimate, 4)
  assert.equal(sum.spent, 1.5)
  assert.equal(summarize({ projects: [], tasks: [] }, 'нет').percent, 0, 'пустая работа — ноль, а не NaN')
})

test('чек-лист и часы', () => {
  assert.deepEqual(checklistProgress({ checklist: [{ done: true }, { done: false }] }), { done: 1, total: 2 })
  assert.deepEqual(checklistProgress({}), { done: 0, total: 0 })
  assert.equal(fmtHours(1.5), '1,5 ч')
  assert.equal(fmtHours(0), '')
})

test('шкала сроков: задачи без дат не рисуются, срок раньше начала не даёт отрицательной длины', () => {
  const now = new Date(2026, 9, 10)
  const tl = timeline([
    { id: 'a', number: 1, start_date: '2026-10-05', deadline: '2026-10-12' },
    { id: 'b', number: 2, deadline: '2026-10-15' },
    { id: 'c', number: 3, start_date: '2026-10-08' },
    { id: 'd', number: 4 },
    { id: 'e', number: 5, start_date: '2026-10-20', deadline: '2026-10-18' },
  ], now)
  assert.deepEqual(tl.rows.map((r) => r.task.id), ['a', 'c', 'b', 'e'])
  const row = Object.fromEntries(tl.rows.map((r) => [r.task.id, r]))
  assert.equal(row.a.len, 8)
  assert.equal(row.b.len, 1, 'только срок — отрезок в один день')
  assert.equal(row.c.len, 3, 'только начало — отрезок до сегодня')
  assert.equal(row.c.open, true)
  assert.ok(row.e.len >= 1, 'срок раньше начала дал отрицательную длину')
  assert.ok(tl.rows.every((r) => r.from >= 0 && r.from + r.len <= tl.days), 'отрезок вылез за шкалу')
  assert.equal(timeline([{ id: 'd' }], now).rows.length, 0)
})

test('колонки новой работы заводит клиент — с готовыми id', () => {
  const cols = defaultColumns()
  assert.deepEqual(cols.map((c) => c.kind), ['todo', 'doing', 'review', 'done'])
  assert.ok(cols.every((c) => /^trkc:[0-9a-f]{8,40}$/.test(c.id)))
})
