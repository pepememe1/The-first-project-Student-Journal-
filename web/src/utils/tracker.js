// tracker.js — логика трекера задач беседы БЕЗ интерфейса: операции, фильтры, сроки, сводка.
//
// Трекер правится у человека на экране и уходит на сервер ОДНОЙ пачкой по кнопке
// «Сохранить» (требование Ярослава 05.10.2026: «чтобы уведомления не спамили… сделать
// кнопку сохранить»). Поэтому у клиента два состояния: то, что отдал сервер, и рабочая
// копия — серверное состояние плюс накопленные операции. Обе стороны обязаны понимать
// операцию ОДИНАКОВО, иначе после сохранения доска «прыгнет»: человек видел одно, а
// записалось другое. Сервер — `server/app/routers/messenger/tracker.py`; здесь его
// зеркало (`applyOp`) и всё, что считается по состоянию.
//
// ⚠️ Всё в этом файле — чистые функции. Интерфейс их только зовёт: вёрстку тесты не
// видят, а перестановку двух условий в расчёте срока или в сжатии пачки — видят.

import { collegeDayKey, collegeParts, fromCollegeWall } from './collegeTime.js'

// Те же наборы, что на сервере (`_PRIORITIES`, `_TASK_KINDS`, `_COLUMN_KINDS`,
// `_LINK_KINDS`) — и те же пять приоритетов и типов, что у Яндекс Трекера.
export const PRIORITIES = ['blocker', 'critical', 'normal', 'minor', 'trivial']   //от срочного
export const TASK_KINDS = ['task', 'bug', 'improvement', 'epic', 'milestone']
export const COLUMN_KINDS = ['todo', 'doing', 'review', 'done']
export const LINK_KINDS = ['relates', 'blocks', 'depends']

const PRIORITY_RANK = { blocker: 0, critical: 1, normal: 2, minor: 3, trivial: 4 }

// ── идентификаторы ────────────────────────────────────────────────────────────────────
// id выдаёт КЛИЕНТ: операции одной пачки ссылаются друг на друга («создай задачу в только
// что созданной колонке»). Формат сервер проверяет жёстко — `trkX:` + шестнадцатеричное.
function hex(n) {
  const bytes = new Uint8Array(n)
  // crypto есть и в браузере, и в Node 20+ (тесты). Запасной путь — на случай совсем
  // старого движка: id тогда хуже по случайности, но трекер открывается.
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes)
  else for (let i = 0; i < n; i++) bytes[i] = Math.floor(Math.random() * 256)
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}
export const newId = (kind) => ({ project: 'trkp:', column: 'trkc:', task: 'trkt:' }[kind] || '') + hex(16)
export const smallId = () => hex(6)

// ── ключ работы («Курсовая работа» → KR) ──────────────────────────────────────────────
// Зеркало `tracker.make_key` на сервере. Расхождение не опасно (сервер проверяет ключ и
// при конфликте выводит свой), но обидно: человек увидел бы в форме один ключ, а после
// сохранения — другой. Таблица случаев одна на обе стороны (тесты py и mjs).
const TRANSLIT = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y',
  к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f',
  х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
}
export const KEY_RE = /^[A-Z][A-Z0-9]{1,9}$/
export function suggestKey(title, taken = []) {
  const latin = [...String(title || '').toLowerCase()].map((ch) => TRANSLIT[ch] ?? ch).join('')
  const words = latin.match(/[a-z0-9]+/g) || []
  let base = words.length >= 2 ? words.slice(0, 5).map((w) => w[0]).join('') : ''
  if (base.length < 2) base = (words[0] || '').slice(0, 5)
  base = base.replace(/^[0-9]+/, '').toUpperCase().slice(0, 6)
  if (base.length < 2) base = 'TASK'
  const used = new Set(taken)
  let key = base
  for (let n = 2; used.has(key); n++) key = `${base.slice(0, 8)}${n}`
  return key
}

// ── применение операции к состоянию (зеркало сервера) ─────────────────────────────────
const clone = (x) => JSON.parse(JSON.stringify(x))
export const cloneState = (s) => clone(s || { projects: [], tasks: [], members: [] })

const DEFAULT_COLUMNS = [
  ['К выполнению', 'todo'], ['В работе', 'doing'], ['На проверке', 'review'], ['Готово', 'done'],
]
// Колонки новой работы клиент заводит САМ и присылает вместе с ней: иначе их id выдал бы
// сервер, и до ответа в новую работу нельзя было бы положить ни одной задачи.
export function defaultColumns(titles = DEFAULT_COLUMNS.map((c) => c[0])) {
  return DEFAULT_COLUMNS.map(([title, kind], i) => ({ id: newId('column'), title: titles[i] || title, kind }))
}

function columnOf(state, id) {
  for (const p of state.projects) {
    const c = (p.columns || []).find((x) => x.id === id)
    if (c) return { project: p, column: c }
  }
  return null
}

/**
 * Применить операцию к состоянию НА МЕСТЕ. Объекта нет — операция молча не делает ничего:
 * так же её пропустит сервер, а здесь это случай «другой человек удалил задачу, пока я
 * правил» при перекладке моих правок на свежее состояние (`rebase`).
 */
export function applyOp(state, op, ctx = {}) {
  const now = ctx.now || ''
  const me = ctx.me || ''
  switch (op.op) {
    case 'project.create': {
      if (state.projects.some((p) => p.id === op.id)) return
      state.projects.push({
        id: op.id, key: op.key || '', title: op.title || '', description: op.description || '',
        color: op.color || '', position: state.projects.length, archived: false,
        labels: clone(op.labels || []),
        columns: (op.columns || []).map((c, i) => ({ id: c.id, title: c.title, kind: c.kind || 'todo', position: i })),
        created_by: me, created_at: now,
      })
      return
    }
    case 'project.update': {
      const p = state.projects.find((x) => x.id === op.id)
      if (!p) return
      for (const f of ['title', 'description', 'color', 'archived', 'position']) if (f in op) p[f] = op[f]
      if ('labels' in op) {
        p.labels = clone(op.labels || [])
        const alive = new Set(p.labels.map((l) => l.id))
        for (const t of state.tasks) if (t.project_id === p.id) t.labels = (t.labels || []).filter((l) => alive.has(l))
      }
      return
    }
    case 'project.delete': {
      const gone = new Set(state.tasks.filter((t) => t.project_id === op.id).map((t) => t.id))
      state.projects = state.projects.filter((p) => p.id !== op.id)
      dropTasks(state, gone)
      return
    }
    case 'column.create': {
      const p = state.projects.find((x) => x.id === op.project_id)
      if (!p || columnOf(state, op.id)) return
      p.columns = p.columns || []
      p.columns.push({ id: op.id, title: op.title || '', kind: op.kind || 'todo', position: op.position ?? p.columns.length })
      return
    }
    case 'column.update': {
      const hit = columnOf(state, op.id)
      if (!hit) return
      for (const f of ['title', 'kind', 'position']) if (f in op) hit.column[f] = op[f]
      if ('kind' in op) {
        for (const t of state.tasks) {
          if (t.column_id === op.id) t.completed_at = op.kind === 'done' ? (t.completed_at || now || 'now') : ''
        }
      }
      return
    }
    case 'column.delete': {
      const hit = columnOf(state, op.id)
      if (!hit) return
      const inside = state.tasks.filter((t) => t.column_id === op.id)
      if (inside.length) {
        const target = columnOf(state, op.move_to)
        if (!target || target.column.id === op.id || target.project.id !== hit.project.id) return
        for (const t of inside) moveTask(t, target.column, null, now)
      }
      hit.project.columns = hit.project.columns.filter((c) => c.id !== op.id)
      return
    }
    case 'task.create': {
      const hit = columnOf(state, op.column_id)
      if (!hit || state.tasks.some((t) => t.id === op.id)) return
      state.tasks.push({
        id: op.id, project_id: hit.project.id, column_id: op.column_id, number: 0, key: '',
        kind: op.kind || 'task', title: op.title || '', description: op.description || '',
        priority: op.priority || 'normal', start_date: op.start_date || '', deadline: op.deadline || '',
        estimate: Number(op.estimate || 0), spent: Number(op.spent || 0), position: op.position || 0,
        labels: clone(op.labels || []), checklist: clone(op.checklist || []),
        parent_id: op.parent_id || '', links: clone(op.links || []),
        assignees: clone(op.assignees || []), comment_count: 0,
        created_by: me, created_at: now, updated_at: now,
        completed_at: hit.column.kind === 'done' ? (now || 'now') : '',
        //Признак «ещё не на сервере»: у такой задачи нет номера, и интерфейс пишет «новая».
        unsaved: true,
      })
      return
    }
    case 'task.update': {
      const t = state.tasks.find((x) => x.id === op.id)
      if (!t) return
      for (const f of ['title', 'description', 'priority', 'kind', 'start_date', 'deadline', 'parent_id']) {
        if (f in op) t[f] = op[f]
      }
      for (const f of ['estimate', 'spent']) if (f in op) t[f] = Number(op[f] || 0)
      for (const f of ['labels', 'checklist', 'links', 'assignees']) if (f in op) t[f] = clone(op[f] || [])
      t.updated_at = now || t.updated_at
      return
    }
    case 'task.move': {
      const t = state.tasks.find((x) => x.id === op.id)
      if (!t) return
      const hit = columnOf(state, op.column_id || t.column_id)
      if (!hit || hit.project.id !== t.project_id) return
      moveTask(t, hit.column, 'position' in op ? op.position : null, now)
      return
    }
    case 'task.delete': {
      dropTasks(state, new Set([op.id]))
      return
    }
    case 'comment.add': {
      const t = state.tasks.find((x) => x.id === op.task_id)
      if (t) t.comment_count = (t.comment_count || 0) + 1
      return
    }
    case 'comment.delete': {
      const t = state.tasks.find((x) => x.id === op.task_id)
      if (t) t.comment_count = Math.max(0, (t.comment_count || 0) - 1)
      return
    }
    default:
  }
}

function moveTask(t, column, position, now) {
  if (t.column_id !== column.id) {
    t.column_id = column.id
    t.completed_at = column.kind === 'done' ? (t.completed_at || now || 'now') : ''
  }
  if (position !== null && position !== undefined) t.position = position
}

// Удаление задач: подзадача удалённой становится обычной задачей, связи на неё снимаются
// (ровно как на сервере — удаляли одну задачу, а не дерево).
function dropTasks(state, gone) {
  if (!gone.size) return
  state.tasks = state.tasks.filter((t) => !gone.has(t.id))
  for (const t of state.tasks) {
    if (gone.has(t.parent_id)) t.parent_id = ''
    if ((t.links || []).some((l) => gone.has(l.task_id))) t.links = t.links.filter((l) => !gone.has(l.task_id))
  }
}

/** Рабочая копия = серверное состояние + мои несохранённые операции поверх. */
export function rebase(serverState, ops, ctx = {}) {
  const draft = cloneState(serverState)
  for (const op of ops) applyOp(draft, op, ctx)
  return draft
}

// ── сжатие пачки ──────────────────────────────────────────────────────────────────────
// Человек правит задачу полем за полем и таскает её по доске — каждое действие даёт
// операцию. На сервер уходит сжатая пачка: правки одного объекта склеены, от серии
// перестановок осталась последняя.
//
// ⚠️ СЖИМАЕМ ТОЛЬКО ВНУТРИ ОТРЕЗКА между «структурными» операциями (создание и удаление
// работ и колонок, удаление задач). Через них склеивать нельзя: «вынес задачу из колонки →
// удалил колонку → сдвинул задачу ещё раз» после склейки перестановок превратилось бы в
// «удалил колонку с задачей внутри», и сервер удаление отклонил бы.
const BARRIERS = new Set(['project.create', 'project.delete', 'column.create', 'column.delete', 'task.delete'])
// Поля, которые можно влить в создание задачи: они ни на что не ссылаются. Родитель,
// связи и метки могли появиться ПОЗЖЕ создания — их оставляем отдельной правкой.
const PLAIN_TASK_FIELDS = new Set(['title', 'description', 'priority', 'kind', 'start_date',
  'deadline', 'estimate', 'spent', 'checklist', 'assignees'])

export function compactOps(ops) {
  const out = []
  let segmentStart = 0
  const findBack = (pred) => {
    for (let i = out.length - 1; i >= segmentStart; i--) if (pred(out[i])) return i
    return -1
  }
  for (const raw of ops) {
    const op = { ...raw }
    if (BARRIERS.has(op.op)) {
      out.push(op)
      segmentStart = out.length
      continue
    }
    if (op.op === 'task.move') {
      const i = findBack((x) => x.op === 'task.move' && x.id === op.id)
      if (i >= 0) {
        //Поздняя перестановка без колонки («сдвинул внутри той же») наследует колонку
        //ранней: иначе склейка потеряла бы сам переход между колонками.
        const merged = { ...out[i], ...op }
        out.splice(i, 1)
        out.push(merged)
        continue
      }
    } else if (op.op === 'task.update') {
      const { op: _o, id: _i, ...fields } = op
      const created = findBack((x) => x.op === 'task.create' && x.id === op.id)
      if (created >= 0 && Object.keys(fields).every((f) => PLAIN_TASK_FIELDS.has(f))) {
        out[created] = { ...out[created], ...fields }
        continue
      }
      const prev = findBack((x) => x.op === 'task.update' && x.id === op.id)
      if (prev >= 0) {
        //Склеенная правка встаёт на место ПОЗДНЕЙ: её поля могут ссылаться на то, что
        //появилось между двумя правками (метка, родитель).
        const merged = { ...out[prev], ...fields }
        out.splice(prev, 1)
        out.push(merged)
        continue
      }
    } else if (op.op === 'project.update' || op.op === 'column.update') {
      const prev = findBack((x) => x.op === op.op && x.id === op.id)
      if (prev >= 0) {
        //А здесь — на место РАННЕЙ: правка работы определяет метки, на которые сошлются
        //задачи после неё, и сдвиг вниз оставил бы эти ссылки висеть.
        out[prev] = { ...out[prev], ...op }
        continue
      }
    }
    out.push(op)
  }
  return out
}

// ── порядок и перестановка ────────────────────────────────────────────────────────────
export function tasksOfColumn(state, columnId) {
  return state.tasks.filter((t) => t.column_id === columnId)
    .sort((a, b) => (a.position - b.position) || String(a.created_at).localeCompare(String(b.created_at)))
}

/**
 * Операции для «положить задачу в колонку на место index».
 *
 * Ведущий трекер перенумеровывает всю колонку — тогда порядок однозначен и не держится
 * на случайно совпавших позициях. Исполнитель без права вести трекер двигает ТОЛЬКО свою
 * задачу (чужие перестановки сервер отклонит), поэтому ему — одна операция.
 */
export function moveOps(state, taskId, columnId, index, canManage) {
  const task = state.tasks.find((t) => t.id === taskId)
  if (!task) return []
  const row = tasksOfColumn(state, columnId).filter((t) => t.id !== taskId)
  const at = Math.max(0, Math.min(index, row.length))
  if (!canManage) return [{ op: 'task.move', id: taskId, column_id: columnId, position: at }]
  row.splice(at, 0, task)
  const ops = []
  row.forEach((t, i) => {
    if (t.id === taskId) {
      if (t.column_id !== columnId || t.position !== i) ops.push({ op: 'task.move', id: t.id, column_id: columnId, position: i })
    } else if (t.position !== i) {
      ops.push({ op: 'task.move', id: t.id, position: i })
    }
  })
  return ops
}

// ── сроки ─────────────────────────────────────────────────────────────────────────────
//Срок — время на часах КОЛЛЕДЖА (Улан-Удэ), а не устройства. До 15.10.2026 строка срока
//читалась по поясу устройства: у студента на практике в Москве «сдать до 18:00» краснело
//«просрочено» на пять часов позже, чем у преподавателя, который этот срок ставил.
export const isoDay = (d) => collegeDayKey(d)

/** «ГГГГ-ММ-ДД[TЧЧ:ММ]» → момент, когда это время наступает в колледже. null — не дата. */
export function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/.exec(String(s || ''))
  if (!m) return null
  const [y, mo, da] = [+m[1], +m[2], +m[3]]
  //⚠️ `Date` несуществующую дату НЕ отвергает, а переносит: «2026-13-45» молча
  //становится 14 февраля 2027-го. Сверяем, что получилось именно то, что просили
  //(поймано тестом в день написания; сервер проверяет дату так же строго).
  const probe = new Date(Date.UTC(y, mo - 1, da))
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== da) return null
  if (m[4] && (+m[4] > 23 || +m[5] > 59)) return null
  //Срок без времени — до КОНЦА дня: «сдать 20-го» не значит «просрочено в 00:00 20-го».
  return m[4] ? fromCollegeWall(y, mo, da, +m[4], +m[5])
    : new Date(fromCollegeWall(y, mo, da, 23, 59).getTime() + 59000)
}

/**
 * Состояние срока: '' (срока нет), 'done', 'overdue', 'today', 'soon' (до трёх суток), 'ok'.
 * Сделанная задача не бывает просроченной — иначе доска краснела бы вечно.
 */
export function deadlineState(task, now = new Date()) {
  if (!task?.deadline) return ''
  if (task.completed_at) return 'done'
  const due = parseLocal(task.deadline)
  if (!due) return ''
  if (due.getTime() < now.getTime()) return 'overdue'
  if (isoDay(due) === isoDay(now)) return 'today'
  return (due.getTime() - now.getTime()) <= 3 * 86400000 ? 'soon' : 'ok'
}

// ── фильтр и сортировка ───────────────────────────────────────────────────────────────
/**
 * Отбор задач. Пустое поле фильтра — «не ограничивать».
 * f: { q, assignee ('' | id | 'none'), priority, kind, label, status ('' | 'open' | 'done' | 'overdue') }
 */
export function filterTasks(tasks, f = {}, now = new Date()) {
  const q = String(f.q || '').trim().toLowerCase()
  return tasks.filter((t) => {
    if (q && !(`${t.key} ${t.title} ${t.description}`.toLowerCase().includes(q))) return false
    if (f.assignee === 'none') { if ((t.assignees || []).length) return false }
    else if (f.assignee && !(t.assignees || []).includes(f.assignee)) return false
    if (f.priority && t.priority !== f.priority) return false
    if (f.kind && t.kind !== f.kind) return false
    if (f.label && !(t.labels || []).includes(f.label)) return false
    if (f.status === 'open' && t.completed_at) return false
    if (f.status === 'done' && !t.completed_at) return false
    if (f.status === 'overdue' && deadlineState(t, now) !== 'overdue') return false
    return true
  })
}

/** Сортировка списка. key: key | title | priority | deadline | status | assignee | updated. */
export function sortTasks(tasks, key, dir = 1, ctx = {}) {
  const colPos = ctx.columnOrder || {}
  const names = ctx.names || {}
  const val = (t) => {
    switch (key) {
      case 'title': return t.title.toLowerCase()
      case 'priority': return PRIORITY_RANK[t.priority] ?? 9
      //Задачи без срока — в конец при любом направлении было бы честнее, но тогда
      //«по убыванию» перестало бы быть зеркалом «по возрастанию». Оставляем пустые последними
      //только при возрастании: это основной вид («что горит»).
      case 'deadline': return t.deadline || '9999'
      case 'status': return colPos[t.column_id] ?? 99
      case 'assignee': return (names[(t.assignees || [])[0]] || 'яяя').toLowerCase()
      case 'updated': return t.updated_at || ''
      default: return t.number || 1e9          //по номеру; несохранённые — в конец
    }
  }
  return [...tasks].sort((a, b) => {
    const x = val(a), y = val(b)
    if (x < y) return -dir
    if (x > y) return dir
    return (a.number || 1e9) - (b.number || 1e9)
  })
}

// ── сводка ────────────────────────────────────────────────────────────────────────────
export function summarize(state, projectId, now = new Date()) {
  const project = state.projects.find((p) => p.id === projectId)
  const tasks = state.tasks.filter((t) => t.project_id === projectId)
  const kindOf = Object.fromEntries((project?.columns || []).map((c) => [c.id, c.kind]))
  const byKind = { todo: 0, doing: 0, review: 0, done: 0 }
  const byAssignee = {}
  const out = { total: tasks.length, done: 0, overdue: 0, unassigned: 0, estimate: 0, spent: 0, byKind, byAssignee, byPriority: {} }
  for (const t of tasks) {
    const k = kindOf[t.column_id] || 'todo'
    byKind[k] += 1
    if (t.completed_at) out.done += 1
    if (deadlineState(t, now) === 'overdue') out.overdue += 1
    out.estimate += Number(t.estimate || 0)
    out.spent += Number(t.spent || 0)
    out.byPriority[t.priority] = (out.byPriority[t.priority] || 0) + 1
    if (!(t.assignees || []).length) out.unassigned += 1
    for (const uid of t.assignees || []) {
      const row = byAssignee[uid] || (byAssignee[uid] = { total: 0, done: 0, overdue: 0 })
      row.total += 1
      if (t.completed_at) row.done += 1
      if (deadlineState(t, now) === 'overdue') row.overdue += 1
    }
  }
  out.percent = out.total ? Math.round((out.done / out.total) * 100) : 0
  out.estimate = Math.round(out.estimate * 100) / 100
  out.spent = Math.round(out.spent * 100) / 100
  return out
}

/** Сколько пунктов чек-листа сделано: {done, total}. */
export function checklistProgress(task) {
  const items = task?.checklist || []
  return { done: items.filter((x) => x.done).length, total: items.length }
}

// ── шкала сроков (диаграмма Ганта) ────────────────────────────────────────────────────
/**
 * Раскладка задач по дням. Возвращает {start, days, rows:[{task, from, len, open}]}.
 * У задачи без дат строки нет — рисовать её негде. Есть только срок — отрезок в один
 * день; есть только начало — отрезок до сегодня (`open`: срок не назначен).
 */
export function timeline(tasks, now = new Date()) {
  //Метка дня — полночь UTC с числом КОЛЛЕДЖА: арифметика по суткам не зависит от пояса
  //устройства (переходы на летнее время там, где они есть, давали бы сутки в 23 часа).
  //Подписи шкалы читают её через `collegeParts`/`formatCollege` — смещение +8 ч число
  //не меняет.
  const mark = (y, mo, d) => new Date(Date.UTC(y, mo - 1, d))
  const day = (s) => {
    if (!parseLocal(s)) return null
    const [y, mo, d] = String(s).slice(0, 10).split('-').map(Number)
    return mark(y, mo, d)
  }
  const p = collegeParts(now)
  const today = mark(p.year, p.month, p.day)
  const spans = []
  for (const t of tasks) {
    const a = day(t.start_date), b = day(t.deadline)
    if (!a && !b) continue
    const from = a || b
    let to = b || (today > from ? today : from)
    if (to < from) to = from
    spans.push({ task: t, from, to, open: !b })
  }
  if (!spans.length) return { start: today, days: 0, rows: [] }
  let min = spans[0].from, max = spans[0].to
  for (const s of spans) { if (s.from < min) min = s.from; if (s.to > max) max = s.to }
  if (today < min) min = today
  if (today > max) max = today
  const start = new Date(min.getTime() - 86400000)                 //день запаса слева
  const diff = (x, y) => Math.round((x.getTime() - y.getTime()) / 86400000)
  const days = diff(max, start) + 2                                //и справа
  return {
    start, days, today: diff(today, start),
    rows: spans.map((s) => ({ task: s.task, from: diff(s.from, start), len: diff(s.to, s.from) + 1, open: s.open }))
      .sort((x, y) => (x.from - y.from) || ((x.task.number || 1e9) - (y.task.number || 1e9))),
  }
}

/** Часы человеку: 1.5 → «1,5 ч», 0 → ''. */
export function fmtHours(h, unit = 'ч') {
  const v = Number(h || 0)
  if (!v) return ''
  return `${String(Math.round(v * 100) / 100).replace('.', ',')} ${unit}`
}
