<script setup>
// SchedulePage — расписание ВСГУТУ (порт ui/schedule_view.py). Недельная сетка:
// дни-колонки, карточки пар, переключатель I/II недели.
//
// Роли (как в десктопе):
//  • студент — сразу расписание СВОЕЙ группы (без выбора);
//  • преподаватель — сервер матчит его ФИО со спарсенными преподавателями портала:
//    совпало → сразу ЕГО пары; не совпало → две НЕвыбранные кнопки
//    «Расписание преподавателя» / «Расписание группы» (пункт 2);
//  • админ — выбор любой группы.
// Полный снимок для преподавателей сервер строит лениво в фоне (~минута) — пока
// готовится, показываем статус и кнопку «Проверить снова».
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { RotateCw, GraduationCap, User, Users, Download } from '@lucide/vue'
import { scheduleApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import EmptyState from '@/components/ui/EmptyState.vue'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'

const DAYS = [['Пнд', 'Понедельник'], ['Втр', 'Вторник'], ['Срд', 'Среда'],
              ['Чтв', 'Четверг'], ['Птн', 'Пятница'], ['Сбт', 'Суббота']]
const KIND = { лек: ['Лекция', 'blue'], пр: ['Практика', 'green'], лаб: ['Лаборат.', 'muted'],
               сем: ['Семинар', 'muted'], конс: ['Консульт.', 'muted'], зач: ['Зачёт', 'red'], экз: ['Экзамен', 'red'] }

const auth = useAuthStore()
const toast = useToast()
const isStudent = computed(() => auth.role === 'student')
const isTeacher = computed(() => auth.role === 'teacher')

const groups = ref([])
const group = ref('')
const week = ref(1)
const data = ref(null)
const loading = ref(true)

// Режим преподавателя: '' — ещё не выбран (две кнопки), 'me' — свои пары (авто-матч),
// 'teacher' — конкретный преподаватель из списка, 'group' — расписание группы.
const mode = ref('')
const teachers = ref([])
const teacherName = ref('')
const building = ref(false)

// ── Выгрузка расписания файлом ──────────────────────────────────────────────────
// Сервер выгружает расписание ГРУППЫ, поэтому в преподавательском виде («мои пары»,
// где группы как таковой нет) кнопки не показываем: они молча выгрузили бы не то,
// что человек видит на экране.
const exporting = ref(false)
const exportGroup = computed(() =>
  (isTeacher.value && mode.value !== 'group') ? '' : group.value)

async function downloadSchedule(fmt) {
  if (!exportGroup.value) return
  exporting.value = true
  try {
    const { data: blob } = await scheduleApi.exportFile(exportGroup.value, fmt)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Расписание_${exportGroup.value}.${fmt === 'docx' ? 'docx' : 'xlsx'}`
      .replaceAll('/', '-')
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    toast.error('Не удалось выгрузить расписание')
  } finally { exporting.value = false }
}

onMounted(async () => {
  if (isTeacher.value) {
    await loadTeacher('')          // авто-попытка по своему ФИО
    return
  }
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

let pollTimer = null
function stopPoll() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
onBeforeUnmount(stopPoll)

async function loadTeacher(name) {
  loading.value = true
  try {
    const r = (await scheduleApi.teacher(name)).data
    building.value = !!r.building
    teachers.value = r.teachers || []
    week.value = r.week || 1
    if (r.available) {
      data.value = r
      teacherName.value = r.teacher
      if (r.matched_self) mode.value = 'me'
      else if (name) mode.value = 'teacher'
    } else {
      data.value = null
      if (name) mode.value = 'teacher'   // выбрал вручную, но пар нет — остаёмся в режиме
    }
    // Снимок ещё строится на сервере — АВТО-повтор через 5 с (без ручного «Обновить»),
    // пока не будет готов. Прогрев при старте сервера делает ожидание редким.
    stopPoll()
    if (building.value) pollTimer = setTimeout(() => loadTeacher(name), 5000)
  } catch { data.value = null } finally { loading.value = false }
}

async function chooseTeacherMode() {
  mode.value = 'teacher'
  if (!teachers.value.length) await loadTeacher('')
}
async function chooseGroupMode() {
  mode.value = 'group'
  data.value = null
  if (!groups.value.length) {
    try { groups.value = (await scheduleApi.groups()).data.groups || [] } catch { groups.value = [] }
  }
  if (group.value) await load()
  else loading.value = false
}
function refresh() {
  if (isTeacher.value && mode.value !== 'group') loadTeacher(mode.value === 'teacher' ? teacherName.value : '')
  else load()
}

const weeks = computed(() => data.value?.schedule?.weeks || {})
function dayLessons(short) { return (weeks.value[String(week.value)] || {})[short] || [] }
const hasAny = computed(() => data.value?.available && Object.keys(weeks.value).length)
// Преподаватель ещё не выбрал режим и авто-матч не сработал → экран с двумя кнопками.
const teacherChoice = computed(() => isTeacher.value && mode.value === '')
</script>

<template>
  <div class="space-y-4">
    <!-- Преподаватель без авто-совпадения ФИО: две НЕвыбранные кнопки (пункт 2). -->
    <div v-if="teacherChoice" class="flex min-h-[50vh] flex-col items-center justify-center gap-4">
      <p v-if="loading" class="text-sm text-text3">Загрузка…</p>
      <template v-else>
        <p class="text-sm text-text2">
          {{ building ? 'Индекс преподавателей ещё готовится на сервере (~минута).' :
             'Ваше ФИО не найдено в спарсенном расписании — выберите, что показать:' }}
        </p>
        <div class="flex flex-wrap justify-center gap-3">
          <AppButton variant="ghost" :disabled="building" @click="chooseTeacherMode">
            <User class="size-4" /> Расписание преподавателя
          </AppButton>
          <AppButton variant="ghost" @click="chooseGroupMode">
            <Users class="size-4" /> Расписание группы
          </AppButton>
        </div>
        <AppButton v-if="building" variant="green" size="sm" @click="loadTeacher('')">
          <RotateCw class="size-3.5" /> Проверить снова
        </AppButton>
      </template>
    </div>

    <template v-else>
      <div class="flex flex-wrap items-center gap-3">
        <!-- Студент: своя группа (ярлык). Преподаватель: свои пары / выбор коллеги /
             выбор группы. Админ: выбор группы. -->
        <div v-if="isStudent" class="flex h-10 items-center gap-2 rounded-sm border border-border2 bg-card2 px-3 text-sm">
          <GraduationCap class="size-4 text-accent" />
          <span class="font-medium text-text">{{ group || 'Моя группа' }}</span>
        </div>

        <template v-else-if="isTeacher && mode !== 'group'">
          <div v-if="mode === 'me'" class="flex h-10 items-center gap-2 rounded-sm border border-border2 bg-card2 px-3 text-sm">
            <User class="size-4 text-accent" />
            <span class="font-medium text-text">{{ teacherName }}</span>
            <span class="text-xs text-text3">· мои пары</span>
          </div>
          <select v-else v-model="teacherName" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:w-auto sm:max-w-64"
                  @change="loadTeacher(teacherName)">
            <option value="" disabled>Преподаватель…</option>
            <option v-for="t in teachers" :key="t" :value="t">{{ t }}</option>
          </select>
          <button class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline" @click="chooseGroupMode">
            смотреть по группе
          </button>
        </template>

        <template v-else>
          <select v-model="group" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:w-auto" @change="load">
            <option v-if="!groups.length" :value="group">{{ group || 'Группа' }}</option>
            <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
          </select>
          <button v-if="isTeacher" class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline" @click="mode = ''; data = null">
            ← к выбору
          </button>
        </template>

        <div class="flex overflow-hidden rounded-sm border border-border2">
          <button class="px-3 py-2 text-sm" :class="week === 1 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 1">I неделя</button>
          <button class="px-3 py-2 text-sm" :class="week === 2 ? 'bg-accent text-white' : 'bg-card2 text-text3'" @click="week = 2">II неделя</button>
        </div>
        <AppButton variant="ghost" size="sm" @click="refresh"><RotateCw class="size-3.5" /> Обновить</AppButton>

        <!-- Выгрузка расписания файлом. Показываем только для расписания ГРУППЫ:
             у преподавательского вида группы нет, а сервер выгружает именно её. -->
        <template v-if="exportGroup && hasAny">
          <AppButton variant="ghost" size="sm" :disabled="exporting"
                     @click="downloadSchedule('xlsx')">
            <Download class="size-3.5" /> Excel
          </AppButton>
          <AppButton variant="ghost" size="sm" :disabled="exporting"
                     @click="downloadSchedule('docx')">
            <Download class="size-3.5" /> Word
          </AppButton>
        </template>

        <span v-if="data?.week" class="text-xs text-text3">Сейчас: {{ data.week === 2 ? 'II' : 'I' }} неделя</span>
      </div>

      <p v-if="loading" class="text-sm text-text3">Загрузка расписания…</p>
      <EmptyState v-else-if="!hasAny" title="Расписание недоступно"
                  :message="building ? 'Индекс расписания готовится на сервере (~минута) — нажмите «Обновить».'
                            : 'Не удалось получить снимок с портала ВСГУТУ (нет связи или расписание не найдено).'" />

      <!-- Десктоп показывает 6 дней ОДНИМ горизонтальным рядом; на широком экране
           повторяем (6 колонок), на узких — переносим по 2–3. -->
      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
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
              <!-- У пары преподавателя показываем ГРУППУ (у кого ведёт), у групповой — преподавателя. -->
              <p v-if="l.group || l.teacher || l.room" class="mt-0.5 text-xs text-text3">
                {{ l.group ? `Группа ${l.group}` : l.teacher }}<span v-if="l.room"> · ауд. {{ l.room }}</span>
              </p>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </div>
</template>
