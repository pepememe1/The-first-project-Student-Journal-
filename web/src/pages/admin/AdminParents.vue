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
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const auth = useAuthStore()
const toast = useToast()
const { confirm } = useConfirm()

const parents = ref([])
const links = ref([])
const students = ref([])
const loading = ref(true)

const isAdmin = computed(() => auth.role === 'admin')

const STATUS = computed(() => ({
  pending: { label: locale.t('adminParents.statusPending', 'ожидает подтверждения'), variant: 'muted' },
  active: { label: locale.t('adminParents.statusActive', 'доступ открыт'), variant: 'green' },
  revoked: { label: locale.t('adminParents.statusRevoked', 'отозван'), variant: 'red' },
}))

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
    formError.value = locale.t('adminParents.needLoginSurnamePassword', 'Нужны логин, фамилия и пароль')
    return
  }
  saving.value = true; formError.value = ''
  try {
    await staffParentApi.create({ ...f, login: f.login.trim() })
    showCreate.value = false
    await load()
    toast.success(locale.t('adminParents.parentAdded', 'Родитель добавлен'))
  } catch (e) { formError.value = e?.response?.data?.detail || locale.t('adminParents.createFailed', 'Не удалось создать') }
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
    linkError.value = locale.t('adminParents.selectParentStudent', 'Выберите родителя и студента')
    return
  }
  linking.value = true; linkError.value = ''
  try {
    await staffParentApi.link(linkForm.value.parent_id, linkForm.value.student_id)
    showLink.value = false
    await load()
    toast.info(locale.t('adminParents.linkCreatedInfo', 'Заявка создана. Доступ откроется, когда студент подтвердит её у себя.'))
  } catch (e) { linkError.value = e?.response?.data?.detail || locale.t('adminParents.linkFailed', 'Не удалось привязать') }
  finally { linking.value = false }
}
async function unlink(l) {
  const ok = await confirm({
    title: locale.t('adminParents.unlinkConfirmTitle', 'Снять доступ?'),
    message: locale.t('adminParents.unlinkConfirmMessage', { parent: l.parent.full_name, student: l.student.full_name }),
    okText: locale.t('adminParents.unlinkConfirmOk', 'Снять'), danger: true,
  })
  if (!ok) return
  try { await staffParentApi.unlink(l.id); await load() }
  catch (e) { toast.error(e?.response?.data?.detail || locale.t('adminParents.unlinkFailed', 'Не удалось снять')) }
}

// ── Правка/удаление аккаунта родителя (зеркало десктопного _open_parent) ─────────
const showEdit = ref(false)
const editTarget = ref(null)
const editForm = ref({ surname: '', name: '', password: '' })
const savingEdit = ref(false)
const editError = ref('')

function openEdit(p) {
  editTarget.value = p
  const full = (p.full_name || '').trim()
  const [surname0, ...rest0] = full.split(' ')
  editForm.value = { surname: surname0 || '', name: rest0.join(' '), password: '' }
  editError.value = ''
  showEdit.value = true
}
async function saveEdit() {
  const f = editForm.value
  savingEdit.value = true; editError.value = ''
  try {
    await staffParentApi.update(editTarget.value.id, {
      surname: f.surname.trim(), name: f.name.trim(), password: f.password,
    })
    showEdit.value = false
    await load()
    toast.success(locale.t('adminParents.saved', 'Сохранено'))
  } catch (e) { editError.value = e?.response?.data?.detail || locale.t('adminParents.saveFailed', 'Не удалось сохранить') }
  finally { savingEdit.value = false }
}
async function deleteEdit() {
  const p = editTarget.value
  const ok = await confirm({
    title: locale.t('adminParents.deleteConfirmTitle', 'Удалить аккаунт родителя?'),
    message: locale.t('adminParents.deleteConfirmMessage', { name: p.full_name || p.login }),
    okText: locale.t('common.delete'), danger: true,
  })
  if (!ok) return
  try {
    await staffParentApi.remove(p.id)
    showEdit.value = false
    await load()
  } catch (e) { toast.error(e?.response?.data?.detail || locale.t('adminParents.deleteFailed', 'Не удалось удалить')) }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <p class="mr-auto max-w-2xl text-sm text-text3">
        {{ locale.t('adminParents.linkExplainerBefore', 'Привязка создаёт') }}
        <b class="text-text2">{{ locale.t('adminParents.linkExplainerRequest', 'заявку') }}</b>{{ locale.t('adminParents.linkExplainerAfter', ', а не доступ: журнал откроется родителю только после того, как студент подтвердит её в своём кабинете.') }}
      </p>
      <AppButton v-if="isAdmin" variant="ghost" size="sm" @click="openCreate">{{ locale.t('adminParents.addParentAction', '+ Родитель') }}</AppButton>
      <AppButton variant="green" size="sm" :disabled="!parents.length" @click="openLink">
        {{ locale.t('adminParents.linkToStudentAction', 'Привязать к студенту') }}
      </AppButton>
    </div>

    <!-- ── Аккаунты родителей (правка/удаление — только админ) ────────────────────── -->
    <div v-if="isAdmin" class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colAccounts', 'Аккаунты родителей') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colLogin', 'Логин') }}</th>
            <th class="px-4 py-2.5 text-right font-semibold">{{ locale.t('adminParents.colActions', 'Действия') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!loading && !parents.length"><td colspan="3" class="px-4 py-6 text-center text-text3">{{ locale.t('adminParents.noParents', 'Родителей пока нет') }}</td></tr>
          <tr v-for="p in parents" :key="p.id" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="px-4 py-2.5 text-text">{{ p.full_name || '—' }}</td>
            <td class="px-4 py-2.5 text-text2">{{ p.login }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="text-text3 hover:text-accent" :title="locale.t('adminParents.edit', 'Изменить')" @click="openEdit(p)">✎</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colParent', 'Родитель') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colStudent', 'Студент') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colGroup', 'Группа') }}</th>
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminParents.colStatus', 'Статус') }}</th>
            <th class="px-4 py-2.5 text-right font-semibold">{{ locale.t('adminParents.colActions', 'Действия') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="px-4 py-6 text-center text-text3">{{ locale.t('common.loading') }}</td></tr>
          <tr v-else-if="!links.length"><td colspan="5" class="px-4 py-6 text-center text-text3">{{ locale.t('adminParents.noLinks', 'Привязок нет') }}</td></tr>
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
                      :title="locale.t('adminParents.revokeAccess', 'Снять доступ')" @click="unlink(l)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── Новый родитель ──────────────────────────────────────────────────────── -->
    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showCreate = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ locale.t('adminParents.newParentTitle', 'Новый родитель') }}</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.colLogin', 'Логин') }}</span>
            <input v-model="form.login" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.surname', 'Фамилия') }}</span>
              <input v-model="form.surname" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.firstName', 'Имя') }}</span>
              <input v-model="form.name" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.passwordLabel', 'Пароль') }}</span>
            <input v-model="form.password" type="text"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <p v-if="formError" class="text-sm text-red">{{ formError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showCreate = false">{{ locale.t('common.cancel') }}</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="createParent">
            {{ saving ? locale.t('adminParents.saving', 'Сохранение…') : locale.t('adminParents.addAction2', 'Добавить') }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- ── Привязка ────────────────────────────────────────────────────────────── -->
    <div v-if="showLink" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showLink = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ locale.t('adminParents.linkModalTitle', 'Привязать родителя к студенту') }}</h3>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.colParent', 'Родитель') }}</span>
            <select v-model="linkForm.parent_id" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="p in parents" :key="p.id" :value="p.id">{{ p.full_name || p.login }}</option>
            </select></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.colStudent', 'Студент') }}</span>
            <select v-model="linkForm.student_id" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent">
              <option v-for="s in students" :key="s.id" :value="s.id">
                {{ s.surname }} {{ s.name }} · {{ s.group }}
              </option>
            </select>
            <span v-if="!students.length" class="mt-1 block text-xs text-text3">
              {{ locale.t('adminParents.studentsAdminOnlyHint', 'Список студентов доступен администратору.') }}
            </span>
          </label>
          <p v-if="linkError" class="text-sm text-red">{{ linkError }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showLink = false">{{ locale.t('common.cancel') }}</AppButton>
          <AppButton variant="green" size="sm" :disabled="linking" @click="createLink">
            {{ linking ? locale.t('adminParents.linking', 'Привязка…') : locale.t('adminParents.linkAction2', 'Привязать') }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- ── Правка родителя ─────────────────────────────────────────────────────── -->
    <div v-if="showEdit" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showEdit = false">
      <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-1 font-title text-lg font-bold text-text">{{ editTarget?.full_name || locale.t('adminParents.parentFallback', 'Родитель') }}</h3>
        <p class="mb-4 text-xs text-text3">{{ locale.t('adminParents.loginPrefix', 'Логин:') }} {{ editTarget?.login }}</p>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.surname', 'Фамилия') }}</span>
              <input v-model="editForm.surname" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
            <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.nameAndPatronymic', 'Имя Отчество') }}</span>
              <input v-model="editForm.name" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          </div>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('adminParents.newPassword', 'Новый пароль') }}</span>
            <input v-model="editForm.password" type="text" :placeholder="locale.t('adminParents.leaveEmptyHint', 'Оставьте пустым, чтобы не менять')"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" /></label>
          <p v-if="editError" class="text-sm text-red">{{ editError }}</p>
        </div>
        <div class="mt-5 flex items-center justify-between gap-2">
          <AppButton variant="red" size="sm" @click="deleteEdit">{{ locale.t('common.delete') }}</AppButton>
          <div class="flex gap-2">
            <AppButton variant="ghost" size="sm" @click="showEdit = false">{{ locale.t('common.cancel') }}</AppButton>
            <AppButton variant="green" size="sm" :disabled="savingEdit" @click="saveEdit">
              {{ savingEdit ? locale.t('adminParents.saving', 'Сохранение…') : locale.t('common.save') }}
            </AppButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
