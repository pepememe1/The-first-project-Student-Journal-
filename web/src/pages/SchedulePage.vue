<script setup>
// SchedulePage — расписание ВСГУТУ (порт ui/schedule_view.py). Недельная сетка:
// дни-колонки, карточки пар, переключатель I/II недели.
//
// Категории (портал читается в 4 разделах — schedule/parser.py::CATEGORIES):
// «Магистратура, колледж, ДОУ» (DEFAULT_CATEGORY) — единственная с реальными
// аккаунтами/журналом, остальные («Бакалавриат, специалитет», «Заочное 1/2») —
// только просмотр расписания. Кнопки-категории видны всем ролям; смена категории
// на неколледжевую переводит ЛЮБУЮ роль в режим выбора группы из списка — «моя
// группа»/«мои пары» имеют смысл только внутри колледжа, вне его для роли просто
// нет данных, которые можно было бы авто-подставить.
//
// Роли для КАТЕГОРИИ ПО УМОЛЧАНИЮ (колледж) — как и раньше:
//  • студент — сразу расписание СВОЕЙ группы (без выбора);
//  • преподаватель — сервер матчит его ФИО со спарсенными преподавателями портала:
//    совпало → сразу ЕГО пары; не совпало → две НЕвыбранные кнопки
//    «Расписание преподавателя» / «Расписание группы» (пункт 2);
//  • админ — выбор любой группы.
// Полный снимок для преподавателей сервер строит лениво в фоне (~минута) — пока
// готовится, показываем статус и кнопку «Проверить снова».
//
// Сессионные категории (Заочное 1/2, dated=true) — заголовки дней это конкретные
// календарные даты («Пнд, 06 апреля»), а не Пн-Сб, и число «недель» (сессионных
// блоков) не всегда 2 — см. dayColumns/weekButtons ниже.
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
const DEFAULT_CATEGORY = 'college'

const auth = useAuthStore()
const toast = useToast()
const isStudent = computed(() => auth.role === 'student')
const isTeacher = computed(() => auth.role === 'teacher')

const categories = ref([])
const category = ref(DEFAULT_CATEGORY)
const isDefaultCategory = computed(() => category.value === DEFAULT_CATEGORY)
const categoryDated = computed(() =>
  categories.value.find((c) => c.key === category.value)?.dated || false)

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
  (isTeacher.value && isDefaultCategory.value && mode.value !== 'group') ? '' : group.value)

async function downloadSchedule(fmt) {
  if (!exportGroup.value) return
  exporting.value = true
  try {
    const { data: blob } = await scheduleApi.exportFile(exportGroup.value, fmt, category.value)
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
  try {
    const r = (await scheduleApi.categories()).data
    categories.value = r.categories || []
    category.value = r.default || DEFAULT_CATEGORY
  } catch { categories.value = []; category.value = DEFAULT_CATEGORY }
  await enterCategory()
})

// Вход в категорию (при старте страницы и при каждой смене кнопки). Колледж —
// прежнее ролевое поведение (студент/препод авто, админ выбирает); любая другая
// категория — режим «выбор группы из списка» для ВСЕХ ролей, там нет ни своей
// группы, ни своего ФИО преподавателя — их просто неоткуда авто-подставить.
async function enterCategory() {
  data.value = null
  week.value = 1
  stopPoll()
  if (isDefaultCategory.value && isTeacher.value) {
    mode.value = ''
    await loadTeacher('')
    return
  }
  mode.value = 'group'
  group.value = ''
  await loadGroupsList()
  if (isDefaultCategory.value && isStudent.value) {
    await load()          // студент — сразу своя группа (сервер сам подставит)
  } else {
    loading.value = false // ждём выбора группы из списка
  }
}

async function onCategoryChange(key) {
  if (key === category.value) return
  category.value = key
  await enterCategory()
}

async function loadGroupsList() {
  try { groups.value = (await scheduleApi.groups(category.value)).data.groups || [] }
  catch { groups.value = [] }
}

async function load() {
  loading.value = true
  try {
    const r = (await scheduleApi.get(group.value || undefined, category.value)).data
    data.value = r
    group.value = r.group || group.value
    const wk = Object.keys(r.schedule?.weeks || {}).map(Number).sort((a, b) => a - b)
    //Сессионные категории — своя «текущая» неделя не существует (это не календарная
    //чётность, а порядковый номер сессии) — берём первый реально найденный блок.
    week.value = categoryDated.value ? (wk[0] || 1) : (r.week || 1)
  } catch { data.value = null } finally { loading.value = false }
}

let pollTimer = null
function stopPoll() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
onBeforeUnmount(stopPoll)

async function loadTeacher(name) {
  loading.value = true
  try {
    const r = (await scheduleApi.teacher(name, category.value)).data
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
  if (!groups.value.length) await loadGroupsList()
  if (group.value) await load()
  else loading.value = false
}
function refresh() {
  if (isDefaultCategory.value && isTeacher.value && mode.value !== 'group') {
    loadTeacher(mode.value === 'teacher' ? teacherName.value : '')
  } else load()
}

const weeks = computed(() => data.value?.schedule?.weeks || {})
const weekKeys = computed(() => Object.keys(weeks.value).map(Number).sort((a, b) => a - b))
// Кнопки недели/сессии: обычные категории — ВСЕГДА [1, 2] (как и раньше — кнопка
// нужна и тогда, когда у группы на эту чётность нет пар, просто покажет «нет
// занятий»); сессионные — реальное число блоков (не фиксировано, у разных групп
// заочки может отличаться).
const weekButtons = computed(() => {
  if (!categoryDated.value) return [1, 2]
  return weekKeys.value.length ? weekKeys.value : [1]
})
function weekButtonLabel(wk) {
  if (!categoryDated.value) {
    return (wk === 2 ? 'II неделя' : 'I неделя') + (data.value?.week === wk ? '  · сейчас' : '')
  }
  const days = Object.keys(weeks.value[String(wk)] || {})
  if (!days.length) return `Сессия ${wk}`
  const first = days[0].split(', ').pop()
  const last = days[days.length - 1].split(', ').pop()
  return first === last ? `Сессия ${wk} (${first})` : `Сессия ${wk} (${first}–${last})`
}
function dayLessons(dayKey) { return (weeks.value[String(week.value)] || {})[dayKey] || [] }
const hasAny = computed(() => data.value?.available && Object.keys(weeks.value).length)
// Дни-колонки: обычные категории — фиксированные 6 (даже пустые, как и раньше);
// сессионные — реальные даты ТЕКУЩЕЙ недели/сессии, в порядке разбора (уже
// хронологический — см. schedule/parser.py::parse_group_page_dated).
const dayColumns = computed(() => {
  if (!categoryDated.value) return DAYS
  return Object.keys(weeks.value[String(week.value)] || {}).map((d) => [d, d])
})
// Преподаватель ещё не выбрал режим и авто-матч не сработал → экран с двумя кнопками
// (только для категории по умолчанию — вне колледжа своего ФИО матчить не с чем).
const teacherChoice = computed(() => isDefaultCategory.value && isTeacher.value && mode.value === '')
</script>

<template>
  <div class="space-y-4">
    <!-- Категории портала (как на сайте) — видны всегда, независимо от режима ниже. -->
    <div v-if="categories.length > 1" class="flex flex-wrap gap-2">
      <button v-for="c in categories" :key="c.key"
              class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="category === c.key
                ? 'border-accent bg-accent text-white'
                : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="onCategoryChange(c.key)">
        {{ c.label }}
      </button>
    </div>

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
        <!-- Студент в категории по умолчанию: своя группа (ярлык). Преподаватель в
             ней же: свои пары / выбор коллеги / выбор группы. Все остальные случаи
             (админ, либо любая роль вне колледжа) — выбор группы из списка. -->
        <div v-if="isStudent && isDefaultCategory" class="flex h-10 items-center gap-2 rounded-sm border border-border2 bg-card2 px-3 text-sm">
          <GraduationCap class="size-4 text-accent" />
          <span class="font-medium text-text">{{ group || 'Моя группа' }}</span>
        </div>

        <template v-else-if="isDefaultCategory && isTeacher && mode !== 'group'">
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
          <button v-if="isDefaultCategory && isTeacher" class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline" @click="mode = ''; data = null">
            ← к выбору
          </button>
        </template>

        <div class="flex flex-wrap overflow-hidden rounded-sm border border-border2">
          <button v-for="wk in weekButtons" :key="wk" class="px-3 py-2 text-sm"
                  :class="week === wk ? 'bg-accent text-white' : 'bg-card2 text-text3'"
                  @click="week = wk">{{ weekButtonLabel(wk) }}</button>
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

        <span v-if="!categoryDated && data?.week" class="text-xs text-text3">Сейчас: {{ data.week === 2 ? 'II' : 'I' }} неделя</span>
      </div>

      <p v-if="loading" class="text-sm text-text3">Загрузка расписания…</p>
      <EmptyState v-else-if="!hasAny" title="Расписание недоступно"
                  :message="building ? 'Индекс расписания готовится на сервере (~минута) — нажмите «Обновить».'
                            : 'Не удалось получить снимок с портала ВСГУТУ (нет связи или расписание не найдено).'" />

      <!-- Десктоп показывает дни ОДНИМ горизонтальным рядом; на широком экране
           повторяем (6 колонок), на узких — переносим по 2–3. Для сессионных
           категорий число колонок не фиксировано — сетка просто перетекает. -->
      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div v-for="[key, full] in dayColumns" :key="key" class="rounded-lg border border-border bg-card p-3 shadow-card">
          <p class="mb-2 font-title text-base font-bold text-text">{{ full }}</p>
          <p v-if="!dayLessons(key).length" class="py-4 text-center text-xs text-text2">Занятий нет</p>
          <ul v-else class="space-y-2">
            <li v-for="(l, i) in dayLessons(key)" :key="i" class="rounded-md border border-border bg-card2 p-2.5">
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
