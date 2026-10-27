<script setup>
// TrackerTaskDialog — окно задачи: поля, чек-лист, подзадачи, связи, комментарии, история.
//
// 🔑 ОКНО НИЧЕГО НЕ ОТПРАВЛЯЕТ НА СЕРВЕР. Каждая правка — операция в пачке стора
// (`tracker.stage`): она сразу видна на доске и уйдёт по кнопке «Сохранить» вместе с
// остальными. Отдельной кнопки «сохранить задачу» здесь нет намеренно — их было бы две с
// разным смыслом, и человек, нажавший «сохранить» в окне, считал бы, что письмо
// исполнителю уже ушло.
//
// Кому что можно — решает сервер (`tracker.py`), здесь это только отражено, чтобы поле не
// выглядело рабочим у того, чью правку всё равно отклонят:
//   • ведущий трекер правит всё;
//   • исполнитель без этого права в СВОЕЙ задаче меняет статус, отметки чек-листа и
//     затраченное время;
//   • комментировать может любой участник.
import { ref, computed, watch } from 'vue'
import {
  X, Trash2, Plus, ListChecks, MessageSquare, History, Link2, CornerDownRight, Check, Search, Send,
} from '@lucide/vue'
import Avatar from '@/components/ui/Avatar.vue'
import GroupTag from '@/components/ui/GroupTag.vue'
import { profilePlate } from '@/theme/palette'
import { studentGroup } from '@/utils/people'
import { messengerApi } from '@/api/endpoints'
import { isStaleSession } from '@/api/responseOwner'
import { useTrackerStore } from '@/stores/tracker'
import { useConfirm } from '@/composables/useConfirm'
import { PRIORITIES, TASK_KINDS, LINK_KINDS, newId, smallId, checklistProgress, deadlineState } from '@/utils/tracker'
import { useTrackerLabels, PRIORITY_STYLE, KIND_STYLE, labelColor } from '@/composables/useTrackerLabels'

const tracker = useTrackerStore()
const L = useTrackerLabels()
const { confirm } = useConfirm()
const emit = defineEmits(['close'])

const task = computed(() => tracker.task)
const project = computed(() => (tracker.draft?.projects || []).find((p) => p.id === task.value?.project_id) || null)
const columns = computed(() => [...(project.value?.columns || [])].sort((a, b) => a.position - b.position))
const members = computed(() => tracker.memberById)
const canManage = computed(() => tracker.canManage)
const isMine = computed(() => (task.value?.assignees || []).includes(tracker.me))
// Исполнитель без права вести трекер: статус, отметки чек-листа, затраченное время.
const canProgress = computed(() => canManage.value || isMine.value)

function update(fields) {
  if (!task.value) return
  tracker.stage({ op: 'task.update', id: task.value.id, ...fields })
}

// ── название и описание: правим в своих полях, в пачку — по уходу из поля ────────────
// Операция на каждую букву раздула бы пачку (сжатие её склеит, но до него она живёт в
// памяти), а главное — перекладка на свежее состояние шла бы на каждом символе.
const title = ref('')
const description = ref('')
function commitTitle() {
  const v = title.value.trim()
  if (!v) { title.value = task.value?.title || ''; return }     //пустое название сервер отклонит
  if (v !== task.value.title) update({ title: v })
}
function commitDescription() {
  if (description.value !== (task.value.description || '')) update({ description: description.value })
}

// ── статус ───────────────────────────────────────────────────────────────────────────
function setColumn(columnId) {
  if (!task.value || columnId === task.value.column_id) return
  const count = tracker.tasks.filter((t) => t.column_id === columnId).length
  tracker.stage({ op: 'task.move', id: task.value.id, column_id: columnId, position: count })
}

// ── даты: день и (необязательно) время ───────────────────────────────────────────────
const dayOf = (s) => String(s || '').slice(0, 10)
const timeOf = (s) => (String(s || '').includes('T') ? String(s).slice(11, 16) : '')
function setDate(field, day, time = '') {
  update({ [field]: day ? (time ? `${day}T${time}` : day) : '' })
}
const due = computed(() => deadlineState(task.value))

// ── исполнители ──────────────────────────────────────────────────────────────────────
const peopleOpen = ref(false)
const peopleQuery = ref('')
// Esc при открытом списке исполнителей закрывает СПИСОК, а не окно задачи. Директива окна
// слушает `window` и нажатие с `preventDefault` не трогает — без этой строки Esc уносил
// всё окно, и человек, передумавший выбирать исполнителя, терял из виду саму задачу
// (найдено живым прогоном 06.10.2026).
function onPeopleEsc(e) {
  if (!peopleOpen.value) return
  peopleOpen.value = false
  e.preventDefault()
}
const peopleList = computed(() => {
  const q = peopleQuery.value.trim().toLowerCase()
  return tracker.members.filter((m) => !q || m.full_name.toLowerCase().includes(q))
})
function toggleAssignee(uid) {
  const cur = task.value.assignees || []
  update({ assignees: cur.includes(uid) ? cur.filter((x) => x !== uid) : [...cur, uid] })
}

// ── метки ────────────────────────────────────────────────────────────────────────────
function toggleLabel(id) {
  const cur = task.value.labels || []
  update({ labels: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] })
}

// ── чек-лист ─────────────────────────────────────────────────────────────────────────
const newItem = ref('')
const check = computed(() => checklistProgress(task.value))
function toggleItem(item) {
  update({ checklist: task.value.checklist.map((x) => (x.id === item.id ? { ...x, done: !x.done } : x)) })
}
function addItem() {
  const text = newItem.value.trim()
  if (!text) return
  update({ checklist: [...(task.value.checklist || []), { id: smallId(), text, done: false }] })
  newItem.value = ''
}
function removeItem(item) {
  update({ checklist: task.value.checklist.filter((x) => x.id !== item.id) })
}

// ── подзадачи и родитель ─────────────────────────────────────────────────────────────
const siblings = computed(() => tracker.tasks.filter((t) => t.id !== task.value?.id))
const children = computed(() => tracker.tasks.filter((t) => t.parent_id === task.value?.id))
const parent = computed(() => tracker.tasks.find((t) => t.id === task.value?.parent_id) || null)
// Родителем не может стать собственная подзадача (и её подзадачи) — цикл сервер отклонит.
const descendants = computed(() => {
  const out = new Set()
  const walk = (id) => { for (const t of tracker.tasks) if (t.parent_id === id && !out.has(t.id)) { out.add(t.id); walk(t.id) } }
  if (task.value) walk(task.value.id)
  return out
})
const parentOptions = computed(() => siblings.value.filter((t) => !descendants.value.has(t.id)))
const newSub = ref('')
function addSubtask() {
  const text = newSub.value.trim()
  if (!text || !task.value) return
  const first = columns.value[0]
  if (!first) return
  tracker.stage({
    op: 'task.create', id: newId('task'), column_id: first.id, title: text, parent_id: task.value.id,
    position: tracker.tasks.filter((t) => t.column_id === first.id).length,
  })
  newSub.value = ''
}

// ── связи ────────────────────────────────────────────────────────────────────────────
const linkKind = ref('relates')
const linkTarget = ref('')
const allTasks = computed(() => tracker.draft?.tasks || [])
const taskById = computed(() => Object.fromEntries(allTasks.value.map((t) => [t.id, t])))
// Обратные связи: кто ссылается на ЭТУ задачу (хранятся у той стороны, показываем у обеих).
const backLinks = computed(() => allTasks.value.flatMap((t) =>
  (t.links || []).filter((l) => l.task_id === task.value?.id).map((l) => ({ type: l.type, from: t }))))
function addLink() {
  if (!linkTarget.value) return
  const cur = task.value.links || []
  if (cur.some((l) => l.type === linkKind.value && l.task_id === linkTarget.value)) return
  update({ links: [...cur, { type: linkKind.value, task_id: linkTarget.value }] })
  linkTarget.value = ''
}
function removeLink(link) {
  update({ links: task.value.links.filter((l) => !(l.type === link.type && l.task_id === link.task_id)) })
}

// ── комментарии и история (с сервера) ────────────────────────────────────────────────
const tab = ref('comments')
const details = ref({ comments: [], history: [] })
const detailsLoading = ref(false)
async function loadDetails() {
  details.value = { comments: [], history: [] }
  const t = task.value
  if (!t || t.unsaved) return                //у несохранённой задачи на сервере ещё ничего нет
  detailsLoading.value = true
  try {
    const { data } = await messengerApi.trackerTaskDetails(tracker.convId, t.id)
    if (task.value?.id === t.id) details.value = data
  } catch (e) {
    if (isStaleSession(e)) return
    //Комментарии не загрузились — задача всё равно открыта и правится; честная пустота
    //с подписью лучше окна, которое не открылось.
  } finally { detailsLoading.value = false }
}
// После сохранения пачки комментарии и история на сервере изменились — перечитываем.
watch(() => tracker.savedAt, loadDetails)
// Открыли другую задачу (подзадача, связь, родитель) — окно то же, содержимое новое.
// ⚠️ Наблюдение стоит НИЖЕ объявлений `tab` и `loadDetails` намеренно: с `immediate` оно
// срабатывает прямо во время `setup`, и обращение к ещё не объявленной константе роняет
// весь компонент (наш записанный класс дефекта — «ref из мёртвой зоны»).
watch(() => task.value?.id, () => {
  title.value = task.value?.title || ''
  description.value = task.value?.description || ''
  tab.value = 'comments'
  loadDetails()
}, { immediate: true })
// Название и описание могли поменяться не здесь (перекладка на свежее состояние после
// чужого сохранения) — подхватываем, если человек сейчас не правит поле сам.
watch(() => [task.value?.title, task.value?.description], ([t, d]) => {
  if (document.activeElement?.tagName !== 'TEXTAREA') {
    title.value = t || ''
    description.value = d || ''
  }
})

const newComment = ref('')
// Мои комментарии, которые ещё в пачке: показываем сразу, с пометкой «не сохранён».
const pendingComments = computed(() => tracker.ops.filter((o) => o.op === 'comment.add' && o.task_id === task.value?.id))
const deletedCommentIds = computed(() => new Set(tracker.ops.filter((o) => o.op === 'comment.delete').map((o) => o.id)))
function addComment() {
  const body = newComment.value.trim()
  if (!body || !task.value) return
  tracker.stage({ op: 'comment.add', id: smallId(), task_id: task.value.id, body })
  newComment.value = ''
}
function removeComment(c) {
  tracker.stage({ op: 'comment.delete', id: c.id, task_id: task.value.id })
}

/** Строка истории человеку. */
function historyText(h) {
  const d = h.data || {}
  if (h.kind === 'created') return L.t('tracker.history.created')
  if (h.kind === 'moved') return L.t('tracker.history.moved', { from: d.from || '—', to: d.to || '—' })
  if (h.kind === 'assigned') return L.t('tracker.history.assigned', { name: d.name || '' })
  if (h.kind === 'unassigned') return L.t('tracker.history.unassigned', { name: d.name || '' })
  if (h.kind === 'commented') return L.t('tracker.history.commented')
  if (h.kind === 'changed') {
    const field = L.t(`tracker.history.field.${d.field}`)
    const show = (v) => {
      if (d.field === 'priority') return L.priority.value[v] || v
      if (d.field === 'kind') return L.kind.value[v] || v
      if (d.field === 'deadline' || d.field === 'start_date') return L.fmtDate(v) || '—'
      return v || '—'
    }
    //У описания, меток и связей «было → стало» не пишем: в строку оно не помещается, а
    //обрезок вводил бы в заблуждение.
    if (['description', 'labels', 'links', 'parent_id'].includes(d.field)) return L.t('tracker.history.changedPlain', { field })
    return L.t('tracker.history.changed', { field, old: show(d.old), new: show(d.new) })
  }
  return h.kind
}

async function removeTask() {
  const ok = await confirm({
    title: L.t('tracker.deleteTaskTitle'),
    message: L.t('tracker.deleteTaskText', { title: task.value.title }),
    okText: L.t('common.delete'), cancelText: L.t('common.cancel'),
  })
  if (!ok) return
  tracker.stage({ op: 'task.delete', id: task.value.id })
  emit('close')
}
</script>

<template>
  <div v-if="task" v-dialog class="fixed inset-0 z-[60] flex items-stretch justify-center sm:items-center sm:p-4"
       style="background: var(--gb-overlay)" @click.self="emit('close')">
    <div class="flex h-full w-full max-w-5xl flex-col overflow-hidden bg-card shadow-card sm:h-[min(52rem,92vh)] sm:rounded-2xl sm:border sm:border-border2">
      <!-- шапка -->
      <header class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5 sm:px-4">
        <component :is="(KIND_STYLE[task.kind] || KIND_STYLE.task).icon" class="size-5 shrink-0"
                   :style="{ color: (KIND_STYLE[task.kind] || KIND_STYLE.task).color }" />
        <span class="shrink-0 text-sm font-semibold tabular-nums text-text3">{{ task.key || L.t('tracker.newBadge') }}</span>
        <span v-if="task.unsaved" class="shrink-0 rounded-full bg-accent-glow px-2 py-0.5 text-[11px] font-semibold text-accent">
          {{ L.t('tracker.notSavedYet') }}
        </span>
        <span v-if="parent" class="flex min-w-0 items-center gap-1 truncate text-xs text-text3">
          <CornerDownRight class="size-3.5 shrink-0" />
          <button type="button" class="truncate hover:text-accent" @click="tracker.taskId = parent.id">
            {{ parent.key || L.t('tracker.newBadge') }} · {{ parent.title }}
          </button>
        </span>
        <span class="flex-1" />
        <button v-if="canManage" type="button" @click="removeTask" :aria-label="L.t('tracker.deleteTask')"
                :title="L.t('tracker.deleteTask')"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-red/10 hover:text-red">
          <Trash2 class="size-4" />
        </button>
        <button type="button" @click="emit('close')" :aria-label="L.t('common.close')"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </header>

      <div class="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        <!-- основная колонка -->
        <div class="min-w-0 flex-1 space-y-4 p-3 sm:p-4 md:overflow-y-auto">
          <textarea v-model="title" rows="1" maxlength="200" :readonly="!canManage" @blur="commitTitle"
                    @keydown.enter.prevent="$event.target.blur()" :aria-label="L.t('tracker.field.title')"
                    class="w-full resize-none rounded-lg border border-transparent bg-transparent px-2 py-1 font-title text-xl font-bold text-text outline-none focus:border-accent focus:bg-card2"
                    :class="canManage ? 'hover:border-border2' : ''" style="field-sizing: content" />

          <div>
            <p class="mb-1 px-2 text-xs font-semibold uppercase tracking-wide text-text3">{{ L.t('tracker.field.description') }}</p>
            <textarea v-model="description" rows="4" maxlength="4000" :readonly="!canManage" @blur="commitDescription"
                      :placeholder="canManage ? L.t('tracker.descriptionPlaceholder') : L.t('tracker.noDescription')"
                      class="w-full resize-y rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm leading-relaxed text-text outline-none focus:border-accent" />
          </div>

          <!-- чек-лист -->
          <div>
            <p class="mb-1.5 flex items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-text3">
              <ListChecks class="size-3.5" />{{ L.t('tracker.checklist') }}
              <span v-if="check.total" class="font-normal normal-case tracking-normal">{{ check.done }}/{{ check.total }}</span>
            </p>
            <div v-if="check.total" class="mb-2 h-1.5 overflow-hidden rounded-full bg-bg2">
              <div class="h-full rounded-full bg-accent transition-[width]" :style="{ width: (check.done / check.total * 100) + '%' }" />
            </div>
            <ul class="space-y-0.5">
              <li v-for="item in task.checklist" :key="item.id" class="group flex items-start gap-2 rounded-md px-2 py-1 hover:bg-bg2">
                <!-- Подпись — сам текст пункта: «флажок» без имени читалка экрана зачитала бы
                     десять раз подряд одинаково, и какой из них отмечаешь, было бы не понять. -->
                <button type="button" :disabled="!canProgress" @click="toggleItem(item)" role="checkbox" :aria-checked="item.done"
                        :aria-label="item.text"
                        class="mt-0.5 grid size-4 shrink-0 place-items-center rounded border"
                        :class="item.done ? 'border-accent bg-accent text-white' : 'border-border2 bg-card'">
                  <Check v-if="item.done" class="size-3" />
                </button>
                <span class="min-w-0 flex-1 break-words text-sm" :class="item.done ? 'text-text3 line-through' : 'text-text'">{{ item.text }}</span>
                <button v-if="canManage" type="button" @click="removeItem(item)" :aria-label="L.t('common.remove')"
                        class="shrink-0 text-text3 opacity-0 hover:text-red focus:opacity-100 group-hover:opacity-100">
                  <X class="size-4" />
                </button>
              </li>
            </ul>
            <form v-if="canManage" class="mt-1 flex items-center gap-2 px-2" @submit.prevent="addItem">
              <Plus class="size-4 shrink-0 text-text3" />
              <input v-model="newItem" maxlength="160" :placeholder="L.t('tracker.addChecklistItem')"
                     class="min-w-0 flex-1 border-b border-transparent bg-transparent py-1 text-sm text-text outline-none focus:border-accent" />
            </form>
          </div>

          <!-- подзадачи -->
          <div v-if="children.length || canManage">
            <p class="mb-1.5 flex items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-text3">
              <CornerDownRight class="size-3.5" />{{ L.t('tracker.subtasks') }}
            </p>
            <ul class="space-y-0.5">
              <li v-for="c in children" :key="c.id">
                <button type="button" @click="tracker.taskId = c.id"
                        class="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-bg2">
                  <span class="shrink-0 text-xs tabular-nums text-text3" :class="c.completed_at ? 'line-through' : ''">{{ c.key || L.t('tracker.newBadge') }}</span>
                  <span class="min-w-0 flex-1 truncate" :class="c.completed_at ? 'text-text3' : 'text-text'">{{ c.title }}</span>
                  <span class="shrink-0 text-xs text-text3">{{ columns.find((x) => x.id === c.column_id)?.title }}</span>
                </button>
              </li>
            </ul>
            <form v-if="canManage" class="mt-1 flex items-center gap-2 px-2" @submit.prevent="addSubtask">
              <Plus class="size-4 shrink-0 text-text3" />
              <input v-model="newSub" maxlength="200" :placeholder="L.t('tracker.addSubtask')"
                     class="min-w-0 flex-1 border-b border-transparent bg-transparent py-1 text-sm text-text outline-none focus:border-accent" />
            </form>
          </div>

          <!-- связи -->
          <div v-if="(task.links || []).length || backLinks.length || canManage">
            <p class="mb-1.5 flex items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-text3">
              <Link2 class="size-3.5" />{{ L.t('tracker.links') }}
            </p>
            <ul class="space-y-0.5">
              <li v-for="l in task.links" :key="l.type + l.task_id" class="group flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-bg2">
                <span class="shrink-0 text-xs text-text3">{{ L.link.value[l.type] }}</span>
                <button type="button" class="min-w-0 flex-1 truncate text-left text-text hover:text-accent"
                        @click="tracker.taskId = l.task_id; tracker.projectId = taskById[l.task_id]?.project_id || tracker.projectId">
                  {{ taskById[l.task_id]?.key || L.t('tracker.newBadge') }} · {{ taskById[l.task_id]?.title }}
                </button>
                <button v-if="canManage" type="button" @click="removeLink(l)" :aria-label="L.t('common.remove')"
                        class="shrink-0 text-text3 opacity-0 hover:text-red focus:opacity-100 group-hover:opacity-100"><X class="size-4" /></button>
              </li>
              <li v-for="b in backLinks" :key="'b' + b.type + b.from.id" class="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-bg2">
                <span class="shrink-0 text-xs text-text3">{{ L.linkBack.value[b.type] }}</span>
                <button type="button" class="min-w-0 flex-1 truncate text-left text-text hover:text-accent"
                        @click="tracker.taskId = b.from.id; tracker.projectId = b.from.project_id">
                  {{ b.from.key || L.t('tracker.newBadge') }} · {{ b.from.title }}
                </button>
              </li>
            </ul>
            <form v-if="canManage && allTasks.length > 1" class="mt-1 flex flex-wrap items-center gap-2 px-2" @submit.prevent="addLink">
              <select v-model="linkKind" class="rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent">
                <option v-for="k in LINK_KINDS" :key="k" :value="k">{{ L.link.value[k] }}</option>
              </select>
              <select v-model="linkTarget" class="min-w-0 flex-1 rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.pickTask') }}</option>
                <option v-for="t in allTasks.filter((x) => x.id !== task.id)" :key="t.id" :value="t.id">
                  {{ t.key || L.t('tracker.newBadge') }} · {{ t.title }}
                </option>
              </select>
              <button type="submit" :disabled="!linkTarget" class="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40">
                {{ L.t('common.add') }}
              </button>
            </form>
          </div>

          <!-- комментарии и история -->
          <div>
            <div class="mb-2 flex gap-1 border-b border-border">
              <button v-for="[key, label, icon] in [['comments', L.t('tracker.comments'), MessageSquare], ['history', L.t('tracker.historyTab'), History]]"
                      :key="key" type="button" @click="tab = key"
                      class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors"
                      :class="tab === key ? 'border-accent font-semibold text-accent' : 'border-transparent text-text3 hover:text-text'">
                <component :is="icon" class="size-4" />{{ label }}
                <span v-if="key === 'comments' && task.comment_count" class="text-xs">{{ task.comment_count }}</span>
              </button>
            </div>
            <p v-if="detailsLoading" class="px-2 py-3 text-sm text-text3">{{ L.t('common.loading') }}</p>

            <template v-else-if="tab === 'comments'">
              <ul class="space-y-2">
                <li v-for="c in details.comments.filter((x) => !deletedCommentIds.has(x.id))" :key="c.id"
                    class="group rounded-lg border border-border bg-card2 px-3 py-2">
                  <div class="mb-0.5 flex items-baseline gap-2 text-xs">
                    <span class="font-semibold text-text">{{ c.author_name || '—' }}</span>
                    <span class="text-text3">{{ L.fmtStamp(c.created_at) }}</span>
                    <button v-if="c.mine || canManage" type="button" @click="removeComment(c)"
                            class="ml-auto text-text3 opacity-0 hover:text-red focus:opacity-100 group-hover:opacity-100"
                            :aria-label="L.t('common.delete')"><Trash2 class="size-3.5" /></button>
                  </div>
                  <p class="whitespace-pre-wrap break-words text-sm text-text">{{ c.body }}</p>
                </li>
                <li v-for="c in pendingComments" :key="c.id" class="rounded-lg border border-dashed border-accent/60 bg-accent-glow/40 px-3 py-2">
                  <div class="mb-0.5 text-xs text-accent">{{ L.t('tracker.commentPending') }}</div>
                  <p class="whitespace-pre-wrap break-words text-sm text-text">{{ c.body }}</p>
                </li>
              </ul>
              <p v-if="!details.comments.length && !pendingComments.length" class="px-2 py-2 text-sm text-text3">
                {{ L.t('tracker.noComments') }}
              </p>
              <form class="mt-2 flex items-end gap-2" @submit.prevent="addComment">
                <textarea v-model="newComment" rows="2" maxlength="2000" :placeholder="L.t('tracker.commentPlaceholder')"
                          @keydown.enter.ctrl.prevent="addComment"
                          class="min-w-0 flex-1 resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />
                <button type="submit" :disabled="!newComment.trim()" :aria-label="L.t('tracker.addComment')"
                        class="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-white disabled:opacity-40">
                  <Send class="size-4" />
                </button>
              </form>
            </template>

            <template v-else>
              <p v-if="task.unsaved" class="px-2 py-2 text-sm text-text3">{{ L.t('tracker.historyAfterSave') }}</p>
              <p v-else-if="!details.history.length" class="px-2 py-2 text-sm text-text3">{{ L.t('tracker.noHistory') }}</p>
              <ul v-else class="space-y-1.5">
                <li v-for="h in details.history" :key="h.id" class="flex gap-2 px-2 text-sm">
                  <span class="w-28 shrink-0 text-xs text-text3">{{ L.fmtStamp(h.created_at) }}</span>
                  <span class="min-w-0 text-text2"><b class="font-semibold text-text">{{ h.actor_name || '—' }}</b> {{ historyText(h) }}</span>
                </li>
              </ul>
            </template>
          </div>
        </div>

        <!-- боковая колонка: поля задачи -->
        <aside class="shrink-0 space-y-3 border-t border-border bg-bg2/50 p-3 sm:p-4 md:w-72 md:overflow-y-auto md:border-l md:border-t-0">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.status') }}</span>
            <select :value="task.column_id" :disabled="!canProgress" @change="setColumn($event.target.value)"
                    class="w-full rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60">
              <option v-for="c in columns" :key="c.id" :value="c.id">{{ c.title }}</option>
            </select>
          </label>

          <div class="relative" @keydown.esc="onPeopleEsc">
            <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.assignees') }}</span>
            <button type="button" :disabled="!canManage" @click="peopleOpen = !peopleOpen"
                    class="flex min-h-[2.5rem] w-full flex-wrap items-center gap-1.5 rounded-lg border border-border2 bg-card px-2 py-1.5 text-left disabled:opacity-80"
                    :class="peopleOpen ? 'border-accent' : ''">
              <span v-for="uid in task.assignees" :key="uid" class="flex min-w-0 max-w-full items-center gap-1 rounded-full bg-bg2 py-0.5 pl-0.5 pr-2 text-xs text-text">
                <Avatar :src="members[uid]?.avatar" :name="members[uid]?.full_name || '?'" :role="members[uid]?.user_role"
                        :color="profilePlate(members[uid]?.profile_color)" :size="20" />
                <span class="min-w-0 truncate">{{ members[uid]?.full_name || '—' }}</span>
              </span>
              <span v-if="!(task.assignees || []).length" class="px-1 text-sm text-text3">{{ L.t('tracker.noAssignee') }}</span>
            </button>
            <div v-back-close v-if="peopleOpen" class="fixed inset-0 z-10" @click="peopleOpen = false" />
            <div v-if="peopleOpen" class="absolute left-0 right-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-lg border border-border2 bg-card p-1 shadow-card">
              <label class="mb-1 flex items-center gap-1.5 rounded-md border border-border2 px-2 py-1">
                <Search class="size-3.5 text-text3" />
                <input v-model="peopleQuery" :placeholder="L.t('common.search')" class="min-w-0 flex-1 bg-transparent text-sm text-text outline-none" />
              </label>
              <button v-for="m in peopleList" :key="m.user_id" type="button" @click="toggleAssignee(m.user_id)"
                      class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-bg2">
                <Avatar :src="m.avatar" :name="m.full_name" :role="m.user_role" :color="profilePlate(m.profile_color)" :size="24" />
                <span class="min-w-0 flex-1 truncate text-sm text-text">{{ m.full_name }}</span>
                <GroupTag :group="studentGroup(m)" />
                <Check v-if="(task.assignees || []).includes(m.user_id)" class="size-4 shrink-0 text-accent" />
              </button>
              <p v-if="!peopleList.length" class="px-2 py-2 text-sm text-text3">{{ L.t('messenger.nobodyFound') }}</p>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.priority') }}</span>
              <select :value="task.priority" :disabled="!canManage" @change="update({ priority: $event.target.value })"
                      class="w-full rounded-lg border border-border2 bg-card px-2 py-2 text-sm outline-none focus:border-accent disabled:opacity-60"
                      :style="{ color: (PRIORITY_STYLE[task.priority] || PRIORITY_STYLE.normal).color }">
                <option v-for="p in PRIORITIES" :key="p" :value="p" style="color: var(--gb-text)">{{ L.priority.value[p] }}</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.kind') }}</span>
              <select :value="task.kind" :disabled="!canManage" @change="update({ kind: $event.target.value })"
                      class="w-full rounded-lg border border-border2 bg-card px-2 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60">
                <option v-for="k in TASK_KINDS" :key="k" :value="k">{{ L.kind.value[k] }}</option>
              </select>
            </label>
          </div>

          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.start') }}</span>
            <input type="date" :value="dayOf(task.start_date)" :disabled="!canManage"
                   @change="setDate('start_date', $event.target.value)"
                   class="w-full rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
          </label>
          <div>
            <span class="mb-1 block text-xs font-semibold" :class="due === 'overdue' ? 'text-red' : 'text-text3'">
              {{ L.t('tracker.field.deadline') }}<template v-if="L.deadline.value[due]"> · {{ L.deadline.value[due] }}</template>
            </span>
            <div class="flex gap-2">
              <input type="date" :value="dayOf(task.deadline)" :disabled="!canManage" :aria-label="L.t('tracker.field.deadline')"
                     @change="setDate('deadline', $event.target.value, timeOf(task.deadline))"
                     class="min-w-0 flex-1 rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
              <input type="time" :value="timeOf(task.deadline)" :disabled="!canManage || !task.deadline" :aria-label="L.t('tracker.field.deadlineTime')"
                     @change="setDate('deadline', dayOf(task.deadline), $event.target.value)"
                     class="w-24 shrink-0 rounded-lg border border-border2 bg-card px-2 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.estimate') }}, {{ L.hoursUnit.value }}</span>
              <input type="number" min="0" max="9999" step="0.5" :value="task.estimate || ''" :disabled="!canManage"
                     @change="update({ estimate: Math.max(0, Number($event.target.value) || 0) })"
                     class="w-full rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.spent') }}, {{ L.hoursUnit.value }}</span>
              <input type="number" min="0" max="9999" step="0.5" :value="task.spent || ''" :disabled="!canProgress"
                     @change="update({ spent: Math.max(0, Number($event.target.value) || 0) })"
                     class="w-full rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
            </label>
          </div>

          <div v-if="(project?.labels || []).length">
            <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.labels') }}</span>
            <div class="flex flex-wrap gap-1.5">
              <button v-for="l in project.labels" :key="l.id" type="button" :disabled="!canManage" @click="toggleLabel(l.id)"
                      class="rounded-full border px-2 py-0.5 text-xs font-semibold transition-colors disabled:cursor-default"
                      :class="(task.labels || []).includes(l.id) ? 'border-transparent text-white' : 'border-border2 bg-card text-text2'"
                      :style="(task.labels || []).includes(l.id) ? { background: labelColor(l.color) } : {}">
                {{ l.title }}
              </button>
            </div>
          </div>

          <label v-if="canManage && parentOptions.length" class="block">
            <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.parent') }}</span>
            <select :value="task.parent_id" @change="update({ parent_id: $event.target.value })"
                    class="w-full rounded-lg border border-border2 bg-card px-2.5 py-2 text-sm text-text outline-none focus:border-accent">
              <option value="">{{ L.t('tracker.noParent') }}</option>
              <option v-for="t in parentOptions" :key="t.id" :value="t.id">{{ t.key || L.t('tracker.newBadge') }} · {{ t.title }}</option>
            </select>
          </label>

          <p v-if="task.created_at" class="border-t border-border pt-2 text-xs text-text3">
            {{ L.t('tracker.createdBy', { name: members[task.created_by]?.full_name || '—', when: L.fmtStamp(task.created_at) }) }}
          </p>
          <!-- Тому, кто править не может, говорим это прямо: серые поля без объяснения
               читаются как поломка. -->
          <p v-if="!canManage" class="rounded-lg bg-card px-2.5 py-2 text-xs text-text3">
            {{ isMine ? L.t('tracker.assigneeHint') : L.t('tracker.readOnlyHint') }}
          </p>
        </aside>
      </div>
    </div>
  </div>
</template>
