<script setup>
// AdminGroups — группы + CRUD (Phase B). Создание/правка (список предметов группы) /
// удаление; кнопка «🏫 Из расписания» добавляет спарсенные группы колледжа (как в
// десктопе). Пишется в те же таблицы (id=grp:name) → синкается в десктоп.
import { ref, computed, watch, onMounted } from 'vue'
import { adminApi, scheduleApi, termsApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'

const toast = useToast()
const { confirm } = useConfirm()
const rows = ref([])
const loading = ref(true)
const allSubjects = ref([])
const parsedGroups = ref([])
const allTeachers = ref([])   // §ролей: [{id, name, subjects}] — для выбора препода на предмет

// ── Категории расписания (schedule/parser.py::CATEGORIES) — та же идея, что в
// «Расписании»: кнопки-фильтр сверху таблицы + выбор при создании группы. «Все
// категории» по умолчанию — 100% прежнее поведение (видно всё).
const categories = ref([])
const categoryFilter = ref('')
const filteredRows = computed(() => {
  if (!categoryFilter.value) return rows.value
  return rows.value.filter((g) => (g.category || 'college') === categoryFilter.value)
})
const nonCollegeCategories = computed(() => categories.value.filter((c) => c.key !== 'college'))
async function loadCategories() {
  try { categories.value = (await scheduleApi.categories()).data.categories || [] }
  catch { categories.value = [] }
}
function categoryLabel(key) {
  return categories.value.find((c) => c.key === key)?.label || key
}

// ── Учебный период + перевод на курс (rollover) ─────────────────────────────────
const currentTerm = ref(null)
const rolling = ref(false)
function termLabel(t) { return t ? `${t.year} · ${t.semester === 1 ? 'осенний' : 'весенний'} семестр` : '' }
async function loadTerm() {
  try { currentTerm.value = (await termsApi.list()).data.current } catch { /* */ }
}
async function rollover() {
  const next = currentTerm.value?.semester === 1 ? 'весенний семестр' : 'осенний семестр следующего года'
  const ok = await confirm({
    title: `Перевести на следующий учебный период (${next})?`,
    message: 'Текущий семестр станет архивом (только чтение), новый — активным. Группы и студенты сохранятся, оценки нового семестра — с чистого листа.',
    okText: 'Перевести',
  })
  if (!ok) return
  rolling.value = true
  try {
    const r = (await adminApi.rolloverTerm()).data
    currentTerm.value = r.current
    toast.success(`Готово. Текущий период: ${termLabel(r.current)}.`)
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось перевести') }
  finally { rolling.value = false }
}

async function reload() {
  loading.value = true
  try { rows.value = (await adminApi.groups()).data.groups || [] } catch { rows.value = [] } finally { loading.value = false }
}
onMounted(async () => {
  await reload()
  await loadTerm()
  await loadCategories()
  try { allSubjects.value = (await adminApi.subjects()).data.subjects?.map((s) => s.name) || [] } catch { /* */ }
  try { parsedGroups.value = (await scheduleApi.groups()).data.groups || [] } catch { /* */ }
  try { allTeachers.value = (await adminApi.teachers()).data.teachers || [] } catch { /* */ }
})
// Преподаватели, у которых ЕСТЬ данный предмет (Влад: «нажали математику — все преподы,
// у которых указана математика в предметах») — фильтр на клиенте, без нового запроса.
function teachersFor(subject) {
  return allTeachers.value.filter((t) => (t.subjects || []).includes(subject))
}

const showForm = ref(false)
const editing = ref(null)
const form = ref({ name: '', subjects: [], category: 'college' })
const saving = ref(false)
const formError = ref('')
const importing = ref(false)

function openCreate() {
  editing.value = null
  form.value = { name: '', subjects: [], category: 'college' }
  formError.value = ''; showForm.value = true
}
function openEdit(g) {
  editing.value = g.name
  form.value = { name: g.name, subjects: [...(g.subjects || [])], category: g.category || 'college' }
  formError.value = ''; showForm.value = true
}
function toggleSubject(s) {
  const i = form.value.subjects.indexOf(s)
  if (i >= 0) form.value.subjects.splice(i, 1)
  else form.value.subjects.push(s)
}
async function save() {
  const f = form.value
  if (!f.name.trim()) { formError.value = 'Введите название группы'; return }
  saving.value = true; formError.value = ''
  try {
    if (editing.value) await adminApi.updateGroup(editing.value, { subjects: f.subjects, category: f.category })
    else await adminApi.createGroup({ name: f.name.trim(), subjects: f.subjects, category: f.category })
    showForm.value = false; await reload()
  } catch (e) { formError.value = e?.response?.data?.detail || 'Не удалось сохранить' }
  finally { saving.value = false }
}
async function del(g) {
  if (!(await confirm({ title: `Удалить группу ${g.name}?`, okText: 'Удалить', danger: true }))) return
  try { await adminApi.deleteGroup(g.name); await reload() }
  catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось удалить') }
}
// ── Учебные часы группы («пройдено X из Y») ─────────────────────────────────────
// Часы задаются на СЕМЕСТР и по КАЖДОМУ предмету, поэтому это отдельное окно, а не поле
// в форме группы. Сохраняем пачкой одним запросом: одно нажатие «Сохранить» не должно
// превращаться в полтора десятка запросов с половинчатым результатом при обрыве связи.
const showHours = ref(false)
const hoursGroup = ref('')
const hoursRows = ref([])          // [{subject, hours_total, hours_done}]
const hoursTerm = ref(null)
const hoursLoading = ref(false)
const hoursSaving = ref(false)

async function openHours(g) {
  hoursGroup.value = g.name
  hoursRows.value = []
  showHours.value = true
  hoursLoading.value = true
  try {
    const r = (await adminApi.groupHours(g.name)).data
    hoursRows.value = r.subjects || []
    hoursTerm.value = r.term || null
  } catch (e) {
    toast.error(e?.response?.data?.detail || 'Не удалось загрузить часы')
    showHours.value = false
  } finally { hoursLoading.value = false }
}

async function saveHours() {
  hoursSaving.value = true
  try {
    const hours = {}
    const teachers = {}
    const zet = {}
    hoursRows.value.forEach((r) => {
      hours[r.subject] = Number(r.hours_total) || 0
      teachers[r.subject] = r.teacher_id || ''
      //ЗЕТ: пусто/не число — снять (null), НЕ подставлять zet_hint автоматически
      //(docs/PLAN-ZET.md §10 — подсказка, а не источник правды).
      const zv = r.zet
      zet[r.subject] = (zv === '' || zv === null || zv === undefined || Number.isNaN(Number(zv)))
        ? null : Number(zv)
    })
    await adminApi.saveGroupHours(hoursGroup.value, hours, teachers, zet)
    toast.success('Часы сохранены')
    showHours.value = false
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось сохранить') }
  finally { hoursSaving.value = false }
}

// ── Импорт специальности/учебного плана ВСГУТУ (parsers/esstu_parser.py) ────────
// Отдельно от «Из расписания» выше: тот берёт ТОЛЬКО названия предметов с портала
// расписания, а это — целиком специальность+год поступления → часы/ЗЕТ по каждому
// предмету ИМЕННО текущего курса/семестра (курс считается от года поступления,
// см. серверный study_hours.course_and_semester — счётчик от даты, а не хранимое
// число, чтобы через год не protaskaть группу вручную).
const showImport = ref(false)
const importGroup = ref('')
const importSpecialties = ref([])
const importLoadingList = ref(false)
const importForm = ref({ specialty_code: '', enrollment_year: '' })
const importYears = ref([])          // реальные годы набора с опубликованным планом
const importLoadingYears = ref(false)
const importSaving = ref(false)
const importError = ref('')
const importResult = ref(null)   // {course, semester, imported, unmapped, saved_hours}

// Год поступления — ВЫБОР из реально опубликованных на сайте планов, а не
// ручной ввод числа (админ почти всегда промахивался мимо доступных лет —
// на сайте обычно только 3-5 последних, не с основания колледжа). Список
// зависит от специальности — перегружаем при каждой её смене.
watch(() => importForm.value.specialty_code, async (code) => {
  importYears.value = []
  importForm.value.enrollment_year = ''
  if (!code) return
  importLoadingYears.value = true
  try {
    const r = (await adminApi.esstuPlanYears(code)).data
    importYears.value = r.years || []
    if (importYears.value.length) importForm.value.enrollment_year = importYears.value[0]
  } catch { /* остаётся пустым — форма покажет «нет доступных годов» */ }
  finally { importLoadingYears.value = false }
})

async function openImport(g) {
  importGroup.value = g.name
  importResult.value = null
  importError.value = ''
  importYears.value = []
  importForm.value = { specialty_code: '', enrollment_year: '' }
  showImport.value = true
  importLoadingList.value = true
  try {
    const r = (await adminApi.esstuSpecialties(g.name)).data
    importSpecialties.value = r.specialties || []
    if (r.suggested_code) importForm.value.specialty_code = r.suggested_code   // будит watch выше
  } catch (e) {
    importError.value = e?.response?.data?.detail || 'Не удалось получить список специальностей'
  } finally { importLoadingList.value = false }
}

async function runImport() {
  const f = importForm.value
  if (!f.specialty_code || !f.enrollment_year) {
    importError.value = 'Выберите специальность и год поступления'
    return
  }
  importSaving.value = true; importError.value = ''; importResult.value = null
  try {
    const r = (await adminApi.importEsstu(importGroup.value, f.specialty_code, Number(f.enrollment_year))).data
    importResult.value = r
    await reload()
  } catch (e) { importError.value = e?.response?.data?.detail || 'Не удалось импортировать план' }
  finally { importSaving.value = false }
}

// ── Импорт группы по категории расписания (Бакалавриат/Заочное 1/2) ─────────────
// Отдельно от ESSTU-импорта выше (тот — предметы+часы+ЗЕТ для УЖЕ существующей
// колледж-группы) и от «Из расписания» ниже (тот — тоже только колледж). Здесь —
// ЗАВОДИМ саму группу как каталожную запись, связанную с расписанием, без
// предметов/часов/журнала (у небюджетных категорий их нет и не будет).
const showScheduleImport = ref(false)
const scheduleImportCategory = ref('')
const scheduleImportGroups = ref([])
const scheduleImportGroupName = ref('')
const scheduleImportLoadingGroups = ref(false)
const scheduleImportSaving = ref(false)
const scheduleImportError = ref('')

watch(scheduleImportCategory, async (key) => {
  scheduleImportGroups.value = []
  scheduleImportGroupName.value = ''
  if (!key) return
  scheduleImportLoadingGroups.value = true
  try { scheduleImportGroups.value = (await scheduleApi.groups(key)).data.groups || [] }
  catch { /* остаётся пустым — форма покажет «нет данных» */ }
  finally { scheduleImportLoadingGroups.value = false }
})

function openScheduleImport() {
  scheduleImportError.value = ''
  showScheduleImport.value = true
  const key = nonCollegeCategories.value[0]?.key || ''
  if (key === scheduleImportCategory.value) scheduleImportCategory.value = ''   // форсируем watch
  scheduleImportCategory.value = key
}

async function runScheduleImport() {
  if (!scheduleImportCategory.value || !scheduleImportGroupName.value) {
    scheduleImportError.value = 'Выберите категорию и группу'
    return
  }
  scheduleImportSaving.value = true; scheduleImportError.value = ''
  try {
    await adminApi.importScheduleCategory(scheduleImportCategory.value, scheduleImportGroupName.value)
    toast.success(`Группа «${scheduleImportGroupName.value}» добавлена.`)
    showScheduleImport.value = false
    await reload()
  } catch (e) { scheduleImportError.value = e?.response?.data?.detail || 'Не удалось импортировать' }
  finally { scheduleImportSaving.value = false }
}

// «Из расписания» — привязывает к каждой группе предметы ИЗ её расписания (портал
// ВСГУТУ) и пополняет каталог. Снимок строится на сервере лениво (~минута): если он
// ещё готовится — просим нажать позже.
async function importParsed() {
  importing.value = true
  try {
    const r = (await adminApi.bindSubjects()).data
    if (!r.ok && r.building) {
      toast.info('Индекс расписания готовится на сервере (~минута). Нажми «🏫 Из расписания» ещё раз чуть позже.')
    } else {
      toast.success(`Готово: групп обновлено — ${r.bound}, предметов в каталоге — ${r.subjects}.` +
            (r.building ? ' (индекс ещё дообновляется — можно повторить для полноты)' : ''))
      await reload()
      try { allSubjects.value = (await adminApi.subjects()).data.subjects?.map((s) => s.name) || [] } catch { /* */ }
    }
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось выполнить') }
  finally { importing.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <div v-if="currentTerm" class="mr-auto flex items-center gap-2 text-sm">
        <span class="text-text3">Учебный период:</span>
        <Badge variant="green">{{ termLabel(currentTerm) }}</Badge>
      </div>
      <AppButton variant="ghost" size="sm" :disabled="rolling" @click="rollover">
        {{ rolling ? 'Перевод…' : '⏭ Перевод на курс' }}
      </AppButton>
      <AppButton variant="ghost" size="sm" :disabled="importing" @click="importParsed">
        {{ importing ? 'Обновление…' : 'Обновить группы' }}
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="openScheduleImport">🌐 Импорт по категории</AppButton>
      <AppButton variant="green" size="sm" @click="openCreate">+ Добавить</AppButton>
    </div>

    <!-- Кнопки-категории (та же идея, что в «Расписании») — фильтр таблицы ниже. -->
    <div v-if="categories.length > 1" class="flex flex-wrap gap-2">
      <button class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="!categoryFilter ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="categoryFilter = ''">Все категории</button>
      <button v-for="c in categories" :key="c.key"
              class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
              :class="categoryFilter === c.key ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
              @click="categoryFilter = c.key">{{ c.label }}</button>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">Группа</th>
            <th class="px-4 py-2.5 font-semibold">Категория</th>
            <th class="px-4 py-2.5 text-right font-semibold">Студентов</th>
            <th class="px-4 py-2.5 font-semibold">Предметы</th>
            <th class="px-4 py-2.5 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="px-4 py-6 text-center text-text3">Загрузка…</td></tr>
          <tr v-else-if="!filteredRows.length"><td colspan="5" class="px-4 py-6 text-center text-text3">Групп нет</td></tr>
          <tr v-for="(g, i) in filteredRows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="px-4 py-2.5 font-semibold text-text">{{ g.name }}</td>
            <td class="px-4 py-2.5"><Badge variant="muted">{{ categoryLabel(g.category || 'college') }}</Badge></td>
            <td class="px-4 py-2.5 text-right text-text2">{{ g.students }}</td>
            <td class="px-4 py-2.5">
              <div class="flex flex-wrap gap-1.5">
                <Badge v-for="s in (g.subjects || []).slice(0, 4)" :key="s" variant="muted">{{ s }}</Badge>
                <span v-if="(g.subjects?.length || 0) > 4" class="text-xs text-text3">+{{ g.subjects.length - 4 }}</span>
                <span v-if="!g.subjects?.length" class="text-text3">—</span>
              </div>
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="mr-3 text-text3 hover:text-accent" title="Импорт специальности/плана с сайта ВСГУТУ" @click="openImport(g)">🎓</button>
              <button class="mr-3 text-text3 hover:text-accent" title="Учебные часы по предметам" @click="openHours(g)">🕐</button>
              <button class="mr-3 text-text3 hover:text-accent" title="Изменить" @click="openEdit(g)">✎</button>
              <button class="text-text3 hover:text-red" title="Удалить" @click="del(g)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── Учебные часы группы ─────────────────────────────────────────────────── -->
    <div v-if="showHours" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showHours = false">
      <div class="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="font-title text-lg font-bold text-text">Учебные часы · {{ hoursGroup }}</h3>
        <p class="mb-4 mt-1 text-xs text-text3">
          Часы на семестр по каждому предмету. Пройденное считается по лекциям и практикам
          (одно занятие — 2 академических часа); домашние задания в часы не входят.
          <span v-if="hoursTerm"> Период: {{ hoursTerm.year }} · {{ hoursTerm.semester === 1 ? 'осенний' : 'весенний' }}.</span>
        </p>

        <p v-if="hoursLoading" class="py-6 text-center text-sm text-text3">Загрузка…</p>
        <p v-else-if="!hoursRows.length" class="py-6 text-center text-sm text-text3">
          У группы нет предметов — сначала задайте их кнопкой ✎.
        </p>
        <div v-else class="max-h-80 space-y-2 overflow-y-auto">
          <div v-for="r in hoursRows" :key="r.subject"
               class="rounded-sm border border-border2 px-2 py-1.5 hover:bg-bg2">
            <div class="flex items-center gap-3">
              <span class="min-w-0 flex-1 truncate text-sm text-text" :title="r.subject">{{ r.subject }}</span>
              <span class="shrink-0 text-xs text-text3">пройдено {{ r.hours_done }} ч</span>
              <input v-model.number="r.hours_total" type="number" min="0" step="2"
                     class="h-9 w-24 shrink-0 rounded-sm border border-border2 bg-card2 px-2 text-right text-sm text-text outline-none focus:border-accent" />
            </div>
            <!-- ЗЕТ (docs/PLAN-ZET.md): подсказка zet_hint — СЕРАЯ, только placeholder,
                 автоматом никогда не сохраняется, пока администратор явно не впишет число. -->
            <div class="mt-1.5 flex items-center gap-2">
              <span class="shrink-0 text-xs text-text3">ЗЕТ</span>
              <input v-model="r.zet" type="number" min="0" step="0.1"
                     :placeholder="r.zet_hint ? String(r.zet_hint) : ''"
                     class="h-8 w-20 shrink-0 rounded-sm border border-border2 bg-card2 px-2 text-right text-xs text-text outline-none placeholder:text-text3 focus:border-accent" />
              <span v-if="r.zet_hint" class="text-[11px] text-text3">← {{ r.zet_hint }} по формуле (72ч/36)</span>
            </div>
            <!-- §ролей: препод, ведущий эту группу по этому предмету — единственный
                 источник правды «какие группы видит препод» (webdata.teacher_assignments). -->
            <select v-model="r.teacher_id"
                    class="mt-1.5 h-8 w-full rounded-sm border border-border2 bg-card2 px-2 text-xs text-text2 outline-none focus:border-accent">
              <option value="">— преподаватель не назначен —</option>
              <option v-for="t in teachersFor(r.subject)" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
            <p v-if="!teachersFor(r.subject).length" class="mt-1 text-[11px] text-text3">
              Нет преподавателей с предметом «{{ r.subject }}» — добавьте его во вкладке «Преподаватели».
            </p>
          </div>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showHours = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="hoursSaving || hoursLoading || !hoursRows.length" @click="saveHours">
            {{ hoursSaving ? 'Сохранение…' : 'Сохранить' }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- ── Импорт специальности/учебного плана ВСГУТУ ─────────────────────────────── -->
    <div v-if="showImport" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showImport = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="font-title text-lg font-bold text-text">Импорт с сайта ВСГУТУ · {{ importGroup }}</h3>
        <p class="mb-4 mt-1 text-xs text-text3">
          Подтягивает учебный план специальности и заносит в группу предметы+часы+ЗЕТ
          ИМЕННО текущего курса/семестра (считается от года поступления). Список
          предметов группы будет ЗАМЕНЁН — как при обновлении «Из расписания».
        </p>

        <template v-if="!importResult">
          <p v-if="importLoadingList" class="py-6 text-center text-sm text-text3">Загрузка специальностей…</p>
          <div v-else class="space-y-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Специальность</span>
              <select v-model="importForm.specialty_code"
                      class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
                <option value="">— выберите —</option>
                <option v-for="s in importSpecialties" :key="s.code" :value="s.code">{{ s.code }} — {{ s.name }}</option>
              </select>
              <p v-if="!importSpecialties.length" class="mt-1 text-xs text-red">
                Список специальностей недоступен (сайт ВСГУТУ не ответил) — попробуйте позже.
              </p>
            </label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Год поступления</span>
              <select v-model.number="importForm.enrollment_year" :disabled="!importForm.specialty_code || importLoadingYears"
                      class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-50">
                <option value="">{{ importLoadingYears ? '— загрузка… —' : '— выберите —' }}</option>
                <option v-for="y in importYears" :key="y" :value="y">{{ y }}</option>
              </select>
              <p v-if="importForm.specialty_code && !importLoadingYears && !importYears.length"
                 class="mt-1 text-xs text-red">
                Для этой специальности на сайте нет опубликованных планов.
              </p>
            </label>
            <p v-if="importError" class="text-sm text-red">{{ importError }}</p>
          </div>
        </template>

        <!-- Сводка после успешного импорта — что именно подтянулось. -->
        <div v-else class="space-y-2 text-sm">
          <p class="text-text">Курс <b>{{ importResult.course }}</b>, семестр с начала обучения
            <b>{{ importResult.semester }}</b> (текущий период: {{ importResult.term.year }} ·
            {{ importResult.term.semester === 1 ? 'осенний' : 'весенний' }}).</p>
          <p class="text-text2">Предметов с часами этого семестра: <b>{{ importResult.imported.length }}</b></p>
          <div v-if="importResult.imported.length" class="flex flex-wrap gap-1.5">
            <Badge v-for="s in importResult.imported" :key="s" variant="green">{{ s }}</Badge>
          </div>
          <template v-if="importResult.unmapped.length">
            <p class="pt-1 text-text2">Добавлены без часов (не удалось определить семестр в плане —
              задайте часы вручную кнопкой 🕐):</p>
            <div class="flex flex-wrap gap-1.5">
              <Badge v-for="s in importResult.unmapped" :key="s" variant="muted">{{ s }}</Badge>
            </div>
          </template>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showImport = false">{{ importResult ? 'Закрыть' : 'Отмена' }}</AppButton>
          <AppButton v-if="!importResult" variant="green" size="sm"
                    :disabled="importSaving || importLoadingList || !importSpecialties.length" @click="runImport">
            {{ importSaving ? 'Импорт…' : 'Импортировать' }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- ── Импорт группы по категории расписания ──────────────────────────────────── -->
    <div v-if="showScheduleImport" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showScheduleImport = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="font-title text-lg font-bold text-text">Импорт группы по категории</h3>
        <p class="mb-4 mt-1 text-xs text-text3">
          Заводит группу как каталожную запись, связанную с расписанием портала —
          БЕЗ предметов/часов/журнала (для колледжа их даёт «Добавить группу» /
          «Обновить группы»).
        </p>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Категория</span>
            <select v-model="scheduleImportCategory"
                    class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
              <option v-for="c in nonCollegeCategories" :key="c.key" :value="c.key">{{ c.label }}</option>
            </select>
          </label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Группа (с портала)</span>
            <select v-model="scheduleImportGroupName" :disabled="scheduleImportLoadingGroups || !scheduleImportGroups.length"
                    class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-50">
              <option value="">{{ scheduleImportLoadingGroups ? '— загрузка… —' : '— выберите —' }}</option>
              <option v-for="n in scheduleImportGroups" :key="n" :value="n">{{ n }}</option>
            </select>
            <p v-if="!scheduleImportLoadingGroups && scheduleImportCategory && !scheduleImportGroups.length"
               class="mt-1 text-xs text-red">
              Нет данных с портала для этой категории (сайт недоступен либо снимок ещё не собран).
            </p>
          </label>
          <p v-if="scheduleImportError" class="text-sm text-red">{{ scheduleImportError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showScheduleImport = false">Отмена</AppButton>
          <AppButton variant="green" size="sm"
                    :disabled="scheduleImportSaving || !scheduleImportGroupName" @click="runScheduleImport">
            {{ scheduleImportSaving ? 'Импорт…' : 'Импортировать' }}
          </AppButton>
        </div>
      </div>
    </div>

    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ editing ? 'Изменить группу' : 'Добавить группу' }}</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Название</span>
            <input v-model="form.name" :disabled="!!editing" list="grp-parsed" placeholder="Выберите или введите"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
            <datalist id="grp-parsed"><option v-for="n in parsedGroups" :key="n" :value="n" /></datalist>
          </label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Категория</span>
            <select v-model="form.category"
                    class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
              <option v-for="c in categories" :key="c.key" :value="c.key">{{ c.label }}</option>
            </select>
          </label>
          <div>
            <span class="mb-1 block text-tiny uppercase text-text3">Предметы группы</span>
            <div class="max-h-48 overflow-y-auto rounded-sm border border-border2 bg-card2 p-2">
              <label v-for="s in allSubjects" :key="s" class="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm text-text hover:bg-bg2">
                <input type="checkbox" :checked="form.subjects.includes(s)" @change="toggleSubject(s)" />
                {{ s }}
              </label>
              <p v-if="!allSubjects.length" class="px-1 py-2 text-xs text-text3">Сначала заведите предметы во вкладке «Предметы».</p>
            </div>
          </div>
          <p v-if="formError" class="text-sm text-red">{{ formError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showForm = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="save">{{ saving ? 'Сохранение…' : (editing ? 'Сохранить' : 'Добавить') }}</AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
