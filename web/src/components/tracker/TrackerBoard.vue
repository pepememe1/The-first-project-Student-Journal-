<script setup>
// TrackerBoard — доска (канбан): колонки-статусы и карточки задач с перетаскиванием.
//
// ━━ ПЕРЕТАСКИВАНИЕ СВОЁ, БЕЗ БИБЛИОТЕКИ И БЕЗ HTML5 drag-and-drop ━━
// Встроенное перетаскивание браузера на сенсорном экране не работает вовсе, а доска
// нужна и в приложении на телефоне. Поэтому тянем сами:
//   • мышь — нажал, сдвинул на несколько пикселей, тащишь;
//   • палец — ДОЛГОЕ нажатие, потом тащишь. Короткое касание с движением — это прокрутка
//     доски, и отнимать её у пальца нельзя: карточки занимают почти всю колонку.
// ⚠️ Для пальца слушаем события касания, а не указателя. У событий указателя решение
// «прокрутка или жест» принимается в момент касания (`touch-action`) и посреди жеста не
// меняется: пришлось бы запретить прокрутку по карточкам навсегда. Событие касания можно
// отменить (`preventDefault`) с того момента, как долгое нажатие сработало.
//
// Доска НИЧЕГО не пишет сама: на отпускании она сообщает «задачу такую-то — в колонку
// такую-то, на место такое-то», а операции строит и копит стор (кнопка «Сохранить»).
import { ref, computed, onBeforeUnmount } from 'vue'
import { Plus } from '@lucide/vue'
import TrackerTaskCard from '@/components/tracker/TrackerTaskCard.vue'
import { COLUMN_STYLE, useTrackerLabels } from '@/composables/useTrackerLabels'
import haptics from '@/utils/haptics'

const props = defineProps({
  columns: { type: Array, required: true },
  tasks: { type: Array, required: true },          // задачи работы (уже отфильтрованные)
  allTasks: { type: Array, default: () => [] },    // все задачи работы — для ключа родителя
  labels: { type: Array, default: () => [] },
  members: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: false },
  me: { type: String, default: '' },
})
const emit = defineEmits(['open', 'move', 'create'])
const L = useTrackerLabels()
// Фокус в строку ввода сразу при её появлении (общей директивы в проекте нет).
const vFocus = { mounted: (el) => el.focus() }

const byColumn = computed(() => {
  const map = Object.fromEntries(props.columns.map((c) => [c.id, []]))
  for (const t of props.tasks) (map[t.column_id] || (map[t.column_id] = [])).push(t)
  for (const id of Object.keys(map)) {
    map[id].sort((a, b) => (a.position - b.position) || String(a.created_at).localeCompare(String(b.created_at)))
  }
  return map
})
const keyById = computed(() => Object.fromEntries(props.allTasks.map((t) => [t.id, t.key])))

// Тащить задачу может ведущий трекер, а исполнитель — только свою (так же решит сервер).
const canDrag = (t) => props.canManage || (t.assignees || []).includes(props.me)

// ── быстрое добавление задачи в колонку ──────────────────────────────────────────────
const addIn = ref('')            // id колонки, где открыта строка ввода
const addTitle = ref('')
function openAdd(colId) { addIn.value = colId; addTitle.value = '' }
function submitAdd(colId) {
  const title = addTitle.value.trim()
  if (!title) { addIn.value = ''; return }
  emit('create', { columnId: colId, title, position: (byColumn.value[colId] || []).length })
  addTitle.value = ''            //строка остаётся открытой — задачи заводят пачкой
}

// ── перетаскивание ───────────────────────────────────────────────────────────────────
const drag = ref(null)           // {id, x, y, w, h, col, index} — пока тащим
let pending = null               // нажали, но ещё не тащим
let pressTimer = null
let suppressClick = false        // отпускание после перетаскивания не должно открыть задачу
const boardEl = ref(null)

const DRAG_START_PX = 6          // мышь: сдвиг, после которого нажатие становится перетаскиванием
const LONG_PRESS_MS = 320        // палец: сколько держать
const TOUCH_SLOP_PX = 10         // палец сдвинулся раньше срока — это прокрутка

function begin(x, y) {
  if (!pending) return
  const p = pending
  drag.value = { id: p.id, x: x - p.offX, y: y - p.offY, w: p.w, h: p.h, col: p.col, index: p.index }
  locate(x, y)
}

// Куда упадёт карточка: колонка под указателем и место между её карточками.
function locate(x, y) {
  const d = drag.value
  if (!d) return
  d.x = x - pending.offX
  d.y = y - pending.offY
  const colEl = document.elementFromPoint(x, y)?.closest?.('[data-col]')
  if (!colEl) return
  const cards = [...colEl.querySelectorAll('[data-task]')].filter((el) => el.dataset.task !== d.id)
  let index = cards.length
  for (let i = 0; i < cards.length; i++) {
    const r = cards[i].getBoundingClientRect()
    if (y < r.top + r.height / 2) { index = i; break }
  }
  d.col = colEl.dataset.col
  d.index = index
  autoScroll(x)
}

// У края доски она подъезжает сама — иначе дальнюю колонку перетаскиванием не достать.
function autoScroll(x) {
  const el = boardEl.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const edge = 48
  if (x > r.right - edge) el.scrollLeft += 18
  else if (x < r.left + edge) el.scrollLeft -= 18
}

function finish(commit) {
  const d = drag.value
  if (d && commit && d.col) {
    emit('move', { taskId: d.id, columnId: d.col, index: d.index })
    suppressClick = true
    setTimeout(() => { suppressClick = false }, 0)
  }
  drag.value = null
  pending = null
  clearTimeout(pressTimer)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerCancel)
  window.removeEventListener('touchmove', onTouchMove)
  window.removeEventListener('touchend', onTouchEnd)
  window.removeEventListener('touchcancel', onTouchCancel)
}

function arm(e, task, x, y) {
  const r = e.currentTarget.getBoundingClientRect()
  pending = {
    id: task.id, startX: x, startY: y, offX: x - r.left, offY: y - r.top, w: r.width, h: r.height,
    col: task.column_id, index: (byColumn.value[task.column_id] || []).findIndex((t) => t.id === task.id),
  }
}

// мышь и перо
function onPointerDown(e, task) {
  if (e.pointerType === 'touch') return              //палец — своими событиями, см. шапку
  if (e.button !== 0 || !canDrag(task)) return
  arm(e, task, e.clientX, e.clientY)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerCancel)
}
function onPointerMove(e) {
  if (!pending) return
  if (!drag.value) {
    if (Math.hypot(e.clientX - pending.startX, e.clientY - pending.startY) < DRAG_START_PX) return
    begin(e.clientX, e.clientY)
  }
  e.preventDefault()
  locate(e.clientX, e.clientY)
}
function onPointerUp() { finish(true) }
function onPointerCancel() { finish(false) }

// палец
function onTouchStart(e, task) {
  if (e.touches.length !== 1 || !canDrag(task)) return
  const t = e.touches[0]
  arm(e, task, t.clientX, t.clientY)
  pressTimer = setTimeout(() => {
    if (!pending) return
    begin(pending.startX, pending.startY)
    haptics.tap()                //палец действует вслепую: «взял» должно ощущаться
  }, LONG_PRESS_MS)
  window.addEventListener('touchmove', onTouchMove, { passive: false })
  window.addEventListener('touchend', onTouchEnd)
  window.addEventListener('touchcancel', onTouchCancel)
}
function onTouchMove(e) {
  if (!pending) return
  const t = e.touches[0]
  if (!drag.value) {
    //Сдвинулся раньше, чем сработало долгое нажатие, — человек прокручивает доску.
    if (Math.hypot(t.clientX - pending.startX, t.clientY - pending.startY) > TOUCH_SLOP_PX) finish(false)
    return
  }
  e.preventDefault()             //с этого момента жест наш: страница под пальцем стоит
  locate(t.clientX, t.clientY)
}
function onTouchEnd() { finish(true) }
function onTouchCancel() { finish(false) }

onBeforeUnmount(() => finish(false))

function onCardClick(task) {
  if (suppressClick) return
  emit('open', task.id)
}
</script>

<template>
  <div ref="boardEl" class="flex h-full min-h-0 gap-3 overflow-x-auto px-3 pb-3 sm:px-4">
    <section v-for="col in columns" :key="col.id" :data-col="col.id"
             class="flex max-h-full w-[17.5rem] shrink-0 flex-col rounded-xl border bg-bg2/60 transition-colors"
             :class="drag && drag.col === col.id ? 'border-accent' : 'border-border'">
      <header class="flex shrink-0 items-center gap-2 px-3 py-2.5">
        <span class="size-2 shrink-0 rounded-full"
              :style="{ background: (COLUMN_STYLE[col.kind] || COLUMN_STYLE.todo).color }" />
        <h3 class="min-w-0 flex-1 truncate text-sm font-semibold text-text" :title="L.columnKind.value[col.kind]">
          {{ col.title }}
        </h3>
        <span class="shrink-0 rounded-full bg-card px-1.5 text-[11px] tabular-nums text-text3">
          {{ (byColumn[col.id] || []).length }}
        </span>
        <button v-if="canManage" type="button" @click="openAdd(col.id)"
                :aria-label="L.t('tracker.addTask')" :title="L.t('tracker.addTask')"
                class="grid size-6 shrink-0 place-items-center rounded-md text-text3 hover:bg-card hover:text-accent">
          <Plus class="size-4" />
        </button>
      </header>

      <div class="flex min-h-[3rem] flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
        <template v-for="(task, i) in (byColumn[col.id] || [])" :key="task.id">
          <!-- Место, куда упадёт карточка. Отдельная полоса, а не раздвигание соседей:
               раздвигание меняло бы высоту колонки под указателем, и цель «убегала» бы. -->
          <div v-if="drag && drag.col === col.id && drag.index === i && drag.id !== task.id"
               class="h-1 shrink-0 rounded-full bg-accent" />
          <div :data-task="task.id"
               class="gb-tracker-card shrink-0"
               :class="[canDrag(task) ? 'cursor-grab' : 'cursor-pointer', drag && drag.id === task.id ? 'opacity-30' : '']"
               role="button" tabindex="0"
               @pointerdown="onPointerDown($event, task)"
               @touchstart.passive="onTouchStart($event, task)"
               @contextmenu.prevent
               @click="onCardClick(task)" @keydown.enter="emit('open', task.id)">
            <TrackerTaskCard :task="task" :labels="labels" :members="members"
                             :parent-key="keyById[task.parent_id] || ''" />
          </div>
        </template>
        <div v-if="drag && drag.col === col.id && drag.index >= (byColumn[col.id] || []).filter((t) => t.id !== drag.id).length"
             class="h-1 shrink-0 rounded-full bg-accent" />

        <form v-if="addIn === col.id" class="shrink-0" @submit.prevent="submitAdd(col.id)">
          <textarea v-model="addTitle" rows="2" maxlength="200" v-focus
                    :placeholder="L.t('tracker.taskTitlePlaceholder')"
                    @keydown.enter.exact.prevent="submitAdd(col.id)" @keydown.esc.stop.prevent="addIn = ''"
                    @blur="submitAdd(col.id); addIn = ''"
                    class="w-full resize-none rounded-lg border border-accent bg-card px-2.5 py-2 text-sm text-text outline-none" />
        </form>
        <button v-else-if="canManage" type="button" @click="openAdd(col.id)"
                class="flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm text-text3 transition-colors hover:bg-card hover:text-accent">
          <Plus class="size-4" />{{ L.t('tracker.addTask') }}
        </button>
      </div>
    </section>

    <!-- Карточка под указателем. `pointer-events-none` обязателен: иначе она сама
         оказывалась бы элементом под указателем, и колонку под ней было бы не найти. -->
    <div v-if="drag" class="pointer-events-none fixed left-0 top-0 z-[70] rotate-2 opacity-95 shadow-xl"
         :style="{ width: drag.w + 'px', transform: `translate(${drag.x}px, ${drag.y}px) rotate(2deg)` }">
      <TrackerTaskCard v-if="tasks.find((t) => t.id === drag.id)"
                       :task="tasks.find((t) => t.id === drag.id)" :labels="labels" :members="members" />
    </div>
  </div>
</template>

<style scoped>
/* Долгое нажатие пальцем не должно выделять текст карточки и звать меню браузера. */
.gb-tracker-card {
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  outline: none;
}
.gb-tracker-card:focus-visible { box-shadow: 0 0 0 2px var(--gb-accent); border-radius: 0.5rem; }
</style>
