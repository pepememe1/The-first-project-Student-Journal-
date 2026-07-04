<script setup>
// TeacherJournal — журнал преподавателя (порт teacher_dashboard "journal"): выбор
// группы и своего предмета, матрица «студенты × занятия × оценки» + средний.
import { ref, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'

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
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <select v-model="subject" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
      </select>
      <span v-if="saving" class="self-center text-xs text-text3">Сохранение…</span>
      <span v-else-if="data?.students?.length" class="self-center text-xs text-text3">Клик по клетке — ввод оценки</span>
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
              {{ l.type.slice(0, 3) }}<br>№{{ l.number }}
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
  </div>
</template>
