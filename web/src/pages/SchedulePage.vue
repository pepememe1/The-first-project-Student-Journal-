<script setup>
// SchedulePage — расписание ВСГУТУ (порт ui/schedule_view.py). Недельная сетка:
// дни-колонки, карточки пар (№ + время, тип, предмет, преподаватель, аудитория),
// переключатель I/II недели. Данные — /web/schedule (серверный парсер портала).
import { ref, computed, onMounted } from 'vue'
import { RotateCw, GraduationCap } from '@lucide/vue'
import { scheduleApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import EmptyState from '@/components/ui/EmptyState.vue'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'

const DAYS = [['Пнд', 'Понедельник'], ['Втр', 'Вторник'], ['Срд', 'Среда'],
              ['Чтв', 'Четверг'], ['Птн', 'Пятница'], ['Сбт', 'Суббота']]
const KIND = { лек: ['Лекция', 'blue'], пр: ['Практика', 'green'], лаб: ['Лаборат.', 'muted'],
               сем: ['Семинар', 'muted'], конс: ['Консульт.', 'muted'], зач: ['Зачёт', 'red'], экз: ['Экзамен', 'red'] }

const groups = ref([])
const group = ref('')
const week = ref(1)
const data = ref(null)
const loading = ref(true)
const auth = useAuthStore()
// Студенту группа фиксирована (как в десктопе): расписание его группы открывается
// сразу, без выбора. Преподаватель/админ выбирают любую группу.
const isStudent = computed(() => auth.role === 'student')

onMounted(async () => {
  // Студенту список всех групп не нужен — сервер сам отдаст его группу (user.group_name).
  if (!isStudent.value) {
    try { groups.value = (await scheduleApi.groups()).data.groups || [] } catch { groups.value = [] }
  }
  await load()
})

async function load() {
  loading.value = true
  try {
    const r = (await scheduleApi.get(group.value || undefined)).data
    data.value = r
    group.value = r.group || group.value
    week.value = r.week || 1
  } catch { data.value = null } finally { loading.value = false }
}

const weeks = computed(() => data.value?.schedule?.weeks || {})
function dayLessons(short) { return (weeks.value[String(week.value)] || {})[short] || [] }
const hasAny = computed(() => data.value?.available && Object.keys(weeks.value).length)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <!-- Студент: группа фиксирована (как в десктопе) — ярлык без выбора.
           Преподаватель/админ: выбор любой группы колледжа. -->
      <div v-if="isStudent" class="flex h-10 items-center gap-2 rounded-sm border border-border2 bg-card2 px-3 text-sm">
        <GraduationCap class="size-4 text-accent" />
        <span class="font-medium text-text">{{ group || 'Моя группа' }}</span>
      </div>
      <select v-else v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" @change="load">
        <option v-if="!groups.length" :value="group">{{ group || 'Группа' }}</option>
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <div class="flex overflow-hidden rounded-sm border border-border2">
        <button class="px-3 py-2 text-sm" :class="week === 1 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 1">I неделя</button>
        <button class="px-3 py-2 text-sm" :class="week === 2 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 2">II неделя</button>
      </div>
      <AppButton variant="ghost" size="sm" @click="load"><RotateCw class="size-3.5" /> Обновить</AppButton>
      <span v-if="data?.week" class="text-xs text-text3">Сейчас: {{ data.week === 2 ? 'II' : 'I' }} неделя</span>
    </div>

    <p v-if="loading" class="text-sm text-text3">Загрузка расписания…</p>
    <EmptyState v-else-if="!hasAny" title="Расписание недоступно"
                message="Не удалось получить снимок с портала ВСГУТУ (нет связи или группа не найдена). Попробуйте обновить." />

    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="[short, full] in DAYS" :key="short" class="rounded-lg border border-border bg-card p-3 shadow-card">
        <p class="mb-2 font-title text-base font-bold text-text">{{ full }}</p>
        <p v-if="!dayLessons(short).length" class="py-4 text-center text-xs text-text2">Занятий нет</p>
        <ul v-else class="space-y-2">
          <li v-for="(l, i) in dayLessons(short)" :key="i" class="rounded-md border border-border bg-card2 p-2.5">
            <div class="mb-1 flex items-center justify-between gap-2">
              <span class="text-xs font-semibold text-text3">{{ l.pair_no }}. {{ l.time }}</span>
              <Badge v-if="l.kind" :variant="(KIND[l.kind] || ['', 'muted'])[1]">{{ (KIND[l.kind] || [l.kind])[0] }}</Badge>
            </div>
            <p class="text-sm font-medium text-text">{{ l.subject || l.raw }}</p>
            <p v-if="l.teacher || l.room" class="mt-0.5 text-xs text-text3">
              {{ l.teacher }}<span v-if="l.room"> · ауд. {{ l.room }}</span>
            </p>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
