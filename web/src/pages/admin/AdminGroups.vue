<script setup>
// AdminGroups — группы + CRUD (Phase B). Создание/правка (список предметов группы) /
// удаление; кнопка «🏫 Из расписания» добавляет спарсенные группы колледжа (как в
// десктопе). Пишется в те же таблицы (id=grp:name) → синкается в десктоп.
import { ref, onMounted } from 'vue'
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
const form = ref({ name: '', subjects: [] })
const saving = ref(false)
const formError = ref('')
const importing = ref(false)

function openCreate() { editing.value = null; form.value = { name: '', subjects: [] }; formError.value = ''; showForm.value = true }
function openEdit(g) { editing.value = g.name; form.value = { name: g.name, subjects: [...(g.subjects || [])] }; formError.value = ''; showForm.value = true }
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
    if (editing.value) await adminApi.updateGroup(editing.value, { subjects: f.subjects })
    else await adminApi.createGroup({ name: f.name.trim(), subjects: f.subjects })
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
      <AppButton variant="green" size="sm" @click="openCreate">+ Добавить</AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">Группа</th>
            <th class="px-4 py-2.5 text-right font-semibold">Студентов</th>
            <th class="px-4 py-2.5 font-semibold">Предметы</th>
            <th class="px-4 py-2.5 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="4" class="px-4 py-6 text-center text-text3">Загрузка…</td></tr>
          <tr v-else-if="!rows.length"><td colspan="4" class="px-4 py-6 text-center text-text3">Групп нет</td></tr>
          <tr v-for="(g, i) in rows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="px-4 py-2.5 font-semibold text-text">{{ g.name }}</td>
            <td class="px-4 py-2.5 text-right text-text2">{{ g.students }}</td>
            <td class="px-4 py-2.5">
              <div class="flex flex-wrap gap-1.5">
                <Badge v-for="s in (g.subjects || []).slice(0, 4)" :key="s" variant="muted">{{ s }}</Badge>
                <span v-if="(g.subjects?.length || 0) > 4" class="text-xs text-text3">+{{ g.subjects.length - 4 }}</span>
                <span v-if="!g.subjects?.length" class="text-text3">—</span>
              </div>
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
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

    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ editing ? 'Изменить группу' : 'Добавить группу' }}</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Название</span>
            <input v-model="form.name" :disabled="!!editing" list="grp-parsed" placeholder="Выберите или введите"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-60" />
            <datalist id="grp-parsed"><option v-for="n in parsedGroups" :key="n" :value="n" /></datalist>
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
