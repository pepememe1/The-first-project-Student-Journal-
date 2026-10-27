<script setup>
// TrackerOverlay — трекер задач беседы на весь экран (05.10.2026, просьба Ярослава:
// «у всех появится кнопка в левом верхнем углу, при нажатии откроется меню трекера на
// весь экран… должно быть на уровне Яндекс Трекера»).
//
// Сверху вниз: шапка с кнопкой «Сохранить» → работы беседы и переключатель вида →
// фильтр → сам вид (доска, список, сроки, сводка).
//
// 🔑 «СОХРАНИТЬ» — ЕДИНСТВЕННАЯ ДВЕРЬ НА СЕРВЕР. Всё, что человек делает на доске и в
// окнах, копится в пачке стора. Кнопка отправляет её разом; тогда же назначенным уходит
// по одному письму. Поэтому несохранённое здесь показано настойчиво: счётчик, полоса,
// вопрос при закрытии — человек, раздавший двадцать задач и закрывший окно, должен
// узнать, что не раздал ни одной.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  X, Save, Undo2, Plus, Search, SquareKanban, List, ChartGantt, ChartPie, Settings2,
  TriangleAlert, RotateCw, Archive,
} from '@lucide/vue'
import { useTrackerStore } from '@/stores/tracker'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { isStaleSession } from '@/api/responseOwner'
import { PRIORITIES, TASK_KINDS, filterTasks, moveOps, newId } from '@/utils/tracker'
import { useTrackerLabels, labelColor } from '@/composables/useTrackerLabels'
import TrackerBoard from '@/components/tracker/TrackerBoard.vue'
import TrackerList from '@/components/tracker/TrackerList.vue'
import TrackerTimeline from '@/components/tracker/TrackerTimeline.vue'
import TrackerSummary from '@/components/tracker/TrackerSummary.vue'
import TrackerTaskDialog from '@/components/tracker/TrackerTaskDialog.vue'
import TrackerProjectDialog from '@/components/tracker/TrackerProjectDialog.vue'

const tracker = useTrackerStore()
const L = useTrackerLabels()
const { confirm } = useConfirm()
const toast = useToast()

const VIEWS = computed(() => [
  ['board', L.t('tracker.view.board'), SquareKanban],
  ['list', L.t('tracker.view.list'), List],
  ['timeline', L.t('tracker.view.timeline'), ChartGantt],
  ['summary', L.t('tracker.view.summary'), ChartPie],
])

const projectDialog = ref(null)          // null | '' (новая работа) | id работы
const showArchived = ref(false)
const filtersOpen = ref(false)

const visibleTasks = computed(() => filterTasks(tracker.tasks, tracker.filter))
const errorText = computed(() => {
  if (!tracker.error) return ''
  if (tracker.error === 'load-failed') return L.t('tracker.loadFailed')
  if (tracker.error === 'save-failed') return L.t('tracker.saveFailed')
  return tracker.error                    //причину отказа сервер называет сам
})

// ── действия доски → операции в пачку ────────────────────────────────────────────────
function onCreate({ columnId, title, position }) {
  tracker.stage({ op: 'task.create', id: newId('task'), column_id: columnId, title, position })
}
function onMove({ taskId, columnId, index }) {
  tracker.stage(moveOps(tracker.draft, taskId, columnId, index, tracker.canManage))
}
function quickCreate() {
  const first = tracker.columns[0]
  if (!first) return
  const id = newId('task')
  tracker.stage({
    op: 'task.create', id, column_id: first.id, title: L.t('tracker.untitledTask'),
    position: tracker.tasks.filter((t) => t.column_id === first.id).length,
  })
  tracker.taskId = id                    //сразу в окно задачи: название и поля заполняют там
}
function applyFilter(f) {
  tracker.resetFilter()
  Object.assign(tracker.filter, f)
  tracker.view = 'list'                  //из сводки — к списку отобранного
}

// ── сохранить / отменить / закрыть ───────────────────────────────────────────────────
async function save() {
  const ok = await tracker.save()
  if (!ok) return
  const parts = [L.t('tracker.saved')]
  if (tracker.notified) parts.push(L.t('tracker.lettersSent', { n: tracker.notified }))
  toast.success(parts.join(' '))
}
async function discard() {
  const ok = await confirm({
    title: L.t('tracker.discardTitle'), message: L.t('tracker.discardText', { n: tracker.ops.length }),
    okText: L.t('tracker.discard'), cancelText: L.t('common.cancel'),
  })
  if (ok) tracker.discard()
}
async function requestClose() {
  if (tracker.dirty) {
    // ⚠️ «ОК» здесь — ВЕРНУТЬСЯ, а не закрыть: Esc и щелчок мимо в окне подтверждения
    // означают отмену, и отменой обязано быть безопасное действие. Иначе случайный Esc
    // стирал бы несохранённое распределение задач.
    const leave = await confirm({
      title: L.t('tracker.unsavedTitle'), message: L.t('tracker.unsavedText', { n: tracker.ops.length }),
      okText: L.t('tracker.closeWithoutSaving'), cancelText: L.t('tracker.backToTracker'),
    })
    if (!leave) return
    tracker.discard()
  }
  tracker.close()
}

// ── включение трекера владельцем (если открыли выключенный) ──────────────────────────
const enabling = ref(false)
async function enable() {
  enabling.value = true
  try { await tracker.setSettings({ enabled: true }) }
  catch (e) {
    //Отказ прежней сессии (вышли и вошли другим) новому человеку не показываем.
    if (!isStaleSession(e)) toast.error(e?.response?.data?.detail || L.t('tracker.saveFailed'))
  }
  finally { enabling.value = false }
}

// ── страховочный опрос ───────────────────────────────────────────────────────────────
// Основной сигнал — сокет (`messenger.js` зовёт `onRemoteChange`). Опрос — на случай,
// когда сокета нет (он падает на плохой сети): без него чужие правки не появлялись бы до
// перезахода. В скрытой вкладке не ходим: её никто не видит.
const POLL_MS = 30000
let pollTimer = null
onMounted(() => {
  pollTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.hidden) return
    if (!tracker.saving) tracker.load({ silent: true })
  }, POLL_MS)
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })

// Закрытие вкладки с несохранённым — предупреждение браузера (текст он показывает свой).
function onBeforeUnload(e) {
  if (!tracker.dirty) return
  e.preventDefault()
  e.returnValue = ''
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

const skippedText = (s) => {
  const title = s.source?.title || ''
  return title ? `«${title}» — ${s.reason}` : s.reason
}
</script>

<template>
  <!-- `@click.self` нужен ради Esc: директива окна «щёлкает мимо», и срабатывает тот же
       вопрос про несохранённое, что и у крестика. Самой подложки не видно — окно во весь
       экран. -->
  <div v-dialog data-dialog-guard="self" class="fixed inset-0 z-50 flex flex-col bg-bg" @click.self="requestClose"
       style="padding-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom)">
    <!-- ── шапка ─────────────────────────────────────────────────────────────────── -->
    <header class="flex shrink-0 items-center gap-2 border-b border-border bg-card px-3 py-2 sm:px-4">
      <SquareKanban class="size-5 shrink-0 text-accent" />
      <div class="min-w-0 flex-1">
        <h2 class="truncate font-title text-base font-bold leading-tight text-text">{{ L.t('tracker.title') }}</h2>
        <p class="truncate text-xs text-text3">{{ tracker.draft?.title || '' }}</p>
      </div>
      <!-- Несохранённое: счётчик, «отменить», «сохранить». На телефоне подписи кнопок
           прячутся, остаются значки — шапка там в одну строку. -->
      <template v-if="tracker.dirty">
        <span class="hidden shrink-0 text-xs font-semibold text-orange sm:inline">
          {{ L.t('tracker.unsavedCount', { n: tracker.ops.length }) }}
        </span>
        <button type="button" @click="discard" :disabled="tracker.saving" :title="L.t('tracker.discard')"
                class="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-border2 px-2.5 text-sm text-text2 hover:bg-bg2 disabled:opacity-50">
          <Undo2 class="size-4" /><span class="hidden sm:inline">{{ L.t('tracker.discard') }}</span>
        </button>
      </template>
      <button v-if="tracker.enabled" type="button" @click="save" :disabled="!tracker.dirty || tracker.saving"
              class="relative flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition-colors disabled:cursor-default"
              :class="tracker.dirty ? 'bg-accent text-white hover:bg-accent2' : 'bg-bg2 text-text3'">
        <Save class="size-4" />
        <span>{{ tracker.saving ? L.t('tracker.saving') : L.t('common.save') }}</span>
        <span v-if="tracker.dirty" class="grid h-5 min-w-5 place-items-center rounded-full bg-white/25 px-1 text-[11px] tabular-nums sm:hidden">
          {{ tracker.ops.length }}
        </span>
      </button>
      <button type="button" @click="requestClose" :aria-label="L.t('common.close')"
              class="grid size-9 shrink-0 place-items-center rounded-lg text-text3 hover:bg-bg2 hover:text-text">
        <X class="size-5" />
      </button>
    </header>

    <!-- ── сообщения: ошибка, чужие изменения, пропущенные операции ───────────────── -->
    <div v-if="errorText" class="flex shrink-0 items-center gap-2 border-b border-red/30 bg-red/10 px-4 py-2 text-sm text-red" role="alert">
      <TriangleAlert class="size-4 shrink-0" /><span class="min-w-0 flex-1">{{ errorText }}</span>
      <button type="button" class="shrink-0 underline" @click="tracker.error = ''">{{ L.t('common.close') }}</button>
    </div>
    <div v-if="tracker.remoteChanged" class="flex shrink-0 items-center gap-2 border-b border-border bg-accent-glow px-4 py-2 text-sm text-text2">
      <RotateCw class="size-4 shrink-0 text-accent" /><span class="min-w-0 flex-1">{{ L.t('tracker.remoteChanged') }}</span>
      <button type="button" class="shrink-0 text-accent underline" @click="tracker.remoteChanged = false">{{ L.t('common.ok') }}</button>
    </div>
    <div v-if="tracker.skipped.length" class="shrink-0 border-b border-orange/30 bg-orange/10 px-4 py-2 text-sm text-text2" role="status">
      <div class="flex items-center gap-2">
        <TriangleAlert class="size-4 shrink-0 text-orange" />
        <span class="min-w-0 flex-1 font-semibold">{{ L.t('tracker.skippedTitle', { n: tracker.skipped.length }) }}</span>
        <button type="button" class="shrink-0 underline" @click="tracker.skipped = []">{{ L.t('common.close') }}</button>
      </div>
      <ul class="mt-1 max-h-24 list-disc overflow-y-auto pl-9 text-xs">
        <li v-for="(s, i) in tracker.skipped.slice(0, 20)" :key="i">{{ skippedText(s) }}</li>
      </ul>
    </div>

    <!-- ── состояния без доски ────────────────────────────────────────────────────── -->
    <div v-if="tracker.loading && !tracker.draft" class="grid flex-1 place-items-center text-sm text-text3">
      {{ L.t('common.loading') }}
    </div>
    <div v-else-if="!tracker.draft" class="grid flex-1 place-items-center p-6 text-center text-sm text-text3">
      <div>
        <p>{{ L.t('tracker.loadFailed') }}</p>
        <button type="button" class="mt-3 rounded-lg border border-border2 px-3 py-2 text-text2 hover:bg-bg2" @click="tracker.load()">
          {{ L.t('tracker.retry') }}
        </button>
      </div>
    </div>
    <div v-else-if="!tracker.enabled" class="grid flex-1 place-items-center p-6 text-center">
      <div class="max-w-md">
        <SquareKanban class="mx-auto mb-3 size-10 text-text3" />
        <p class="font-title text-lg font-bold text-text">{{ L.t('tracker.offTitle') }}</p>
        <p class="mt-1 text-sm text-text3">
          {{ tracker.canConfigure ? L.t('tracker.offOwnerText') : L.t('tracker.offMemberText') }}
        </p>
        <button v-if="tracker.canConfigure" type="button" :disabled="enabling" @click="enable"
                class="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
          {{ L.t('tracker.enable') }}
        </button>
      </div>
    </div>

    <template v-else>
      <!-- ── работы и вид ─────────────────────────────────────────────────────────── -->
      <div class="flex shrink-0 flex-col gap-2 border-b border-border bg-card px-3 py-2 sm:px-4 lg:flex-row lg:items-center">
        <div class="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
          <button v-for="p in tracker.projects" :key="p.id" type="button" @click="tracker.projectId = p.id"
                  class="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 text-sm transition-colors"
                  :class="tracker.project?.id === p.id ? 'border-accent bg-accent-glow font-semibold text-text' : 'border-border2 text-text2 hover:bg-bg2'">
            <span class="size-2 rounded-full" :style="{ background: labelColor(p.color) }" />
            <span class="font-mono text-[11px] text-text3">{{ p.key }}</span>
            <span class="max-w-[12rem] truncate">{{ p.title }}</span>
          </button>
          <button v-if="tracker.canManage" type="button" @click="projectDialog = ''"
                  class="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-dashed border-border2 px-2.5 text-sm text-accent hover:bg-bg2">
            <Plus class="size-4" />{{ L.t('tracker.newWork') }}
          </button>
          <button v-if="tracker.canManage && tracker.project" type="button" @click="projectDialog = tracker.project.id"
                  :aria-label="L.t('tracker.workSettings')" :title="L.t('tracker.workSettings')"
                  class="grid size-8 shrink-0 place-items-center rounded-lg text-text3 hover:bg-bg2 hover:text-text">
            <Settings2 class="size-4" />
          </button>
          <button v-if="tracker.archivedProjects.length" type="button" @click="showArchived = !showArchived"
                  class="flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-text3 hover:bg-bg2"
                  :class="showArchived ? 'text-accent' : ''">
            <Archive class="size-4" />{{ tracker.archivedProjects.length }}
          </button>
        </div>
        <div class="flex shrink-0 items-center gap-1 overflow-x-auto">
          <button v-for="[key, label, icon] in VIEWS" :key="key" type="button" @click="tracker.view = key"
                  class="flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-sm transition-colors"
                  :class="tracker.view === key ? 'bg-bg2 font-semibold text-text' : 'text-text3 hover:text-text'">
            <component :is="icon" class="size-4" /><span class="hidden sm:inline">{{ label }}</span>
          </button>
        </div>
      </div>

      <!-- Архивные работы: открыть, чтобы вернуть из архива. -->
      <div v-if="showArchived && tracker.archivedProjects.length"
           class="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-bg2 px-4 py-2 text-sm text-text2">
        <span class="text-xs text-text3">{{ L.t('tracker.archived') }}:</span>
        <button v-for="p in tracker.archivedProjects" :key="p.id" type="button" @click="projectDialog = p.id"
                class="rounded-lg border border-border2 bg-card px-2 py-1 text-xs hover:border-accent">
          <span class="font-mono text-text3">{{ p.key }}</span> {{ p.title }}
        </button>
      </div>

      <!-- ── нет ни одной работы ──────────────────────────────────────────────────── -->
      <div v-if="!tracker.project" class="grid flex-1 place-items-center p-6 text-center">
        <div class="max-w-md">
          <p class="font-title text-lg font-bold text-text">{{ L.t('tracker.noWorksTitle') }}</p>
          <p class="mt-1 text-sm text-text3">
            {{ tracker.canManage ? L.t('tracker.noWorksManagerText') : L.t('tracker.noWorksMemberText') }}
          </p>
          <button v-if="tracker.canManage" type="button" @click="projectDialog = ''"
                  class="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2">
            <Plus class="size-4" />{{ L.t('tracker.createWork') }}
          </button>
        </div>
      </div>

      <template v-else>
        <!-- ── фильтр ─────────────────────────────────────────────────────────────── -->
        <div v-if="tracker.view !== 'summary'" class="shrink-0 px-3 py-2 sm:px-4">
          <div class="flex flex-wrap items-center gap-2">
            <label class="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border border-border2 bg-card px-2.5 sm:max-w-xs">
              <Search class="size-4 shrink-0 text-text3" />
              <input v-model="tracker.filter.q" :placeholder="L.t('tracker.searchPlaceholder')"
                     class="min-w-0 flex-1 bg-transparent text-sm text-text outline-none" />
            </label>
            <button type="button" @click="tracker.filter.assignee = tracker.filter.assignee === tracker.me ? '' : tracker.me"
                    class="h-9 shrink-0 rounded-lg border px-3 text-sm transition-colors"
                    :class="tracker.filter.assignee === tracker.me ? 'border-accent bg-accent-glow font-semibold text-accent' : 'border-border2 text-text2 hover:bg-bg2'">
              {{ L.t('tracker.myTasks') }}
            </button>
            <button type="button" @click="filtersOpen = !filtersOpen"
                    class="h-9 shrink-0 rounded-lg border px-3 text-sm transition-colors lg:hidden"
                    :class="filtersOpen || tracker.filterActive ? 'border-accent text-accent' : 'border-border2 text-text2'">
              {{ L.t('tracker.filters') }}
            </button>
            <div class="flex-wrap items-center gap-2 lg:flex" :class="filtersOpen ? 'flex w-full' : 'hidden'">
              <select v-model="tracker.filter.assignee" :aria-label="L.t('tracker.field.assignees')"
                      class="h-9 max-w-[11rem] rounded-lg border border-border2 bg-card px-2 text-sm text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.anyAssignee') }}</option>
                <option value="none">{{ L.t('tracker.noAssignee') }}</option>
                <option v-for="m in tracker.members" :key="m.user_id" :value="m.user_id">{{ m.full_name }}</option>
              </select>
              <select v-model="tracker.filter.status" :aria-label="L.t('tracker.field.status')"
                      class="h-9 rounded-lg border border-border2 bg-card px-2 text-sm text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.anyStatus') }}</option>
                <option value="open">{{ L.t('tracker.statusOpen') }}</option>
                <option value="done">{{ L.t('tracker.statusDone') }}</option>
                <option value="overdue">{{ L.t('tracker.deadline.overdue') }}</option>
              </select>
              <select v-model="tracker.filter.priority" :aria-label="L.t('tracker.field.priority')"
                      class="h-9 rounded-lg border border-border2 bg-card px-2 text-sm text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.anyPriority') }}</option>
                <option v-for="p in PRIORITIES" :key="p" :value="p">{{ L.priority.value[p] }}</option>
              </select>
              <select v-model="tracker.filter.kind" :aria-label="L.t('tracker.field.kind')"
                      class="h-9 rounded-lg border border-border2 bg-card px-2 text-sm text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.anyKind') }}</option>
                <option v-for="k in TASK_KINDS" :key="k" :value="k">{{ L.kind.value[k] }}</option>
              </select>
              <select v-if="(tracker.project.labels || []).length" v-model="tracker.filter.label" :aria-label="L.t('tracker.field.labels')"
                      class="h-9 max-w-[10rem] rounded-lg border border-border2 bg-card px-2 text-sm text-text outline-none focus:border-accent">
                <option value="">{{ L.t('tracker.anyLabel') }}</option>
                <option v-for="l in tracker.project.labels" :key="l.id" :value="l.id">{{ l.title }}</option>
              </select>
              <button v-if="tracker.filterActive" type="button" @click="tracker.resetFilter()"
                      class="h-9 rounded-lg px-2 text-sm text-text3 underline hover:text-text">{{ L.t('tracker.resetFilter') }}</button>
            </div>
            <span class="flex-1" />
            <!-- Число показанных из всех: отфильтрованная доска без подписи читается
                 как «задач нет». -->
            <span class="shrink-0 text-xs text-text3">
              {{ tracker.filterActive ? L.t('tracker.shownOf', { shown: visibleTasks.length, total: tracker.tasks.length })
                                      : L.t('tracker.tasksCount', { n: tracker.tasks.length }) }}
            </span>
            <button v-if="tracker.canManage" type="button" @click="quickCreate"
                    class="flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 text-sm font-semibold text-white hover:bg-accent2">
              <Plus class="size-4" /><span class="hidden sm:inline">{{ L.t('tracker.newTask') }}</span>
            </button>
          </div>
        </div>

        <!-- ── вид ────────────────────────────────────────────────────────────────── -->
        <div class="min-h-0 flex-1" :class="tracker.view === 'summary' ? 'pt-3' : ''">
          <TrackerBoard v-if="tracker.view === 'board'" :columns="tracker.columns" :tasks="visibleTasks"
                        :all-tasks="tracker.tasks" :labels="tracker.project.labels || []" :members="tracker.memberById"
                        :can-manage="tracker.canManage" :me="tracker.me"
                        @open="tracker.taskId = $event" @move="onMove" @create="onCreate" />
          <TrackerList v-else-if="tracker.view === 'list'" :columns="tracker.columns" :tasks="visibleTasks"
                       :members="tracker.memberById" @open="tracker.taskId = $event" />
          <TrackerTimeline v-else-if="tracker.view === 'timeline'" :tasks="visibleTasks" @open="tracker.taskId = $event" />
          <TrackerSummary v-else :state="tracker.draft" :project-id="tracker.project.id" :members="tracker.memberById"
                          @filter="applyFilter" />
        </div>
      </template>
    </template>

    <TrackerTaskDialog v-if="tracker.task" @close="tracker.taskId = ''" />
    <TrackerProjectDialog v-if="projectDialog !== null" :project-id="projectDialog"
                          @close="projectDialog = null" @created="tracker.projectId = $event" />
  </div>
</template>
