<script setup>
// AdminStudents — список студентов + CRUD (Phase B). Добавление/правка/удаление с
// выбором группы из списка (синкнутые группы БД + спарсенные из расписания). id
// студента на сервере — stud:login (как в синке десктопа); удаление мягкое (надгробие),
// поэтому изменения доезжают до десктопа обычным pull.
import { ref, computed, onMounted } from 'vue'
import { adminApi, scheduleApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

const all = ref([])
const loading = ref(true)
const q = ref('')
const groupChoices = ref([])
const showPass = ref(false)     // показать вводимый пароль в модалке (по глазку)

// Пароль в БД хранится ХЕШЕМ и не показывается — глазок открывает то, что админ ВВОДИТ.
function fmtDT(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? '—' : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function reload() {
  loading.value = true
  try { all.value = (await adminApi.students()).data.students || [] } catch { all.value = [] } finally { loading.value = false }
}

onMounted(async () => {
  await reload()
  // Список групп для выбора: синкнутые (БД) + спарсенные из расписания, без дублей —
  // как _all_group_choices в десктопе.
  try {
    const dbG = (await adminApi.groups()).data.groups?.map((g) => g.name) || []
    let parsed = []
    try { parsed = (await scheduleApi.groups()).data.groups || [] } catch { /* оффлайн — ок */ }
    groupChoices.value = [...new Set([...dbG, ...parsed].filter(Boolean))]
  } catch { /* */ }
})

const rows = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return all.value
  return all.value.filter((r) => `${r.surname} ${r.name} ${r.group} ${r.login}`.toLowerCase().includes(s))
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
  if (!f.surname.trim() || !f.name.trim()) { formError.value = 'Введите фамилию и имя'; return }
  if (!f.login.trim()) { formError.value = 'Введите логин'; return }
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
    formError.value = e?.response?.data?.detail || 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function del(r) {
  if (!confirm(`Удалить студента ${r.surname} ${r.name}?`)) return
  try { await adminApi.deleteStudent(r.login); await reload() }
  catch (e) { alert(e?.response?.data?.detail || 'Не удалось удалить') }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <input v-model="q" placeholder="Поиск по ФИО, группе или логину…"
             class="h-10 w-full max-w-sm rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent focus:bg-card" />
      <AppButton variant="green" size="sm" @click="openCreate">+ Добавить</AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">ФИО</th>
            <th class="px-4 py-2.5 font-semibold">Группа</th>
            <th class="px-4 py-2.5 font-semibold">Логин</th>
            <th class="px-4 py-2.5 font-semibold">Телефон</th>
            <th class="px-4 py-2.5 font-semibold">Посл. вход</th>
            <th class="px-4 py-2.5 font-semibold">IP</th>
            <th class="px-4 py-2.5 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="7" class="px-4 py-6 text-center text-text3">Загрузка…</td></tr>
          <tr v-else-if="!rows.length"><td colspan="7" class="px-4 py-6 text-center text-text3">Студентов нет</td></tr>
          <tr v-for="(r, i) in rows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="whitespace-nowrap px-4 py-2.5 font-medium text-text">{{ r.surname }} {{ r.name }}</td>
            <td class="px-4 py-2.5 text-text2">{{ r.group || '—' }}</td>
            <td class="px-4 py-2.5 text-text2">{{ r.login || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text2">{{ r.phone || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3" :title="r.device ? 'устройство: ' + r.device : ''">{{ fmtDT(r.last_login) }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-text3">{{ r.ip || '—' }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="mr-3 text-text3 hover:text-accent" title="Изменить" @click="openEdit(r)">✎</button>
              <button class="text-text3 hover:text-red" title="Удалить" @click="del(r)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Модалка создания/правки -->
    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ editing ? 'Изменить студента' : 'Добавить студента' }}</h3>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Фамилия</span>
              <input v-model="form.surname" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Имя</span>
              <input v-model="form.name" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Отчество <span class="text-text3 normal-case">(необязательно)</span></span>
            <input v-model="form.patronymic" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Логин</span>
            <input v-model="form.login" :disabled="!!editing"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-60" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Группа</span>
            <input v-model="form.group" list="admin-group-list" placeholder="Выберите или введите группу"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
            <datalist id="admin-group-list"><option v-for="g in groupChoices" :key="g" :value="g" /></datalist>
          </label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ editing ? 'Новый пароль (пусто — не менять)' : 'Пароль' }}</span>
            <div class="relative">
              <input v-model="form.password" :type="showPass ? 'text' : 'password'" placeholder="••••••••"
                     class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 pr-10 text-sm text-text outline-none focus:border-accent" />
              <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-text3 hover:text-accent" @click="showPass = !showPass">
                {{ showPass ? '🙈' : '👁' }}
              </button>
            </div>
            <span class="mt-1 block text-tiny text-text3">Пароль в базе хранится хешем — показать можно только новый вводимый.</span></label>
          <p v-if="formError" class="text-sm text-red">{{ formError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showForm = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="save">
            {{ saving ? 'Сохранение…' : (editing ? 'Сохранить' : 'Добавить') }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
