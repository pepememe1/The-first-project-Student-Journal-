<script setup>
// TrackerProjectDialog — «работа»: создание новой либо настройка существующей (название,
// колонки-статусы, метки, архив, удаление).
//
// Как и окно задачи, на сервер ничего не шлёт: каждое действие встаёт операцией в пачку
// стора и уходит по общей кнопке «Сохранить».
import { ref, computed } from 'vue'
import { X, Plus, Trash2, ArrowUp, ArrowDown, Archive, ArchiveRestore } from '@lucide/vue'
import { useTrackerStore } from '@/stores/tracker'
import { useConfirm } from '@/composables/useConfirm'
import { COLUMN_KINDS, KEY_RE, defaultColumns, newId, smallId, suggestKey } from '@/utils/tracker'
import { useTrackerLabels, LABEL_COLORS, labelColor, COLUMN_STYLE } from '@/composables/useTrackerLabels'

const props = defineProps({
  projectId: { type: String, default: '' },      // пусто — создаём новую работу
})
const emit = defineEmits(['close', 'created'])
const tracker = useTrackerStore()
const L = useTrackerLabels()
const { confirm } = useConfirm()

const project = computed(() => (tracker.draft?.projects || []).find((p) => p.id === props.projectId) || null)
const creating = computed(() => !props.projectId)
const COLOR_IDS = Object.keys(LABEL_COLORS)

// ── создание ─────────────────────────────────────────────────────────────────────────
const title = ref('')
const description = ref('')
const color = ref('')
const keyDraft = ref('')
const keyTouched = ref(false)            //ключ правили руками — больше не подставляем свой
const takenKeys = computed(() => (tracker.draft?.projects || []).map((p) => p.key).filter(Boolean))
const key = computed(() => (keyTouched.value ? keyDraft.value : suggestKey(title.value, takenKeys.value)))
const keyError = computed(() => {
  if (!keyTouched.value) return ''
  if (!KEY_RE.test(keyDraft.value)) return L.t('tracker.keyFormat')
  if (takenKeys.value.includes(keyDraft.value)) return L.t('tracker.keyTaken')
  return ''
})
function onKeyInput(e) {
  keyTouched.value = true
  keyDraft.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10)
}
function create() {
  const name = title.value.trim()
  if (!name || keyError.value) return
  const id = newId('project')
  tracker.stage({
    op: 'project.create', id, key: key.value, title: name, description: description.value.trim(),
    color: color.value,
    //Колонки заводим сами и шлём вместе с работой: их id нужны сразу, чтобы в ту же
    //пачку можно было положить задачи.
    columns: defaultColumns(['todo', 'doing', 'review', 'done'].map((k) => L.t(`tracker.defaultColumn.${k}`))),
  })
  emit('created', id)
  emit('close')
}

// ── правка существующей ──────────────────────────────────────────────────────────────
const tab = ref('main')
const update = (fields) => tracker.stage({ op: 'project.update', id: props.projectId, ...fields })
const editTitle = ref(project.value?.title || '')
const editDescription = ref(project.value?.description || '')
function commitTitle() {
  const v = editTitle.value.trim()
  if (!v) { editTitle.value = project.value?.title || ''; return }
  if (v !== project.value.title) update({ title: v })
}
function commitDescription() {
  if (editDescription.value !== (project.value.description || '')) update({ description: editDescription.value })
}

// колонки
const columns = computed(() => [...(project.value?.columns || [])].sort((a, b) => a.position - b.position))
const countIn = (colId) => (tracker.draft?.tasks || []).filter((t) => t.column_id === colId).length
function renameColumn(col, e) {
  const v = e.target.value.trim()
  if (!v) { e.target.value = col.title; return }
  if (v !== col.title) tracker.stage({ op: 'column.update', id: col.id, title: v })
}
function shiftColumn(index, delta) {
  const list = columns.value
  const other = list[index + delta]
  if (!other) return
  //Меняем местами соседей и перенумеровываем весь ряд: позиции у старых работ могли
  //совпадать, и обмен двух чисел не изменил бы порядка.
  const order = list.map((c) => c.id)
  order.splice(index, 1)
  order.splice(index + delta, 0, list[index].id)
  order.forEach((id, i) => {
    if (list.find((c) => c.id === id).position !== i) tracker.stage({ op: 'column.update', id, position: i })
  })
}
function addColumn() {
  tracker.stage({
    op: 'column.create', id: newId('column'), project_id: props.projectId,
    title: L.t('tracker.newColumn'), kind: 'todo', position: columns.value.length,
  })
}
const moveTo = ref({})                   // колонка → куда перенести её задачи при удалении
function removeColumn(col) {
  const n = countIn(col.id)
  if (n && !moveTo.value[col.id]) return
  tracker.stage({ op: 'column.delete', id: col.id, ...(n ? { move_to: moveTo.value[col.id] } : {}) })
}

// метки
const labels = computed(() => project.value?.labels || [])
const newLabel = ref('')
const newLabelColor = ref('blue')
const setLabels = (list) => update({ labels: list })
function addLabel() {
  const name = newLabel.value.trim()
  if (!name) return
  setLabels([...labels.value, { id: smallId(), title: name, color: newLabelColor.value }])
  newLabel.value = ''
}
function patchLabel(label, fields) {
  setLabels(labels.value.map((l) => (l.id === label.id ? { ...l, ...fields } : l)))
}
function renameLabel(label, e) {
  const v = e.target.value.trim()
  if (!v) { e.target.value = label.title; return }
  if (v !== label.title) patchLabel(label, { title: v })
}

async function removeProject() {
  const n = (tracker.draft?.tasks || []).filter((t) => t.project_id === props.projectId).length
  const ok = await confirm({
    title: L.t('tracker.deleteWorkTitle'),
    message: L.t('tracker.deleteWorkText', { title: project.value.title, n }),
    okText: L.t('common.delete'), cancelText: L.t('common.cancel'),
  })
  if (!ok) return
  tracker.stage({ op: 'project.delete', id: props.projectId })
  emit('close')
}
</script>

<template>
  <div v-dialog class="fixed inset-0 z-[60] grid place-items-center p-3 sm:p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-card">
      <header class="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="min-w-0 flex-1 truncate font-title text-base font-bold text-text">
          {{ creating ? L.t('tracker.newWork') : L.t('tracker.workSettings') }}
        </h3>
        <button type="button" @click="emit('close')" :aria-label="L.t('common.close')"
                class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><X class="size-5" /></button>
      </header>

      <!-- создание -->
      <form v-if="creating" class="space-y-3 overflow-y-auto p-4" @submit.prevent="create">
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.workTitle') }}</span>
          <input v-model="title" maxlength="200" autofocus :placeholder="L.t('tracker.workTitlePlaceholder')"
                 class="w-full rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.workKey') }}</span>
          <input :value="key" @input="onKeyInput" maxlength="10" spellcheck="false"
                 class="w-40 rounded-lg border bg-card2 px-3 py-2 font-mono text-sm uppercase text-text outline-none focus:border-accent"
                 :class="keyError ? 'border-red' : 'border-border2'" />
          <span class="mt-1 block text-xs" :class="keyError ? 'text-red' : 'text-text3'">
            {{ keyError || L.t('tracker.workKeyHint', { key: key }) }}
          </span>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.description') }}</span>
          <textarea v-model="description" rows="3" maxlength="4000"
                    class="w-full resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />
        </label>
        <div>
          <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.workColor') }}</span>
          <div class="flex gap-2">
            <button v-for="c in COLOR_IDS" :key="c" type="button" @click="color = c" :aria-label="c || 'default'"
                    class="size-7 rounded-full ring-offset-2 ring-offset-[var(--gb-card)]" :class="color === c ? 'ring-2 ring-accent' : ''"
                    :style="{ background: labelColor(c) }" />
          </div>
        </div>
        <div class="flex justify-end gap-2 pt-1">
          <button type="button" @click="emit('close')" class="rounded-lg px-3 py-2 text-sm text-text3 hover:bg-bg2">{{ L.t('common.cancel') }}</button>
          <button type="submit" :disabled="!title.trim() || !!keyError"
                  class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-40">
            {{ L.t('tracker.createWork') }}
          </button>
        </div>
      </form>

      <!-- настройка -->
      <template v-else-if="project">
        <div class="flex shrink-0 gap-1 border-b border-border px-3">
          <button v-for="[k, label] in [['main', L.t('tracker.tabMain')], ['columns', L.t('tracker.tabColumns')], ['labels', L.t('tracker.tabLabels')]]"
                  :key="k" type="button" @click="tab = k"
                  class="-mb-px border-b-2 px-3 py-2 text-sm transition-colors"
                  :class="tab === k ? 'border-accent font-semibold text-accent' : 'border-transparent text-text3 hover:text-text'">
            {{ label }}
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-4">
          <div v-if="tab === 'main'" class="space-y-3">
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.workTitle') }}</span>
              <input v-model="editTitle" maxlength="200" @blur="commitTitle" @keydown.enter.prevent="$event.target.blur()"
                     class="w-full rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />
            </label>
            <p class="text-xs text-text3">
              {{ L.t('tracker.workKey') }}: <b class="font-mono text-text">{{ project.key || '—' }}</b>
              · {{ L.t('tracker.keyImmutable') }}
            </p>
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.field.description') }}</span>
              <textarea v-model="editDescription" rows="3" maxlength="4000" @blur="commitDescription"
                        class="w-full resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />
            </label>
            <div>
              <span class="mb-1 block text-xs font-semibold text-text3">{{ L.t('tracker.workColor') }}</span>
              <div class="flex gap-2">
                <button v-for="c in COLOR_IDS" :key="c" type="button" @click="update({ color: c })" :aria-label="c || 'default'"
                        class="size-7 rounded-full ring-offset-2 ring-offset-[var(--gb-card)]"
                        :class="(project.color || '') === c ? 'ring-2 ring-accent' : ''" :style="{ background: labelColor(c) }" />
              </div>
            </div>
            <div class="flex flex-wrap gap-2 border-t border-border pt-3">
              <button type="button" @click="update({ archived: !project.archived })"
                      class="flex items-center gap-1.5 rounded-lg border border-border2 px-3 py-2 text-sm text-text2 hover:bg-bg2">
                <component :is="project.archived ? ArchiveRestore : Archive" class="size-4" />
                {{ project.archived ? L.t('tracker.unarchiveWork') : L.t('tracker.archiveWork') }}
              </button>
              <button type="button" @click="removeProject"
                      class="flex items-center gap-1.5 rounded-lg border border-red/40 px-3 py-2 text-sm text-red hover:bg-red/10">
                <Trash2 class="size-4" />{{ L.t('tracker.deleteWork') }}
              </button>
            </div>
          </div>

          <div v-else-if="tab === 'columns'" class="space-y-2">
            <p class="text-xs text-text3">{{ L.t('tracker.columnsHint') }}</p>
            <div v-for="(col, i) in columns" :key="col.id" class="rounded-lg border border-border2 bg-card2 p-2">
              <div class="flex items-center gap-2">
                <span class="size-2.5 shrink-0 rounded-full" :style="{ background: (COLUMN_STYLE[col.kind] || COLUMN_STYLE.todo).color }" />
                <input :value="col.title" maxlength="80" @change="renameColumn(col, $event)" :aria-label="L.t('tracker.columnTitle')"
                       class="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1.5 py-1 text-sm text-text outline-none focus:border-accent focus:bg-card" />
                <select :value="col.kind" @change="tracker.stage({ op: 'column.update', id: col.id, kind: $event.target.value })"
                        :aria-label="L.t('tracker.columnKindLabel')"
                        class="shrink-0 rounded-md border border-border2 bg-card px-1.5 py-1 text-xs text-text outline-none focus:border-accent">
                  <option v-for="k in COLUMN_KINDS" :key="k" :value="k">{{ L.columnKind.value[k] }}</option>
                </select>
                <button type="button" :disabled="i === 0" @click="shiftColumn(i, -1)" :aria-label="L.t('tracker.moveLeft')"
                        class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-card disabled:opacity-30"><ArrowUp class="size-4" /></button>
                <button type="button" :disabled="i === columns.length - 1" @click="shiftColumn(i, 1)" :aria-label="L.t('tracker.moveRight')"
                        class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-card disabled:opacity-30"><ArrowDown class="size-4" /></button>
                <button type="button" :disabled="columns.length <= 1 || (countIn(col.id) > 0 && !moveTo[col.id])" @click="removeColumn(col)"
                        :aria-label="L.t('common.delete')"
                        class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-red/10 hover:text-red disabled:opacity-30"><Trash2 class="size-4" /></button>
              </div>
              <!-- В колонке есть задачи — удалить её можно, только сказав, куда их деть. -->
              <label v-if="countIn(col.id) > 0 && columns.length > 1" class="mt-1.5 flex flex-wrap items-center gap-2 pl-4 text-xs text-text3">
                {{ L.t('tracker.columnHasTasks', { n: countIn(col.id) }) }}
                <select v-model="moveTo[col.id]" class="rounded-md border border-border2 bg-card px-1.5 py-1 text-xs text-text outline-none focus:border-accent">
                  <option :value="undefined">{{ L.t('tracker.pickColumn') }}</option>
                  <option v-for="c in columns.filter((x) => x.id !== col.id)" :key="c.id" :value="c.id">{{ c.title }}</option>
                </select>
              </label>
            </div>
            <button type="button" @click="addColumn" :disabled="columns.length >= 12"
                    class="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-accent hover:bg-bg2 disabled:opacity-40">
              <Plus class="size-4" />{{ L.t('tracker.addColumn') }}
            </button>
          </div>

          <div v-else class="space-y-2">
            <p class="text-xs text-text3">{{ L.t('tracker.labelsHint') }}</p>
            <div v-for="l in labels" :key="l.id" class="flex items-center gap-2">
              <span class="size-4 shrink-0 rounded-full" :style="{ background: labelColor(l.color) }" />
              <input :value="l.title" maxlength="80" @change="renameLabel(l, $event)" :aria-label="L.t('tracker.labelTitle')"
                     class="min-w-0 flex-1 rounded-md border border-border2 bg-card2 px-2 py-1 text-sm text-text outline-none focus:border-accent" />
              <select :value="l.color" @change="patchLabel(l, { color: $event.target.value })" :aria-label="L.t('tracker.workColor')"
                      class="shrink-0 rounded-md border border-border2 bg-card px-1.5 py-1 text-xs text-text outline-none focus:border-accent">
                <option v-for="c in COLOR_IDS" :key="c" :value="c">{{ L.t(`tracker.color.${c || 'gray'}`) }}</option>
              </select>
              <button type="button" @click="setLabels(labels.filter((x) => x.id !== l.id))" :aria-label="L.t('common.delete')"
                      class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-red/10 hover:text-red"><Trash2 class="size-4" /></button>
            </div>
            <form class="flex items-center gap-2 border-t border-border pt-2" @submit.prevent="addLabel">
              <input v-model="newLabel" maxlength="80" :placeholder="L.t('tracker.newLabel')"
                     class="min-w-0 flex-1 rounded-md border border-border2 bg-card2 px-2 py-1.5 text-sm text-text outline-none focus:border-accent" />
              <select v-model="newLabelColor" :aria-label="L.t('tracker.workColor')"
                      class="shrink-0 rounded-md border border-border2 bg-card px-1.5 py-1.5 text-xs text-text outline-none focus:border-accent">
                <option v-for="c in COLOR_IDS" :key="c" :value="c">{{ L.t(`tracker.color.${c || 'gray'}`) }}</option>
              </select>
              <button type="submit" :disabled="!newLabel.trim() || labels.length >= 30"
                      class="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">{{ L.t('common.add') }}</button>
            </form>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
