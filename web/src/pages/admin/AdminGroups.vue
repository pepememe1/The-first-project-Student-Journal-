<script setup>
// AdminGroups — группы + CRUD (Phase B). Создание/правка (список предметов группы) /
// удаление; кнопка «🏫 Из расписания» добавляет спарсенные группы колледжа (как в
// десктопе). Пишется в те же таблицы (id=grp:name) → синкается в десктоп.
import { ref, onMounted } from 'vue'
import { adminApi, scheduleApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'

const rows = ref([])
const loading = ref(true)
const allSubjects = ref([])
const parsedGroups = ref([])

async function reload() {
  loading.value = true
  try { rows.value = (await adminApi.groups()).data.groups || [] } catch { rows.value = [] } finally { loading.value = false }
}
onMounted(async () => {
  await reload()
  try { allSubjects.value = (await adminApi.subjects()).data.subjects?.map((s) => s.name) || [] } catch { /* */ }
  try { parsedGroups.value = (await scheduleApi.groups()).data.groups || [] } catch { /* */ }
})

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
  if (!confirm(`Удалить группу ${g.name}?`)) return
  try { await adminApi.deleteGroup(g.name); await reload() }
  catch (e) { alert(e?.response?.data?.detail || 'Не удалось удалить') }
}
// «Из расписания» — привязывает к каждой группе предметы ИЗ её расписания (портал
// ВСГУТУ) и пополняет каталог. Снимок строится на сервере лениво (~минута): если он
// ещё готовится — просим нажать позже.
async function importParsed() {
  importing.value = true
  try {
    const r = (await adminApi.bindSubjects()).data
    if (!r.ok && r.building) {
      alert('Индекс расписания готовится на сервере (~минута). Нажми «🏫 Из расписания» ещё раз чуть позже.')
    } else {
      alert(`Готово: групп обновлено — ${r.bound}, предметов в каталоге — ${r.subjects}.` +
            (r.building ? '\n(индекс ещё дообновляется — можно повторить для полноты)' : ''))
      await reload()
      try { allSubjects.value = (await adminApi.subjects()).data.subjects?.map((s) => s.name) || [] } catch { /* */ }
    }
  } catch (e) { alert(e?.response?.data?.detail || 'Не удалось выполнить') }
  finally { importing.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-end gap-3">
      <AppButton variant="ghost" size="sm" :disabled="importing" @click="importParsed">
        {{ importing ? 'Привязка…' : '🏫 Привязать предметы' }}
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
              <button class="mr-3 text-text3 hover:text-accent" title="Изменить" @click="openEdit(g)">✎</button>
              <button class="text-text3 hover:text-red" title="Удалить" @click="del(g)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
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
