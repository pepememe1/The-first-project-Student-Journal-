<script setup>
// TeacherJournal — журнал преподавателя (порт teacher_dashboard "journal"): выбор
// группы и своего предмета, матрица «студенты × занятия × оценки» + средний.
import { ref, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'
import AppButton from '@/components/ui/AppButton.vue'

const groups = ref([])
const subjects = ref([])
const group = ref('')
const subject = ref('')
const data = ref(null)
const loading = ref(false)

onMounted(async () => {
  try {
    const o = (await teacherApi.overview()).data
    groups.value = o.groups || []
    subjects.value = o.subjects || []
    group.value = groups.value[0] || ''
    subject.value = subjects.value[0] || ''
  } catch { /* */ }
})

async function load() {
  if (!group.value || !subject.value) { data.value = null; return }
  loading.value = true
  try { data.value = (await teacherApi.journal(group.value, subject.value)).data } catch { data.value = null } finally { loading.value = false }
}
watch([group, subject], load)

const saving = ref(false)
// Ввод оценки прямо в клетке (Phase B). Оптимистично меняем клетку, шлём на сервер,
// затем перезагружаем журнал — средний пересчитывает СЕРВЕР (grading.py, единый
// источник). Пустое значение снимает оценку. При ошибке — откат клетки.
async function onGrade(s, l, value) {
  const v = (value || '').trim()
  const prev = s.grades[l.id] || ''
  if (v === prev) return
  s.grades[l.id] = v
  saving.value = true
  try {
    await teacherApi.setGrade(s.surname, s.name, l.id, v)
    await load()
  } catch (e) {
    s.grades[l.id] = prev
    alert('Не удалось сохранить оценку: ' + (e?.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

function gradeClass(g) {
  const v = (g || '').trim()
  if (v.startsWith('5')) return 'text-accent font-bold'
  if (v.startsWith('4')) return 'text-blue font-bold'
  if (v.startsWith('3')) return 'text-orange font-bold'
  if (v.startsWith('2') || v === 'Н') return 'text-red font-bold'
  return 'text-text2'
}

// Занятия/пары (Phase B): преподаватель наполняет журнал. Создание пишет в таблицу
// lessons (uuid) → десктоп получит через pull; удаление мягкое (надгробие).
const LESSON_TYPES = ['Практика', 'Лекция', 'Экзамен', 'Семинар', 'Лабораторная', 'Зачёт']
const showLesson = ref(false)
const lessonForm = ref({ type: 'Практика', number: 1, topic: '', date: '', hour: 0 })
const savingLesson = ref(false)
const lessonError = ref('')

function openLesson() {
  lessonForm.value = { type: 'Практика', number: (data.value?.lessons?.length || 0) + 1, topic: '', date: '', hour: 0 }
  lessonError.value = ''
  showLesson.value = true
}
async function saveLesson() {
  if (!group.value || !subject.value) { lessonError.value = 'Выберите группу и предмет'; return }
  savingLesson.value = true
  lessonError.value = ''
  try {
    await teacherApi.createLesson({ group: group.value, subject: subject.value, ...lessonForm.value })
    showLesson.value = false
    await load()
  } catch (e) { lessonError.value = e?.response?.data?.detail || 'Не удалось создать занятие' }
  finally { savingLesson.value = false }
}
async function delLesson(l) {
  if (!confirm(`Удалить занятие ${l.type} №${l.number}? Оценки этой пары перестанут учитываться.`)) return
  try { await teacherApi.deleteLesson(l.id); await load() }
  catch (e) { alert(e?.response?.data?.detail || 'Не удалось удалить') }
}

// Экспорт журнала в xlsx: сервер собирает файл (Times New Roman 14, как в десктопе),
// браузер скачивает через blob (нужен Authorization-заголовок — прямой ссылкой нельзя).
const exporting = ref(false)
async function exportXlsx() {
  exporting.value = true
  try {
    const { data: blob } = await teacherApi.journalXlsx(group.value, subject.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Журнал_${group.value}_${subject.value}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  } catch { alert('Не удалось выгрузить Excel') } finally { exporting.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <select v-model="subject" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
      </select>
      <span v-if="saving" class="self-center text-xs text-text3">Сохранение…</span>
      <span v-else-if="data?.students?.length" class="self-center text-xs text-text3">Клик по клетке — ввод оценки</span>
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

    <div v-else class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="sticky left-0 z-10 bg-bg2 px-4 py-2.5 font-semibold">Студент</th>
            <th v-for="l in data.lessons" :key="l.id" class="px-3 py-2.5 text-center font-semibold" :title="`${l.topic} · ${l.date}`">
              <div>{{ l.type.slice(0, 3) }}<br>№{{ l.number }}</div>
              <button class="mt-0.5 text-[10px] font-normal text-text3 hover:text-red" title="Удалить занятие" @click="delLesson(l)">✕</button>
            </th>
            <th class="px-4 py-2.5 text-right font-semibold">Средн.</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in data.students" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="sticky left-0 z-10 whitespace-nowrap bg-card px-4 py-2.5 font-medium text-text">{{ s.surname }} {{ s.name }}</td>
            <td v-for="l in data.lessons" :key="l.id" class="px-1.5 py-1.5 text-center">
              <input :value="s.grades[l.id]" @change="onGrade(s, l, $event.target.value)"
                     :class="gradeClass(s.grades[l.id])" placeholder="·"
                     class="h-8 w-11 rounded-sm border border-transparent bg-transparent text-center text-sm outline-none hover:border-border2 focus:border-accent focus:bg-card2" />
            </td>
            <td class="px-4 py-2.5 text-right font-title font-bold text-accent">{{ s.average || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Модалка создания занятия (пары) -->
    <div v-if="showLesson" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showLesson = false">
      <div class="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">Занятие · {{ group }} · {{ subject }}</h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Тип</span>
              <select v-model="lessonForm.type" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
                <option v-for="t in LESSON_TYPES" :key="t" :value="t">{{ t }}</option>
              </select></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">№</span>
              <input v-model.number="lessonForm.number" type="number" min="1"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Тема</span>
            <input v-model="lessonForm.topic" placeholder="Тема занятия"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Дата</span>
              <input v-model="lessonForm.date" placeholder="дд.мм.гггг"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Часы (лекции)</span>
              <input v-model.number="lessonForm.hour" type="number" min="0"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <p v-if="lessonError" class="text-sm text-red">{{ lessonError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showLesson = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="savingLesson" @click="saveLesson">{{ savingLesson ? 'Сохранение…' : 'Добавить' }}</AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
