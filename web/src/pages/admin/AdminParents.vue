<script setup>
// AdminParents — родители и их привязка к студентам.
//
// Одна страница на две роли: администратор видит все группы, куратор — только свои
// (скоуп режет СЕРВЕР, здесь просто показываем то, что он отдал). Заведение родителя —
// действие администратора, поэтому кнопка «+ Родитель» видна только ему.
//
// Важное для понимания интерфейса: привязка НЕ даёт доступа. Она создаёт заявку, и пока
// студент не подтвердит её у себя, статус «ожидает». Об этом написано прямо на странице —
// иначе сотрудник решит, что система сломана, и пойдёт заводить вторую связь.
import { ref, computed, onMounted } from 'vue'
import { staffParentApi, adminApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'

const auth = useAuthStore()
const toast = useToast()
const { confirm } = useConfirm()

const parents = ref([])
const links = ref([])
const students = ref([])
const loading = ref(true)

const isAdmin = computed(() => auth.role === 'admin')

const STATUS = {
  pending: { label: 'ожидает подтверждения', variant: 'muted' },
  active: { label: 'доступ открыт', variant: 'green' },
  revoked: { label: 'отозван', variant: 'red' },
}

async function load() {
  loading.value = true
  try {
    parents.value = (await staffParentApi.parents()).data.parents || []
    links.value = (await staffParentApi.links()).data.links || []
  } catch { parents.value = []; links.value = [] }
  // Список студентов есть только у админа; куратор выбирает из своих связей и группы.
  if (isAdmin.value) {
    try { students.value = (await adminApi.students()).data.students || [] } catch { /* */ }
  }
  loading.value = false
}
onMounted(load)

// ── Заведение родителя ──────────────────────────────────────────────────────────
const showCreate = ref(false)
const form = ref({ login: '', surname: '', name: '', password: '' })
const saving = ref(false)
const formError = ref('')

function openCreate() {
  form.value = { login: '', surname: '', name: '', password: '' }
  formError.value = ''
  showCreate.value = true
}
async function createParent() {
  const f = form.value
  if (!f.login.trim() || !f.surname.trim() || !f.password) {
    formError.value = 'Нужны логин, фамилия и пароль'
    return
  }
  saving.value = true; formError.value = ''
  try {
    await staffParentApi.create({ ...f, login: f.login.trim() })
    showCreate.value = false
    await load()
    toast.success('Родитель добавлен')
  } catch (e) { formError.value = e?.response?.data?.detail || 'Не удалось создать' }
  finally { saving.value = false }
}

// ── Привязка ────────────────────────────────────────────────────────────────────
const showLink = ref(false)
const linkForm = ref({ parent_id: '', student_id: '' })
const linking = ref(false)
const linkError = ref('')

function openLink() {
  linkForm.value = { parent_id: parents.value[0]?.id || '', student_id: students.value[0]?.id || '' }
  linkError.value = ''
  showLink.value = true
}
async function createLink() {
  if (!linkForm.value.parent_id || !linkForm.value.student_id) {
    linkError.value = 'Выберите родителя и студента'
    return
  }
  linking.value = true; linkError.value = ''
  try {
    await staffParentApi.link(linkForm.value.parent_id, linkForm.value.student_id)
    showLink.value = false
    await load()
    toast.info('Заявка создана. Доступ откроется, когда студент подтвердит её у себя.')
  } catch (e) { linkError.value = e?.response?.data?.detail || 'Не удалось привязать' }
  finally { linking.value = false }
}
async function unlink(l) {
  const ok = await confirm({
    title: 'Снять доступ?',
    message: `${l.parent.full_name} перестанет видеть журнал студента ${l.student.full_name}.`,
    okText: 'Снять', danger: true,
  })
  if (!ok) return
  try { await staffParentApi.unlink(l.id); await load() }
  catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось снять') }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <p class="mr-auto max-w-2xl text-sm text-text3">
        Привязка создаёт <b class="text-text2">заявку</b>, а не доступ: журнал откроется
        родителю только после того, как студент подтвердит её в своём кабинете.
      </p>
      <AppButton v-if="isAdmin" variant="ghost" size="sm" @click="openCreate">+ Родитель</AppButton>
      <AppButton variant="green" size="sm" :disabled="!parents.length" @click="openLink">
        Привязать к студенту
      </AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">Родитель</th>
            <th class="px-4 py-2.5 font-semibold">Студент</th>
            <th class="px-4 py-2.5 font-semibold">Группа</th>
            <th class="px-4 py-2.5 font-semibold">Статус</th>
            <th class="px-4 py-2.5 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="px-4 py-6 text-center text-text3">Загрузка…</td></tr>
          <tr v-else-if="!links.length"><td colspan="5" class="px-4 py-6 text-center text-text3">Привязок нет</td></tr>
          <tr v-for="l in links" :key="l.id" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="px-4 py-2.5 text-text">{{ l.parent.full_name || l.parent.login }}</td>
            <td class="px-4 py-2.5 text-text">{{ l.student.full_name }}</td>
            <td class="px-4 py-2.5 text-text2">{{ l.student.group }}</td>
            <td class="px-4 py-2.5">
              <Badge :variant="STATUS[l.status]?.variant || 'muted'">
                {{ STATUS[l.status]?.label || l.status }}
              </Badge>
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button v-if="l.status !== 'revoked'" class="text-text3 hover:text-red"
                      title="Снять доступ" @click="unlink(l)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── Новый родитель ──────────────────────────────────────────────────────── -->
    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showCreate = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">Новый родитель</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Логин</span>
            <input v-model="form.login" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Фамилия</span>
              <input v-model="form.surname" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Имя</span>
              <input v-model="form.name" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Пароль</span>
            <input v-model="form.password" type="text"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <p v-if="formError" class="text-sm text-red">{{ formError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showCreate = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="createParent">
            {{ saving ? 'Сохранение…' : 'Добавить' }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- ── Привязка ────────────────────────────────────────────────────────────── -->
    <div v-if="showLink" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showLink = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">Привязать родителя к студенту</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Родитель</span>
            <select v-model="linkForm.parent_id" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="p in parents" :key="p.id" :value="p.id">{{ p.full_name || p.login }}</option>
            </select></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Студент</span>
            <select v-model="linkForm.student_id" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="s in students" :key="s.id" :value="s.id">
                {{ s.surname }} {{ s.name }} · {{ s.group }}
              </option>
            </select>
            <span v-if="!students.length" class="mt-1 block text-xs text-text3">
              Список студентов доступен администратору.
            </span>
          </label>
          <p v-if="linkError" class="text-sm text-red">{{ linkError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showLink = false">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="linking" @click="createLink">
            {{ linking ? 'Привязка…' : 'Привязать' }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
