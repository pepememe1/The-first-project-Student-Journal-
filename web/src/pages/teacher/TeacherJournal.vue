<script setup>
// TeacherJournal — журнал преподавателя, порт десктопного teacher_dashboard._update_table:
//  • компактная таблица, выровнена ВЛЕВО (не расползается при 1–2 занятиях);
//  • значения ячеек — селекты по типу (Лекция ✓/Н/Б/О; Практика 2–5/Н; Экзамен 2–5/Н с
//    «(Зачтено)/(Не зачтено)» и назначением пересдачи, как на ПК);
//  • заголовок занятия читаемый: тип №, дата, тема (2 строки + полная в тултипе);
//  • ПКМ по заголовку — меню «Изменить / Пересдача / Удалить»; двойной клик — правка
//    (в модалке видна полная тема); ✎/✕ прямо в шапке;
//  • зебра, цветные оценки/средний, строка «средний по группе»;
//  • дата нового занятия — автоматически сегодняшняя.
// Всё пишется в те же таблицы, что синк десктопа → изменения доезжают до ПК pull'ом.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { teacherApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'
import AppButton from '@/components/ui/AppButton.vue'

const groups = ref([])
const subjects = ref([])
const group = ref('')
const subject = ref('')
const data = ref(null)
const loading = ref(false)
const saving = ref(false)

onMounted(async () => {
  try {
    const o = (await teacherApi.overview()).data
    groups.value = o.groups || []
    subjects.value = o.subjects || []
    group.value = groups.value[0] || ''
    subject.value = subjects.value[0] || ''
  } catch { /* */ }
  document.addEventListener('click', closeCtx)
})
onBeforeUnmount(() => document.removeEventListener('click', closeCtx))

async function load() {
  if (!group.value || !subject.value) { data.value = null; return }
  loading.value = true
  try { data.value = (await teacherApi.journal(group.value, subject.value)).data } catch { data.value = null } finally { loading.value = false }
}
watch([group, subject], load)

// ── Колонки: занятие + его пересдачи (как col_defs в десктопе) ──────────────────
function retakeKey(l, ri) { return ri === 1 ? `${l.id}_retake` : `${l.id}_retake_${ri}` }
function retakeDate(l, ri) { return ri === 1 ? l.retake_date : (l.extra || {})[`retake_date_${ri}`] || '' }
const colDefs = computed(() => {
  const out = []
  for (const l of data.value?.lessons || []) {
    out.push({ l, ri: 0, key: l.id })
    if (l.type === 'Экзамен') {
      for (let ri = 1; ri <= 5; ri++) {
        if (retakeDate(l, ri)) out.push({ l, ri, key: retakeKey(l, ri) })
      }
    }
  }
  return out
})

// ── Значения ячеек (селекты, как комбобоксы десктопа) ───────────────────────────
const OPTIONS = {
  'Лекция': ['', '✓', 'Н', 'Б', 'О'],
  'default': ['', '2', '3', '4', '5', 'Н'],
}
function cellOptions(l) { return OPTIONS[l.type] || OPTIONS.default }
function rawValue(v) { return (v || '').split(' ')[0] }   // «5 (Зачтено)» → «5» в селекте
function isFailed(v) {
  v = (v || '').trim()
  return !!v && (v.startsWith('2') || v.startsWith('Н') || v.includes('Не зачтено'))
}
function needsRetake(s, col) {
  if (s.grades[col.key]) return true
  const prevKey = col.ri === 1 ? col.l.id : retakeKey(col.l, col.ri - 1)
  return isFailed(s.grades[prevKey])
}

function gradeClass(v) {
  v = rawValue(v)
  if (v === '5' || v === '✓') return 'text-accent font-bold'
  if (v === '4') return 'text-blue font-bold'
  if (v === '3') return 'text-orange font-bold'
  if (v === '2' || v === 'Н') return 'text-red font-bold'
  if (v === 'Б' || v === 'О') return 'text-text3 font-semibold'
  return 'text-text2'
}
function avgClass(a) {
  const n = Number(a) || 0
  if (n >= 4.5) return 'text-accent'
  if (n >= 3.5) return 'text-blue'
  if (n >= 3) return 'text-orange'
  if (n > 0) return 'text-red'
  return 'text-text3'
}
const groupAverage = computed(() => {
  const vals = (data.value?.students || []).map((s) => Number(s.average) || 0).filter((v) => v > 0)
  return vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2) : '—'
})

// ── Запись оценки (селект → сервер → перезагрузка: средний считает сервер) ──────
async function setGrade(s, key, value) {
  const prev = s.grades[key] || ''
  if (value === rawValue(prev) && value !== '') return
  s.grades[key] = value
  saving.value = true
  try {
    await teacherApi.setGrade(s.surname, s.name, key, value)
    await load()
  } catch (e) {
    s.grades[key] = prev
    alert('Не удалось сохранить: ' + (e?.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

function plusDays(days) {
  const d = new Date(Date.now() + days * 86400000)
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`
}

// Экзамен — та же логика, что _set_exam_val на ПК.
async function setExamGrade(s, col, value) {
  if (value === '') { await setGrade(s, col.key, ''); return }
  let full = value
  let scheduleRetake = false
  if (value === '4' || value === '5') full = `${value} (Зачтено)`
  else if (value === '3') {
    if (confirm(`Оценка 3 у ${s.surname}. Засчитать?\n\nOK — зачёт, Отмена — на пересдачу.`)) full = '3 (Зачтено)'
    else { full = '3 (Не зачтено)'; scheduleRetake = true }
  } else if (value === '2' || value === 'Н') { full = `${value} (Не зачтено)`; scheduleRetake = true }
  await setGrade(s, col.key, full)
  if (scheduleRetake) {
    const nextRi = col.ri + 1
    if (nextRi <= 5 && !retakeDate(col.l, nextRi)) {
      const rd = prompt('Дата пересдачи (дд.мм.гггг):', plusDays(7))
      if (rd) {
        const payload = nextRi === 1 ? { retake_date: rd } : { [`retake_date_${nextRi}`]: rd }
        try { await teacherApi.updateLesson(col.l.id, payload); await load() }
        catch { alert('Не удалось назначить пересдачу') }
      }
    }
  }
}
function onCell(s, col, value) {
  if (col.l.type === 'Экзамен' || col.ri > 0) setExamGrade(s, col, value)
  else setGrade(s, col.key, value)
}

// ── ПКМ-меню на заголовке занятия (изменить / пересдача / удалить) ──────────────
const ctx = ref({ show: false, x: 0, y: 0, lesson: null })
function openCtx(e, l) { ctx.value = { show: true, x: Math.min(e.clientX, window.innerWidth - 200), y: e.clientY, lesson: l } }
function closeCtx() { if (ctx.value.show) ctx.value.show = false }
function ctxEdit() { openEditLesson(ctx.value.lesson); closeCtx() }
function ctxDelete() { const l = ctx.value.lesson; closeCtx(); delLesson(l) }
async function ctxRetake() {
  const l = ctx.value.lesson; closeCtx()
  const rd = prompt('Дата пересдачи (дд.мм.гггг):', plusDays(7))
  if (rd) { try { await teacherApi.updateLesson(l.id, { retake_date: rd }); await load() } catch { alert('Не удалось') } }
}

// ── Занятия: создание и правка (дата — сегодня по умолчанию) ────────────────────
const LESSON_TYPES = ['Практика', 'Лекция', 'Экзамен', 'Семинар', 'Лабораторная', 'Зачёт']
const showLesson = ref(false)
const editingLesson = ref(null)   // null — создание, иначе id занятия
const lessonForm = ref({ type: 'Практика', number: 1, topic: '', date: '', hour: 0, retake_date: '' })
const savingLesson = ref(false)
const lessonError = ref('')

function openLesson() {
  editingLesson.value = null
  const sameType = (data.value?.lessons || []).filter((l) => l.type === 'Практика').length
  lessonForm.value = { type: 'Практика', number: sameType + 1, topic: '', date: plusDays(0), hour: 0, retake_date: '' }
  lessonError.value = ''
  showLesson.value = true
}
function openEditLesson(l) {
  editingLesson.value = l.id
  lessonForm.value = { type: l.type, number: l.number, topic: l.topic || '', date: l.date || '', hour: l.hour || 0, retake_date: l.retake_date || '' }
  lessonError.value = ''
  showLesson.value = true
}
watch(() => lessonForm.value.type, (t) => {
  if (editingLesson.value) return
  const n = (data.value?.lessons || []).filter((l) => l.type === t).length
  lessonForm.value.number = n + 1
})
async function saveLesson() {
  if (!group.value || !subject.value) { lessonError.value = 'Выберите группу и предмет'; return }
  savingLesson.value = true
  lessonError.value = ''
  try {
    if (editingLesson.value) {
      const f = lessonForm.value
      await teacherApi.updateLesson(editingLesson.value, {
        topic: f.topic, date: f.date, number: f.number, hour: f.hour, retake_date: f.retake_date,
      })
    } else {
      await teacherApi.createLesson({ group: group.value, subject: subject.value, ...lessonForm.value })
    }
    showLesson.value = false
    await load()
  } catch (e) { lessonError.value = e?.response?.data?.detail || 'Не удалось сохранить занятие' }
  finally { savingLesson.value = false }
}
async function delLesson(l) {
  if (!confirm(`Удалить занятие ${l.type} №${l.number}? Оценки этой пары перестанут учитываться.`)) return
  try { await teacherApi.deleteLesson(l.id); await load() }
  catch (e) { alert(e?.response?.data?.detail || 'Не удалось удалить') }
}

// ── Excel ──────────────────────────────────────────────────────────────────────
const exporting = ref(false)
async function exportXlsx() {
  exporting.value = true
  try {
    const { data: blob } = await teacherApi.journalXlsx(group.value, subject.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Журнал_${group.value}_${subject.value}.xlsx`.replaceAll('/', '-')
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    let detail = ''
    try { detail = JSON.parse(await e?.response?.data?.text())?.detail || '' } catch { /* */ }
    alert('Не удалось выгрузить Excel' + (detail ? `: ${detail}` : ''))
  } finally { exporting.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <select v-model="subject" :title="subject"
              class="h-10 min-w-52 max-w-md rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
      </select>
      <span v-if="saving" class="self-center text-xs font-medium text-accent">Сохранение…</span>
      <span v-else-if="data" class="self-center text-xs text-text3">
        Студентов: {{ data.students?.length || 0 }} · занятий: {{ data.lessons?.length || 0 }}
      </span>
      <div v-if="group && subject" class="ml-auto flex gap-2">
        <AppButton variant="ghost" size="sm" :disabled="exporting || !data?.students?.length" @click="exportXlsx">
          {{ exporting ? 'Выгрузка…' : '💾 Excel' }}
        </AppButton>
        <AppButton variant="green" size="sm" @click="openLesson">+ Занятие</AppButton>
      </div>
    </div>

    <EmptyState v-if="!groups.length || !subjects.length" title="Нет нагрузки"
                message="За вами не закреплены группы или предметы." />
    <p v-else-if="loading" class="text-sm text-text3">Загрузка…</p>
    <EmptyState v-else-if="!data?.students?.length" title="Нет студентов" :message="`В группе ${group} нет студентов.`" />
    <EmptyState v-else-if="!data?.lessons?.length" title="Журнал пуст"
                message="Добавьте первое занятие кнопкой «+ Занятие» — колонки появятся здесь." />

    <!-- Таблица компактная и выровнена влево: обёртка не растягивает table (w-max). -->
    <div v-else class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <!-- w-max (без min-w-full): таблица ровно по содержимому и прижата ВЛЕВО, не
           расползается к центру при 1–2 занятиях. -->
      <table class="w-max text-sm">
        <thead>
          <tr class="border-b-2 border-accent/40 bg-bg2 text-text2">
            <th class="sticky left-0 z-10 bg-bg2 px-4 py-3 text-left text-tiny font-semibold uppercase tracking-wide">Студент</th>
            <th v-for="col in colDefs" :key="col.key"
                class="w-32 border-l border-border align-top px-2 py-2"
                :class="col.ri === 0 ? 'cursor-context-menu' : ''"
                :title="col.ri === 0 ? 'ПКМ или двойной клик — изменить занятие' : ''"
                @contextmenu.prevent="col.ri === 0 && openCtx($event, col.l)"
                @dblclick="col.ri === 0 && openEditLesson(col.l)">
              <template v-if="col.ri > 0">
                <div class="text-xs font-bold text-orange">Пересдача №{{ col.ri }}</div>
                <div class="text-[11px] font-normal normal-case text-text3">{{ retakeDate(col.l, col.ri) }}</div>
              </template>
              <template v-else>
                <div class="text-xs font-bold text-text">
                  {{ col.l.type }} №{{ col.l.number }}<span v-if="col.l.type === 'Лекция' && col.l.hour" class="font-normal text-text3"> ({{ col.l.hour }}ч)</span>
                </div>
                <div class="text-[11px] font-normal normal-case text-text3">{{ col.l.date || '—' }}</div>
                <div v-if="col.l.topic" class="mt-0.5 line-clamp-2 text-[11px] font-normal normal-case leading-snug text-text2" :title="col.l.topic">
                  {{ col.l.topic }}
                </div>
                <div class="mt-1 flex items-center justify-center gap-3 text-text3">
                  <button class="hover:text-accent" title="Изменить" @click.stop="openEditLesson(col.l)">✎</button>
                  <button class="hover:text-red" title="Удалить" @click.stop="delLesson(col.l)">✕</button>
                </div>
              </template>
            </th>
            <th class="border-l-2 border-accent/40 px-4 py-3 text-right text-tiny font-semibold uppercase tracking-wide">Средн.</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in data.students" :key="i"
              class="border-b border-border last:border-0 hover:bg-accent-glow/40" :class="i % 2 ? 'bg-bg2/50' : ''">
            <td class="sticky left-0 z-10 whitespace-nowrap px-4 py-2 text-left font-medium text-text" :class="i % 2 ? 'bg-bg2' : 'bg-card'">
              {{ s.surname }} {{ s.name }}
            </td>
            <td v-for="col in colDefs" :key="col.key" class="border-l border-border px-1.5 py-1.5 text-center">
              <span v-if="col.ri > 0 && !needsRetake(s, col)" class="text-text3">—</span>
              <select v-else :value="rawValue(s.grades[col.key])" :class="gradeClass(s.grades[col.key])"
                      :title="s.grades[col.key] || ''"
                      class="h-9 w-14 cursor-pointer rounded-sm border border-border2 bg-card2 text-center text-sm outline-none transition-colors hover:border-accent focus:border-accent"
                      @change="onCell(s, col, $event.target.value)">
                <option v-for="o in cellOptions(col.l)" :key="o" :value="o">{{ o || '·' }}</option>
              </select>
            </td>
            <td class="border-l-2 border-accent/20 px-4 py-2 text-right font-title text-base font-bold" :class="avgClass(s.average)">
              {{ s.average || '—' }}
            </td>
          </tr>
          <tr class="border-t-2 border-accent/40 bg-bg2/70">
            <td class="sticky left-0 z-10 bg-bg2 px-4 py-2.5 text-right text-xs font-semibold uppercase text-text3">Средний по группе</td>
            <td :colspan="colDefs.length" class="px-2 py-2.5"></td>
            <td class="border-l-2 border-accent/40 px-4 py-2.5 text-right font-title text-base font-extrabold" :class="avgClass(groupAverage)">{{ groupAverage }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Контекстное меню (ПКМ) -->
    <div v-if="ctx.show" class="fixed z-50 min-w-48 rounded-lg border border-border2 bg-card py-1 shadow-card"
         :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }" @click.stop>
      <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2" @click="ctxEdit">✎ Изменить тему / дату</button>
      <button v-if="ctx.lesson?.type === 'Экзамен'" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2" @click="ctxRetake">📅 Назначить пересдачу</button>
      <div class="my-1 border-t border-border" />
      <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red hover:bg-red/10" @click="ctxDelete">🗑 Удалить занятие</button>
    </div>

    <!-- Модалка занятия: создание и правка (дата — сегодня по умолчанию) -->
    <div v-if="showLesson" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showLesson = false">
      <div class="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">
          {{ editingLesson ? 'Изменить занятие' : 'Новое занятие' }} · {{ group }}
        </h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Тип</span>
              <select v-model="lessonForm.type" :disabled="!!editingLesson"
                      class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60">
                <option v-for="t in LESSON_TYPES" :key="t" :value="t">{{ t }}</option>
              </select></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">№</span>
              <input v-model.number="lessonForm.number" type="number" min="1"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Тема (полностью)</span>
            <textarea v-model="lessonForm.topic" rows="2" placeholder="Тема занятия"
                      class="w-full resize-none rounded-sm border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent"></textarea></label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Дата</span>
              <input v-model="lessonForm.date" placeholder="дд.мм.гггг"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label v-if="lessonForm.type === 'Лекция'" class="block"><span class="mb-1 block text-tiny uppercase text-text3">Часы</span>
              <input v-model.number="lessonForm.hour" type="number" min="0"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label v-if="lessonForm.type === 'Экзамен'" class="block"><span class="mb-1 block text-tiny uppercase text-text3">Пересдача</span>
              <input v-model="lessonForm.retake_date" placeholder="дд.мм.гггг"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <p v-if="lessonError" class="text-sm text-red">{{ lessonError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showLesson = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="savingLesson" @click="saveLesson">
            {{ savingLesson ? 'Сохранение…' : (editingLesson ? 'Сохранить' : 'Добавить') }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
