<script setup>
// AdminSchedule — редактор расписания ПОВЕРХ портала (overlay). Портал ВСГУТУ — основа
// (read-only), админ точечно правит: добавить/заменить пару в ячейке (неделя·день·№) или
// СКРЫТЬ портальную пару. Правки применяются везде, где отдаётся расписание группы
// (кабинет студента, ответы Вектора). Для колледжей без портала — просто пустая основа.
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'

const toast = useToast()
const { confirm } = useConfirm()

const groups = ref([])
const group = ref('')
const week = ref(1)
const data = ref(null)            // слитое расписание {weeks:{'1':{Пнд:[...]}}}
const overrides = ref([])
const loading = ref(false)
const DAYS = ['Пнд', 'Втр', 'Срд', 'Чтв', 'Птн', 'Сбт']

// id-набор ячеек с правками (для бейджа «правка»)
const editedCells = computed(() =>
  new Set(overrides.value.map((o) => `${o.week}|${o.day}|${o.pair_no}`)))

const weeks = computed(() => data.value?.weeks || {})
function dayPairs(day) {
  return (weeks.value[String(week.value)] || {})[day] || []
}
function isEdited(day, pn) {
  return editedCells.value.has(`${week.value}|${day}|${pn}`)
}

onMounted(async () => {
  try { groups.value = (await adminApi.groups()).data.groups || [] } catch { groups.value = [] }
  if (groups.value.length) { group.value = groups.value[0].name || groups.value[0]; await load() }
})

async function load() {
  if (!group.value) return
  loading.value = true
  try {
    const r = (await adminApi.schedule(group.value)).data
    data.value = r.schedule
    overrides.value = r.overrides || []
  } catch { toast.error('Не удалось загрузить расписание') } finally { loading.value = false }
}

// ── форма добавления/правки пары ──
const showForm = ref(false)
const form = ref({ day: 'Пнд', pair_no: 1, time: '', subject: '', room: '', teacher: '' })
const saving = ref(false)

function openAdd(day) {
  form.value = { day: day || 'Пнд', pair_no: 1, time: '', subject: '', room: '', teacher: '' }
  showForm.value = true
}
function openEdit(day, p) {
  form.value = { day, pair_no: p.pair_no, time: p.time || '', subject: p.subject || '',
                 room: p.room || '', teacher: p.teacher || '' }
  showForm.value = true
}
async function save() {
  if (!form.value.subject.trim()) { toast.error('Укажите предмет'); return }
  saving.value = true
  try {
    await adminApi.setScheduleOverride({
      group: group.value, week: week.value, action: 'set', ...form.value,
      pair_no: Number(form.value.pair_no), subject: form.value.subject.trim(),
    })
    showForm.value = false
    await load()
    toast.success('Пара сохранена')
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось сохранить') }
  finally { saving.value = false }
}

// скрыть портальную пару (создаёт правку action=remove)
async function hidePair(day, p) {
  if (!(await confirm({ title: `Скрыть пару «${p.subject || p.raw}» (${day}, ${p.pair_no})?`,
                        okText: 'Скрыть', danger: true }))) return
  try {
    await adminApi.setScheduleOverride({ group: group.value, week: week.value,
      day, pair_no: p.pair_no, action: 'remove' })
    await load()
  } catch { toast.error('Не удалось скрыть') }
}

// убрать правку ячейки — вернуться к тому, что даёт портал
async function revertCell(day, pn) {
  const ov = overrides.value.find((o) => o.week === week.value && o.day === day && o.pair_no === pn)
  if (!ov) return
  if (!(await confirm({ title: 'Убрать правку и вернуть как на портале?', okText: 'Вернуть' }))) return
  try { await adminApi.deleteScheduleOverride(ov.id); await load() }
  catch { toast.error('Не удалось убрать правку') }
}
</script>

<template>
  <div class="space-y-4">
    <!-- Панель: группа + неделя -->
    <div class="flex flex-wrap items-center gap-3">
      <select v-model="group" @change="load"
              class="h-9 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g.name || g" :value="g.name || g">{{ g.name || g }}</option>
      </select>
      <div class="inline-flex overflow-hidden rounded-sm border border-border2">
        <button class="px-3 py-1.5 text-sm" :class="week === 1 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 1">I неделя</button>
        <button class="px-3 py-1.5 text-sm" :class="week === 2 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 2">II неделя</button>
      </div>
      <span class="text-xs text-text3">Правки применяются поверх портала — их видят студенты и Вектор.</span>
      <AppButton variant="green" size="sm" class="ml-auto" @click="openAdd()">+ Добавить пару</AppButton>
    </div>

    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>

    <!-- Сетка дней -->
    <div v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="day in DAYS" :key="day" class="rounded-lg border border-border bg-card shadow-card">
        <div class="flex items-center justify-between border-b border-border2 px-4 py-2">
          <h3 class="font-semibold text-text">{{ day }}</h3>
          <button class="text-xs text-accent hover:underline" @click="openAdd(day)">+ пара</button>
        </div>
        <ul class="divide-y divide-border">
          <li v-if="!dayPairs(day).length" class="px-4 py-3 text-sm text-text3">Пар нет</li>
          <li v-for="p in dayPairs(day)" :key="p.pair_no" class="flex items-start gap-2 px-4 py-2.5">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="text-xs font-semibold text-text3">{{ p.pair_no }}. {{ p.time }}</span>
                <span v-if="isEdited(day, p.pair_no)" class="rounded-sm bg-accent/15 px-1.5 py-0.5 text-tiny font-semibold text-accent">правка</span>
              </div>
              <p class="truncate text-sm font-medium text-text">{{ p.subject || p.raw }}</p>
              <p v-if="p.room || p.teacher" class="truncate text-xs text-text3">{{ [p.teacher, p.room ? 'ауд. ' + p.room : ''].filter(Boolean).join(' · ') }}</p>
            </div>
            <div class="flex shrink-0 gap-1.5">
              <button class="text-text3 hover:text-accent" title="Изменить" @click="openEdit(day, p)">✎</button>
              <button v-if="isEdited(day, p.pair_no)" class="text-text3 hover:text-text" title="Вернуть как на портале" @click="revertCell(day, p.pair_no)">↩</button>
              <button v-else class="text-text3 hover:text-red" title="Скрыть портальную пару" @click="hidePair(day, p)">✕</button>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <!-- Модалка добавления/правки -->
    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">Пара — {{ group }}, {{ week === 2 ? 'II' : 'I' }} неделя</h3>
        <div class="grid grid-cols-2 gap-3">
          <label class="text-sm">День
            <select v-model="form.day" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="d in DAYS" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label class="text-sm">№ пары
            <input v-model.number="form.pair_no" type="number" min="1" max="8" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="col-span-2 text-sm">Предмет
            <input v-model="form.subject" placeholder="Например: Математика" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="text-sm">Время
            <input v-model="form.time" placeholder="10:45-12:20" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="text-sm">Аудитория
            <input v-model="form.room" placeholder="101" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="col-span-2 text-sm">Преподаватель
            <input v-model="form.teacher" placeholder="ФИО (необязательно)" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showForm = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="save">{{ saving ? 'Сохранение…' : 'Сохранить' }}</AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
