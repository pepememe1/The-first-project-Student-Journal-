<script setup>
// AdminTeachers — преподаватели + CRUD (Phase B). Создание/правка (ФИО, логин, нагрузка
// = список предметов, пароль) / удаление. id на сервере = teach:login (как в синке
// десктопа); удаление мягкое → изменения доезжают до десктопа обычным pull.
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'

const all = ref([])
const loading = ref(true)
const allSubjects = ref([])
const q = ref('')
const showPass = ref(false)
function fmtDT(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? '—' : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function reload() {
  loading.value = true
  try { all.value = (await adminApi.teachers()).data.teachers || [] } catch { all.value = [] } finally { loading.value = false }
}
onMounted(async () => {
  await reload()
  try { allSubjects.value = (await adminApi.subjects()).data.subjects?.map((s) => s.name) || [] } catch { /* */ }
})

const rows = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return all.value
  return all.value.filter((r) => `${r.name} ${r.login}`.toLowerCase().includes(s))
})

const showForm = ref(false)
const editing = ref(null)
const form = ref({ full_name: '', login: '', subjects: [], password: '' })
const saving = ref(false)
const formError = ref('')

function openCreate() { editing.value = null; form.value = { full_name: '', login: '', subjects: [], password: '' }; formError.value = ''; showForm.value = true }
function openEdit(t) { editing.value = t.login; form.value = { full_name: t.name, login: t.login, subjects: [...(t.subjects || [])], password: '' }; formError.value = ''; showForm.value = true }
function toggleSubject(s) {
  const i = form.value.subjects.indexOf(s)
  if (i >= 0) form.value.subjects.splice(i, 1)
  else form.value.subjects.push(s)
}
async function save() {
  const f = form.value
  if (!f.full_name.trim()) { formError.value = 'Введите ФИО'; return }
  if (!f.login.trim()) { formError.value = 'Введите логин'; return }
  saving.value = true; formError.value = ''
  try {
    if (editing.value) await adminApi.updateTeacher(editing.value, { full_name: f.full_name, subjects: f.subjects, password: f.password })
    else await adminApi.createTeacher({ full_name: f.full_name, login: f.login, subjects: f.subjects, password: f.password })
    showForm.value = false; await reload()
  } catch (e) { formError.value = e?.response?.data?.detail || 'Не удалось сохранить' }
  finally { saving.value = false }
}
async function del(t) {
  if (!confirm(`Удалить преподавателя ${t.name}?`)) return
  try { await adminApi.deleteTeacher(t.login); await reload() }
  catch (e) { alert(e?.response?.data?.detail || 'Не удалось удалить') }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <input v-model="q" placeholder="Поиск по ФИО или логину…"
             class="h-10 w-full max-w-sm rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent focus:bg-card" />
      <AppButton variant="green" size="sm" @click="openCreate">+ Добавить</AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">ФИО</th>
            <th class="px-4 py-2.5 font-semibold">Логин</th>
            <th class="px-4 py-2.5 font-semibold">Предметы</th>
            <th class="px-4 py-2.5 font-semibold">Посл. вход</th>
            <th class="px-4 py-2.5 font-semibold">IP</th>
            <th class="px-4 py-2.5 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" class="px-4 py-6 text-center text-text3">Загрузка…</td></tr>
          <tr v-else-if="!rows.length"><td colspan="6" class="px-4 py-6 text-center text-text3">Преподавателей нет</td></tr>
          <tr v-for="(t, i) in rows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="whitespace-nowrap px-4 py-2.5 font-medium text-text">{{ t.name || '—' }}</td>
            <td class="px-4 py-2.5 text-text2">{{ t.login || '—' }}</td>
            <td class="px-4 py-2.5">
              <div class="flex flex-wrap gap-1.5">
                <Badge v-for="s in (t.subjects || []).slice(0, 4)" :key="s" variant="muted">{{ s }}</Badge>
                <span v-if="(t.subjects?.length || 0) > 4" class="text-xs text-text3">+{{ t.subjects.length - 4 }}</span>
                <span v-if="!t.subjects?.length" class="text-text3">—</span>
              </div>
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3" :title="t.device ? 'устройство: ' + t.device : ''">{{ fmtDT(t.last_login) }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3">{{ t.ip || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="mr-3 text-text3 hover:text-accent" title="Изменить" @click="openEdit(t)">✎</button>
              <button class="text-text3 hover:text-red" title="Удалить" @click="del(t)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ editing ? 'Изменить преподавателя' : 'Добавить преподавателя' }}</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">ФИО</span>
            <input v-model="form.full_name" placeholder="Иванов Иван Иванович"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Логин</span>
            <input v-model="form.login" :disabled="!!editing"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-60" /></label>
          <div>
            <span class="mb-1 block text-tiny uppercase text-text3">Нагрузка (предметы)</span>
            <div class="max-h-48 overflow-y-auto rounded-sm border border-border2 bg-card2 p-2">
              <label v-for="s in allSubjects" :key="s" class="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm text-text hover:bg-bg2">
                <input type="checkbox" :checked="form.subjects.includes(s)" @change="toggleSubject(s)" />
                {{ s }}
              </label>
              <p v-if="!allSubjects.length" class="px-1 py-2 text-xs text-text3">Сначала заведите предметы во вкладке «Предметы».</p>
            </div>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ editing ? 'Новый пароль (пусто — не менять)' : 'Пароль' }}</span>
            <div class="relative">
              <input v-model="form.password" :type="showPass ? 'text' : 'password'" placeholder="••••••••"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 pr-10 text-sm text-text outline-none focus:border-accent" />
              <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-text3 hover:text-accent" @click="showPass = !showPass">
                {{ showPass ? '🙈' : '👁' }}
              </button>
            </div></label>
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
