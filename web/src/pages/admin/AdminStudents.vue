<script setup>
// AdminStudents — список студентов + CRUD (Phase B). Добавление/правка/удаление с
// выбором группы из списка (синкнутые группы БД + спарсенные из расписания). id
// студента на сервере — stud:login (как в синке десктопа); удаление мягкое (надгробие),
// поэтому изменения доезжают до десктопа обычным pull.
import { ref, computed, onMounted } from 'vue'
import { adminApi, scheduleApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }

const locale = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()
const all = ref([])
const loading = ref(true)
const q = ref('')
const groupChoices = ref([])
const showPass = ref(false)     // показать вводимый пароль в модалке (по глазку)

// ── Категория расписания + фильтр по группе (schedule/parser.py::CATEGORIES) —
// раньше фильтра по группе в веб-версии не было вообще (только текстовый поиск,
// десктоп такой фильтр уже имел) — заодно закрывает и этот разрыв.
const categories = ref([])
const categoryFilter = ref('')
const groupFilter = ref('')
const groupCategory = ref({})   // {имя группы: category}
async function loadCategories() {
  try { categories.value = (await scheduleApi.categories()).data.categories || [] }
  catch { categories.value = [] }
}
// Курс (3.5.5) — сужает список групп ВНУТРИ категории ЕЩЁ дальше (сортировка
// колледж/бакалавриат/заочное → курс → группа, как просили). Разведано с портала
// (столбец таблицы индекса), число курсов НЕ фиксировано на 4.
const courseFilter = ref('')
const byCourse = ref({})   // {курс: [имена с портала]} — для ТЕКУЩЕЙ categoryFilter (кнопки)
async function loadByCourse() {
  courseFilter.value = ''
  if (!categoryFilter.value) { byCourse.value = {}; return }
  try { byCourse.value = (await scheduleApi.groups(categoryFilter.value)).data.by_course || {} }
  catch { byCourse.value = {} }
}
const courseKeys = computed(() => Object.keys(byCourse.value).map(Number).sort((a, b) => a - b))

// ⚠️ (живой отзыв Влада) Курс раньше сужал только выпадающий список ГРУПП в фильтре —
// саму таблицу студентов не трогал вовсе (кнопка «нажимается, но не сортирует»), и
// столбца с курсом не было, чтобы вообще понять, где студент. Здесь — ОБЩАЯ карта
// {группа → курс} по ВСЕМ категориям сразу (не только по выбранной), нужна и для
// столбца (виден без выбора категории), и для реального фильтра строк ниже.
const groupCourse = ref({})
async function loadGroupCourseMap() {
  const map = {}
  for (const c of categories.value) {
    try {
      const by = (await scheduleApi.groups(c.key)).data.by_course || {}
      for (const [course, names] of Object.entries(by)) {
        for (const g of names) map[g] = Number(course)
      }
    } catch { /* эта категория недоступна — остальные всё равно посчитаем */ }
  }
  groupCourse.value = map
}

// Список групп в фильтре сужается под выбранную категорию, затем под курс — иначе
// можно было бы выбрать «колледж» и группу заочки одновременно и увидеть пусто без
// понятной причины.
const groupFilterChoices = computed(() => {
  let list = groupChoices.value
  if (categoryFilter.value) {
    list = list.filter((g) => (groupCategory.value[g] || 'college') === categoryFilter.value)
  }
  if (courseFilter.value) {
    const names = new Set(byCourse.value[courseFilter.value] || [])
    list = list.filter((g) => names.has(g))
  }
  return list
})
function setCategoryFilter(key) {
  categoryFilter.value = key
  loadByCourse()
  if (groupFilter.value && !groupFilterChoices.value.includes(groupFilter.value)) groupFilter.value = ''
}
function setCourseFilter(c) {
  courseFilter.value = c
  if (groupFilter.value && !groupFilterChoices.value.includes(groupFilter.value)) groupFilter.value = ''
}

// Пароль в БД хранится ХЕШЕМ и не показывается — глазок открывает то, что админ ВВОДИТ.
function fmtDT(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? '—' : d.toLocaleString(BCP47[locale.active] || 'ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function reload() {
  loading.value = true
  try { all.value = (await adminApi.students()).data.students || [] } catch { all.value = [] } finally { loading.value = false }
}

onMounted(async () => {
  await reload()
  await loadCategories()
  loadGroupCourseMap()   // фоном — таблица показывает «—», пока карта не готова, не блокируем список
  // Список групп для выбора: синкнутые (БД) + спарсенные из расписания, без дублей —
  // как _all_group_choices в десктопе.
  try {
    const dbGroups = (await adminApi.groups()).data.groups || []
    const dbG = dbGroups.map((g) => g.name)
    groupCategory.value = Object.fromEntries(dbGroups.map((g) => [g.name, g.category || 'college']))
    let parsed = []
    try { parsed = (await scheduleApi.groups()).data.groups || [] } catch { /* оффлайн — ок */ }
    groupChoices.value = [...new Set([...dbG, ...parsed].filter(Boolean))]
  } catch { /* */ }
})

const rows = computed(() => {
  const s = q.value.trim().toLowerCase()
  return all.value.filter((r) => {
    if (s && !`${r.surname} ${r.name} ${r.group} ${r.login}`.toLowerCase().includes(s)) return false
    if (groupFilter.value && r.group !== groupFilter.value) return false
    if (categoryFilter.value && (groupCategory.value[r.group] || 'college') !== categoryFilter.value) return false
    if (courseFilter.value && groupCourse.value[r.group] !== Number(courseFilter.value)) return false
    return true
  })
})

// Модалка создания/правки
const showForm = ref(false)
const editing = ref(null) // null = создание; иначе исходный login (ключ)
const form = ref({ surname: '', name: '', patronymic: '', login: '', group: '', password: '' })
const saving = ref(false)
const formError = ref('')

function openCreate() {
  editing.value = null
  form.value = { surname: '', name: '', patronymic: '', login: '', group: '', password: '' }
  formError.value = ''
  showForm.value = true
}
function openEdit(r) {
  editing.value = r.login
  //Имя и отчество — раздельно: сервер отдаёт first_name/patronymic (name — полная форма-ключ).
  form.value = {
    surname: r.surname, name: r.first_name ?? r.name, patronymic: r.patronymic ?? '',
    login: r.login, group: r.group, password: '',
  }
  formError.value = ''
  showForm.value = true
}

async function save() {
  const f = form.value
  if (!f.surname.trim() || !f.name.trim()) { formError.value = locale.t('adminStudents.enterSurnameName', 'Введите фамилию и имя'); return }
  if (!f.login.trim()) { formError.value = locale.t('adminStudents.enterLogin', 'Введите логин'); return }
  saving.value = true
  formError.value = ''
  try {
    if (editing.value) {
      await adminApi.updateStudent(editing.value, { surname: f.surname, name: f.name, patronymic: f.patronymic, group: f.group, password: f.password })
    } else {
      await adminApi.createStudent({ surname: f.surname, name: f.name, patronymic: f.patronymic, login: f.login, group: f.group, password: f.password })
    }
    showForm.value = false
    await reload()
  } catch (e) {
    formError.value = e?.response?.data?.detail || locale.t('adminStudents.saveFailed', 'Не удалось сохранить')
  } finally {
    saving.value = false
  }
}

async function del(r) {
  if (!(await confirm({ title: locale.t('adminStudents.confirmDelete', { name: `${r.surname} ${r.name}` }), okText: locale.t('common.delete'), danger: true }))) return
  try { await adminApi.deleteStudent(r.login); await reload() }
  catch (e) { toast.error(e?.response?.data?.detail || locale.t('adminStudents.deleteFailed', 'Не удалось удалить')) }
}
</script>

<template>
  <div class="space-y-4">
    <!-- Кнопки-категории (та же идея, что в «Расписании»/«Группах») — сужают список
         групп в фильтре ниже. -->
    <div v-if="categories.length > 1" class="flex flex-wrap gap-2">
      <button class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="!categoryFilter ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="setCategoryFilter('')">{{ locale.t('adminStudents.allCategories', 'Все категории') }}</button>
      <button v-for="c in categories" :key="c.key"
              class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="categoryFilter === c.key ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="setCategoryFilter(c.key)">{{ c.label }}</button>
    </div>

    <!-- Кнопки-курсы — ВНУТРИ выбранной категории (3.5.5), число курсов не
         фиксировано на 4 (разведано с портала). -->
    <div v-if="categoryFilter && courseKeys.length > 1" class="flex flex-wrap gap-2">
      <button class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="!courseFilter ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="setCourseFilter('')">{{ locale.t('adminGroups.allCourses', 'Все курсы') }}</button>
      <button v-for="c in courseKeys" :key="c"
              class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="courseFilter === c ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="setCourseFilter(c)">{{ locale.t('adminGroups.courseN', { n: c }) }}</button>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <input v-model="q" :placeholder="locale.t('adminStudents.searchPlaceholder', 'Поиск по ФИО, группе или логину…')"
             class="h-10 w-full max-w-sm rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent focus:bg-card" />
      <select v-model="groupFilter"
              class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option value="">{{ locale.t('adminStudents.allGroups', 'Все группы') }}</option>
        <option v-for="g in groupFilterChoices" :key="g" :value="g">{{ g }}</option>
      </select>
      <AppButton variant="green" size="sm" @click="openCreate">{{ locale.t('adminStudents.addAction', '+ Добавить') }}</AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colFullName', 'ФИО') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colGroup', 'Группа') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colCourse', 'Курс') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colLogin', 'Логин') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colPhone', 'Телефон') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colLastLogin', 'Посл. вход') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminStudents.colIp', 'IP') }}</th>
            <th class="px-4 py-2.5 text-right font-semibold">{{ locale.t('adminStudents.colActions', 'Действия') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="8" class="px-4 py-6 text-center text-text3">{{ locale.t('common.loading') }}</td></tr>
          <tr v-else-if="!rows.length"><td colspan="8" class="px-4 py-6 text-center text-text3">{{ locale.t('adminStudents.noStudents', 'Студентов нет') }}</td></tr>
          <tr v-for="(r, i) in rows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="whitespace-nowrap px-4 py-2.5 font-medium text-text">{{ r.surname }} {{ r.name }}</td>
            <td class="px-4 py-2.5 text-text2">{{ r.group || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text2">{{ groupCourse[r.group] ?? '—' }}</td>
            <td class="px-4 py-2.5 text-text2">{{ r.login || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text2">{{ r.phone || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3" :title="r.device ? locale.t('adminStudents.deviceTitle', { device: r.device }) : ''">{{ fmtDT(r.last_login) }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3">{{ r.ip || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="mr-3 text-text3 hover:text-accent" :title="locale.t('adminStudents.edit', 'Изменить')" @click="openEdit(r)">✎</button>
              <button class="text-text3 hover:text-red" :title="locale.t('common.delete')" @click="del(r)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Модалка создания/правки -->
    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ editing ? locale.t('adminStudents.editTitle', 'Изменить студента') : locale.t('adminStudents.addTitle', 'Добавить студента') }}</h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminStudents.surname', 'Фамилия') }}</span>
              <input v-model="form.surname" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminStudents.firstName', 'Имя') }}</span>
              <input v-model="form.name" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminStudents.patronymic', 'Отчество') }} <span class="text-text3 normal-case">{{ locale.t('adminStudents.optionalHint', '(необязательно)') }}</span></span>
            <input v-model="form.patronymic" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminStudents.colLogin', 'Логин') }}</span>
            <input v-model="form.login" :disabled="!!editing"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-60" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminStudents.colGroup', 'Группа') }}</span>
            <input v-model="form.group" list="admin-group-list" :placeholder="locale.t('adminStudents.groupPlaceholder', 'Выберите или введите группу')"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
            <datalist id="admin-group-list"><option v-for="g in groupChoices" :key="g" :value="g" /></datalist>
          </label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ editing ? locale.t('adminStudents.newPasswordHint', 'Новый пароль (пусто — не менять)') : locale.t('adminStudents.passwordLabel', 'Пароль') }}</span>
            <div class="relative">
              <input v-model="form.password" :type="showPass ? 'text' : 'password'" placeholder="••••••••"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 pr-10 text-sm text-text outline-none focus:border-accent" />
              <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-text3 hover:text-accent" @click="showPass = !showPass">
                {{ showPass ? '🙈' : '👁' }}
              </button>
            </div>
            <span class="mt-1 block text-tiny text-text3">{{ locale.t('adminStudents.passwordHashHint', 'Пароль в базе хранится хешем — показать можно только новый вводимый.') }}</span></label>
          <p v-if="formError" class="text-sm text-red">{{ formError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showForm = false">{{ locale.t('common.cancel') }}</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="save">
            {{ saving ? locale.t('adminStudents.saving', 'Сохранение…') : (editing ? locale.t('common.save') : locale.t('adminStudents.addAction2', 'Добавить')) }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
