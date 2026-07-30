<script setup>
// AdminSchedule — редактор расписания 2.0 (overlay поверх портала ВСГУТУ).
//
// Что нового против первой версии:
//  • сетка «слоты × дни» — каждая ячейка является зоной для drag-drop;
//  • перенос пары ПЕРЕТАСКИВАНИЕМ (long-press ~0.5 c, работает мышью и пальцем);
//  • при переносе время подстраивается под НОМЕР слота (1-я пара → 09:00, 3-я → 13:00);
//  • сразу после переноса — сверка аудитории/преподавателя у ДРУГИХ групп, накладка
//    подсвечивается красным;
//  • правки НЕ пишутся сразу — копятся в ЧЕРНОВИКЕ, «Сохранить» шлёт их пачкой;
//  • уход со вкладки или смена группы с несохранённым черновиком — переспрос;
//  • «Взять с ВСГУТУ» (группа/все) — форс-обновление портала; «Сброс» (группа/все) —
//    снять правки и вернуться к порталу.
//
// Почему сетка, а не карточки: перетаскивать пару в конкретный слот (день+номер) можно,
// только когда каждый слот — видимая зона сброса, включая пустые.
import { ref, computed, reactive, onMounted, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { adminApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'

const toast = useToast()
const { confirm } = useConfirm()

const DAYS = ['Пнд', 'Втр', 'Срд', 'Чтв', 'Птн', 'Сбт']
// Стандартная сетка звонков ВСГУТУ — запасная, если портал не отдал своё расписание пар.
const DEFAULT_TIMES = ['09:00-10:35', '10:45-12:20', '13:00-14:35',
                       '14:45-16:20', '16:25-18:00', '18:05-19:40']
// Сколько держать пару, прежде чем начнётся перетаскивание. Короткое удержание отличает
// намеренный перенос от обычного тапа/прокрутки. Значение подбираемое.
const LONG_PRESS_MS = 500
const MOVE_CANCEL_PX = 8      // сдвиг до старта перетаскивания = это прокрутка, не drag

const groups = ref([])
const group = ref('')
const week = ref(1)
const base = ref(null)        // слитое расписание с сервера {weeks, pair_times}
const savedKeys = ref(new Set())   // ячейки с УЖЕ сохранёнными правками (бейдж «сохранено»)
const loading = ref(false)
// §ролей: предмет — из СПИСКА предметов группы (не свободный текст), преподаватель —
// автоматом из назначения (webdata.teacher_assignments), а не ручной ввод ФИО.
const teacherBySubject = ref({})   // {предмет: {id, name}} для ТЕКУЩЕЙ группы/термина
const groupSubjects = computed(() => {
  const g = groups.value.find((x) => (x.name || x) === group.value)
  return g?.subjects || []
})

// Черновик: ключ «неделя|день|слот» → {action:'set'|'remove', ...поля}. Пусто = нет правок.
const pending = reactive({})
// Ключи ячеек, где сверка нашла накладку (для подсветки).
const conflicts = reactive(new Set())

const dirty = computed(() => Object.keys(pending).length > 0)
const pairTimes = computed(() => base.value?.pair_times?.length ? base.value.pair_times : DEFAULT_TIMES)

function key(day, slot) { return `${week.value}|${day}|${slot}` }
function timeForSlot(slot) { return pairTimes.value[slot - 1] || '' }

// Сколько строк-слотов рисовать: минимум 6, но если где-то есть пара с бо́льшим номером —
// показываем и её (портал изредка даёт 7-ю пару).
const slotCount = computed(() => {
  let max = 6
  for (const day of DAYS) {
    for (const p of basePairs(day)) max = Math.max(max, p.pair_no || 0)
  }
  for (const k of Object.keys(pending)) {
    const [w, , slot] = k.split('|')
    if (Number(w) === week.value) max = Math.max(max, Number(slot))
  }
  return max
})
const slots = computed(() => Array.from({ length: slotCount.value }, (_, i) => i + 1))

function basePairs(day) {
  return (base.value?.weeks?.[String(week.value)] || {})[day] || []
}

// Что показать в ячейке с учётом черновика: null — пусто.
function cell(day, slot) {
  const k = key(day, slot)
  if (k in pending) {
    const op = pending[k]
    if (op.action === 'remove') return null
    return { pair_no: slot, ...op, _pending: true }
  }
  const found = basePairs(day).find((p) => Number(p.pair_no) === slot)
  return found ? { ...found, _pending: false } : null
}

function isPending(day, slot) { return key(day, slot) in pending }
function isSaved(day, slot) { return !isPending(day, slot) && savedKeys.value.has(key(day, slot)) }
function isConflict(day, slot) { return conflicts.has(key(day, slot)) }

// ── Загрузка ──────────────────────────────────────────────────────────────────────
onMounted(async () => {
  try { groups.value = (await adminApi.groups()).data.groups || [] } catch { groups.value = [] }
  if (groups.value.length) { group.value = groups.value[0].name || groups.value[0]; await load() }
})

async function load() {
  if (!group.value) return
  loading.value = true
  try {
    const r = (await adminApi.schedule(group.value)).data
    base.value = r.schedule
    savedKeys.value = new Set((r.overrides || []).map((o) => `${o.week}|${o.day}|${o.pair_no}`))
    clearDraft()
  } catch { toast.error('Не удалось загрузить расписание') } finally { loading.value = false }
  //Назначения препод↔предмет для автозаполнения графы «Преподаватель» — тот же
  //источник, что и в редакторе часов («Группы» → 🕐), не блокирует основную загрузку.
  try {
    const hr = (await adminApi.groupHours(group.value)).data
    const map = {}
    for (const s of (hr.subjects || [])) {
      if (s.teacher_id) map[s.subject] = { id: s.teacher_id, name: s.teacher_name }
    }
    teacherBySubject.value = map
  } catch { teacherBySubject.value = {} }
}

function clearDraft() {
  for (const k of Object.keys(pending)) delete pending[k]
  conflicts.clear()
}

// ── Сохранение / отмена черновика ──────────────────────────────────────────────────
const saving = ref(false)
async function saveDraft() {
  if (!dirty.value) return
  saving.value = true
  try {
    const overrides = Object.entries(pending).map(([k, op]) => {
      const [w, day, slot] = k.split('|')
      return { group: group.value, week: Number(w), day, pair_no: Number(slot), ...op }
    })
    await adminApi.saveScheduleOverrides(overrides)
    toast.success('Расписание сохранено')
    await load()
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось сохранить') }
  finally { saving.value = false }
}

async function discardDraft() {
  if (!dirty.value) return
  if (!(await confirm({ title: 'Отменить несохранённые правки?', okText: 'Отменить правки', danger: true }))) return
  clearDraft()
}

// ── Перенос: собственно правка черновика ───────────────────────────────────────────
async function moveCell(from, to) {
  if (from.day === to.day && from.slot === to.slot) return
  const src = cell(from.day, from.slot)
  if (!src) return
  if (cell(to.day, to.slot)) {
    toast.error('Слот занят — сначала освободите его')
    return
  }
  // Перенос = скрыть исходную ячейку + задать целевую (время под номер целевого слота).
  pending[key(from.day, from.slot)] = { action: 'remove' }
  conflicts.delete(key(from.day, from.slot))
  const op = {
    action: 'set',
    subject: src.subject || src.raw || '',
    room: src.room || '', teacher: src.teacher || '', kind: src.kind || '',
    time: timeForSlot(to.slot),
  }
  pending[key(to.day, to.slot)] = op
  await checkSlot(to.day, to.slot, op)
}

// Сверка целевого слота против других групп (аудитория/преподаватель).
async function checkSlot(day, slot, op) {
  try {
    const r = (await adminApi.slotConflicts({
      group: group.value, week: week.value, day, pair_no: slot,
      room: op.room, teacher: op.teacher, subject: op.subject,
    })).data
    const clash = (r.room?.length || 0) + (r.teacher?.length || 0)
    if (clash) {
      conflicts.add(key(day, slot))
      const who = r.room?.length ? `аудитория ${op.room}` : `преподаватель ${op.teacher}`
      toast.error(`Накладка: ${who} занят(а) в это время у другой группы`)
    } else {
      conflicts.delete(key(day, slot))
      if (r.building) toast.info('Проверка неполна: расписание портала ещё собирается')
    }
  } catch { /* сверка не критична — правку не блокируем */ }
}

// ── Форма пары (добавить / изменить / скрыть) ──────────────────────────────────────
const showForm = ref(false)
const form = reactive({ day: 'Пнд', slot: 1, subject: '', room: '', teacher: '', origin: null })

// Предмет выбран/сменился → преподаватель подставляется автоматом из назначения.
// Не найдено назначения — поле остаётся пустым (не блокирует сохранение: расписание
// можно вести и до кадрового назначения).
function onFormSubjectChange() {
  form.teacher = teacherBySubject.value[form.subject]?.name || ''
}
function openAdd(day, slot) {
  Object.assign(form, { day, slot, subject: '', room: '', teacher: '', origin: null })
  showForm.value = true
}
function openEdit(day, slot) {
  const c = cell(day, slot)
  if (!c) return openAdd(day, slot)
  const subject = c.subject || c.raw || ''
  Object.assign(form, {
    day, slot, subject, room: c.room || '',
    teacher: teacherBySubject.value[subject]?.name || c.teacher || '', origin: { day, slot },
  })
  showForm.value = true
}
async function submitForm() {
  if (!form.subject.trim()) { toast.error('Укажите предмет'); return }
  // Сменили день/номер в форме — это тоже перенос: старую ячейку убрать.
  if (form.origin && (form.origin.day !== form.day || form.origin.slot !== form.slot)) {
    pending[key(form.origin.day, form.origin.slot)] = { action: 'remove' }
    conflicts.delete(key(form.origin.day, form.origin.slot))
  }
  const op = {
    action: 'set', subject: form.subject.trim(), room: form.room.trim(),
    //Преподаватель — ставится автоматом из назначения (не ручной ввод, см. onFormSubjectChange).
    teacher: (teacherBySubject.value[form.subject]?.name || '').trim(), kind: '',
    time: timeForSlot(form.slot),
  }
  pending[key(form.day, form.slot)] = op
  showForm.value = false
  await checkSlot(form.day, form.slot, op)
}
function hideFromForm() {
  pending[key(form.day, form.slot)] = { action: 'remove' }
  conflicts.delete(key(form.day, form.slot))
  showForm.value = false
}

// ── Взять с ВСГУТУ / Сброс ─────────────────────────────────────────────────────────
async function refreshGroup() {
  if (dirty.value && !(await confirm({ title: 'Обновить с ВСГУТУ? Несохранённые правки пропадут.', okText: 'Обновить', danger: true }))) return
  loading.value = true
  try { await adminApi.refreshSchedule(group.value); await load(); toast.success('Расписание обновлено с портала') }
  catch { toast.error('Не удалось обновить'); loading.value = false }
}
async function refreshAll() {
  if (!(await confirm({ title: 'Обновить расписание ВСЕХ групп с ВСГУТУ?', message: 'Сборка идёт в фоне (~минуту).', okText: 'Обновить все' }))) return
  try { await adminApi.refreshSchedule('', true); toast.success('Обновление всех групп запущено (в фоне)') }
  catch { toast.error('Не удалось запустить обновление') }
}
async function resetGroup() {
  if (!(await confirm({ title: `Сбросить правки группы ${group.value}?`, message: 'Расписание снова будет браться с портала.', okText: 'Сбросить', danger: true }))) return
  try { await adminApi.resetSchedule(group.value); await load(); toast.success('Правки сброшены') }
  catch { toast.error('Не удалось сбросить') }
}
async function resetAll() {
  if (!(await confirm({ title: 'Сбросить правки ВСЕХ групп?', message: 'Все ручные правки колледжа будут удалены безвозвратно.', okText: 'Далее', danger: true }))) return
  if (!(await confirm({ title: 'Точно удалить правки всех групп?', message: 'Это действие необратимо.', okText: 'Удалить всё', danger: true }))) return
  try { const r = await adminApi.resetSchedule('', true); await load(); toast.success(`Сброшено правок: ${r.data.reset}`) }
  catch { toast.error('Не удалось сбросить') }
}

// ── Смена группы/недели с защитой от потери черновика ───────────────────────────────
async function onGroupChange(e) {
  const next = e.target.value
  if (dirty.value && !(await confirm({ title: 'Продолжить без сохранения?', message: 'В расписании есть несохранённые правки.', okText: 'Продолжить', danger: true }))) {
    e.target.value = group.value      // вернуть прежний выбор
    return
  }
  group.value = next
  await load()
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  return await confirm({ title: 'Продолжить без сохранения?', message: 'В расписании есть несохранённые правки.', okText: 'Уйти без сохранения', danger: true })
})

// Уход со страницы через закрытие вкладки/обновление браузера.
function beforeUnload(e) { if (dirty.value) { e.preventDefault(); e.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))

// ── Drag-and-drop (long-press, мышь и тач) ─────────────────────────────────────────
const dragging = ref(null)        // {day, slot, text} — что тащим
const hover = ref(null)           // {day, slot} — над какой ячейкой
const ghost = reactive({ show: false, x: 0, y: 0, text: '' })
let press = null                  // фаза удержания до старта перетаскивания

function onPairPointerDown(e, day, slot) {
  if (e.button != null && e.button !== 0) return   // только основная кнопка мыши
  const c = cell(day, slot)
  if (!c) return
  press = { day, slot, x: e.clientX, y: e.clientY, text: c.subject || c.raw || '', moved: false }
  press.timer = setTimeout(beginDrag, LONG_PRESS_MS)
  window.addEventListener('pointermove', onPressMove)
  window.addEventListener('pointerup', onPressUp)
}
function onPressMove(e) {
  if (!press) return
  if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > MOVE_CANCEL_PX) {
    press.moved = true
    endPress()          // сдвинулись до срабатывания удержания — это прокрутка, не перенос
  }
}
function onPressUp() {
  if (!press) return
  const p = press
  endPress()
  if (!p.moved) openEdit(p.day, p.slot)   // короткий тап = открыть форму (правка/скрытие)
}
function endPress() {
  if (press?.timer) clearTimeout(press.timer)
  window.removeEventListener('pointermove', onPressMove)
  window.removeEventListener('pointerup', onPressUp)
  press = null
}
function beginDrag() {
  if (!press) return
  const p = press
  window.removeEventListener('pointermove', onPressMove)
  window.removeEventListener('pointerup', onPressUp)
  if (press?.timer) clearTimeout(press.timer)
  press = null
  dragging.value = { day: p.day, slot: p.slot, text: p.text }
  Object.assign(ghost, { show: true, x: p.x, y: p.y, text: p.text })
  window.addEventListener('pointermove', onDragMove, { passive: false })
  window.addEventListener('pointerup', onDragUp)
}
function cellUnderPoint(e) {
  const el = document.elementFromPoint(e.clientX, e.clientY)
  const td = el?.closest('[data-day]')
  if (!td) return null
  return { day: td.dataset.day, slot: Number(td.dataset.slot) }
}
function onDragMove(e) {
  e.preventDefault()      // не даём странице прокручиваться во время перетаскивания
  ghost.x = e.clientX; ghost.y = e.clientY
  hover.value = cellUnderPoint(e)
}
async function onDragUp(e) {
  const from = dragging.value
  const to = cellUnderPoint(e)
  endDrag()
  if (from && to) await moveCell(from, to)
}
function endDrag() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragUp)
  dragging.value = null
  hover.value = null
  ghost.show = false
}
onBeforeUnmount(() => { endPress(); endDrag() })

function isDragSource(day, slot) {
  return dragging.value && dragging.value.day === day && dragging.value.slot === slot
}
function isHover(day, slot) {
  return hover.value && hover.value.day === day && hover.value.slot === slot
}
</script>

<template>
  <div class="space-y-4" style="touch-action: pan-y">
    <!-- Панель управления -->
    <div class="flex flex-wrap items-center gap-2">
      <select :value="group" @change="onGroupChange"
              class="h-9 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g.name || g" :value="g.name || g">{{ g.name || g }}</option>
      </select>
      <div class="inline-flex overflow-hidden rounded-sm border border-border2">
        <button class="px-3 py-1.5 text-sm" :class="week === 1 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 1">I неделя</button>
        <button class="px-3 py-1.5 text-sm" :class="week === 2 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 2">II неделя</button>
      </div>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        <AppButton variant="ghost" size="sm" @click="refreshGroup">↻ Взять с ВСГУТУ</AppButton>
        <AppButton variant="ghost" size="sm" @click="refreshAll">↻ Все группы</AppButton>
        <AppButton variant="ghost" size="sm" @click="resetGroup">Сброс группы</AppButton>
        <AppButton variant="ghost" size="sm" @click="resetAll">Сброс всех</AppButton>
      </div>
    </div>

    <!-- Черновик: сохранить / отменить -->
    <div v-if="dirty" class="flex flex-wrap items-center gap-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-2.5">
      <span class="text-sm font-medium text-accent">Есть несохранённые правки</span>
      <div class="ml-auto flex gap-2">
        <AppButton variant="ghost" size="sm" @click="discardDraft">Отменить</AppButton>
        <AppButton variant="green" size="sm" :disabled="saving" @click="saveDraft">{{ saving ? 'Сохранение…' : 'Сохранить' }}</AppButton>
      </div>
    </div>

    <p class="text-xs text-text3">
      Удерживайте пару ~полсекунды и перетащите на другой слот или день. Время подстроится
      под номер пары. Тап по паре — правка, тап по пустой ячейке — добавить.
    </p>

    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>

    <!-- Сетка «слоты × дни» -->
    <div v-else class="overflow-x-auto">
      <table class="w-full min-w-[820px] border-collapse select-none">
        <thead>
          <tr>
            <th class="w-28 border border-border2 bg-card2 p-2 text-xs font-semibold text-text3">Пара</th>
            <th v-for="day in DAYS" :key="day" class="border border-border2 bg-card2 p-2 text-sm font-semibold text-text">{{ day }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="slot in slots" :key="slot">
            <td class="border border-border2 bg-card2 p-2 text-center align-top">
              <div class="text-sm font-bold text-text">{{ slot }}</div>
              <div class="text-tiny text-text3">{{ timeForSlot(slot) }}</div>
            </td>
            <td v-for="day in DAYS" :key="day" :data-day="day" :data-slot="slot"
                class="h-20 border border-border2 p-1 align-top transition-colors"
                :class="[
                  isHover(day, slot) ? 'bg-accent/15 ring-2 ring-inset ring-accent' : '',
                  !cell(day, slot) && dragging ? 'bg-card2/50' : '',
                ]"
                @click="!cell(day, slot) && !dragging && openAdd(day, slot)">
              <div v-if="cell(day, slot)"
                   class="group relative h-full cursor-grab rounded-md border p-1.5 text-left"
                   :class="[
                     isConflict(day, slot) ? 'border-red bg-red/10'
                       : isPending(day, slot) ? 'border-accent bg-accent/10'
                       : 'border-border bg-card',
                     isDragSource(day, slot) ? 'opacity-40' : '',
                   ]"
                   @pointerdown="onPairPointerDown($event, day, slot)">
                <p class="truncate text-xs font-semibold text-text">{{ cell(day, slot).subject || cell(day, slot).raw }}</p>
                <p v-if="cell(day, slot).room || cell(day, slot).teacher" class="truncate text-tiny text-text3">
                  {{ [cell(day, slot).teacher, cell(day, slot).room ? 'ауд. ' + cell(day, slot).room : ''].filter(Boolean).join(' · ') }}
                </p>
                <span v-if="isConflict(day, slot)" class="absolute right-1 top-1 text-tiny font-bold text-red" title="Накладка">⚠</span>
                <span v-else-if="isPending(day, slot)" class="absolute right-1 top-1 text-tiny text-accent" title="Не сохранено">●</span>
                <span v-else-if="isSaved(day, slot)" class="absolute right-1 top-1 text-tiny text-text3" title="Сохранённая правка">✎</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Плавающий «призрак» перетаскивания -->
    <div v-if="ghost.show" class="pointer-events-none fixed z-[60] -translate-x-1/2 -translate-y-1/2 rounded-md border border-accent bg-card px-2 py-1 text-xs font-semibold text-text shadow-card"
         :style="{ left: ghost.x + 'px', top: ghost.y + 'px' }">
      {{ ghost.text }}
    </div>

    <!-- Форма пары -->
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
            <select v-model.number="form.slot" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="s in slots" :key="s" :value="s">{{ s }} ({{ timeForSlot(s) }})</option>
            </select>
          </label>
          <label class="col-span-2 text-sm">Предмет
            <select v-model="form.subject" @change="onFormSubjectChange"
                    class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option value="" disabled>Выберите предмет</option>
              <option v-for="s in groupSubjects" :key="s" :value="s">{{ s }}</option>
            </select>
            <p v-if="!groupSubjects.length" class="mt-1 text-tiny text-text3">
              У группы нет предметов — задайте их во вкладке «Группы».
            </p>
          </label>
          <label class="text-sm">Аудитория
            <input v-model="form.room" placeholder="101" class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          </label>
          <!-- §ролей: преподаватель — ставится АВТОМАТОМ из назначения (не ручной ввод),
               см. onFormSubjectChange / webdata.teacher_assignments. -->
          <label class="text-sm">Преподаватель
            <input :value="form.teacher || '— не назначен —'" disabled
                   class="mt-1 h-9 w-full rounded-sm border border-border2 bg-card2/60 px-2 text-sm text-text3 outline-none" />
          </label>
        </div>
        <div class="mt-5 flex items-center justify-between">
          <button v-if="form.origin" class="text-sm text-red hover:underline" @click="hideFromForm">Скрыть пару</button>
          <div class="ml-auto flex gap-2">
            <AppButton variant="ghost" size="sm" @click="showForm = false">Отмена</AppButton>
            <AppButton variant="green" size="sm" @click="submitForm">В черновик</AppButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
