<script setup>
// RoleManagerDialog — «Выдать роль» участнику беседы (§ролей). Роли — КАСТОМНЫЕ, свои для
// каждой группы/канала (ConversationRole), плюс три шаблона для быстрого старта (Студент/
// Староста/Преподаватель — просто дефолтные наборы прав, не хранятся, пока не сохранены).
// Права — фиксированный небольшой набор: kick/manage_roles/cmd_mute/cmd_clear.
import { ref, computed, onMounted } from 'vue'
import { X } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useMessengerStore } from '@/stores/messenger'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({ userId: { type: String, required: true }, userName: { type: String, default: '' } })
const emit = defineEmits(['close'])
const m = useMessengerStore()
const toast = useToast()
const locale = useLocaleStore()

const PERM_LABELS = computed(() => ({
  kick: locale.t('roleManager.perm.kick', 'Выгонять участников'),
  manage_roles: locale.t('roleManager.perm.manageRoles', 'Выдавать роли и создавать новые'),
  cmd_mute: locale.t('roleManager.perm.mute', 'Команда /mute'),
  cmd_clear: locale.t('roleManager.perm.clear', 'Команда /clear'),
}))

const loading = ref(true)
const roles = ref([])
const templates = ref([])
const allPermissions = ref([])
const busy = ref(false)

// Форма создания/правки роли — открывается либо «с нуля», либо от шаблона.
const editing = ref(null)          // существующая роль (объект) или null (новая)
const draftName = ref('')
const draftPerms = ref([])
const showEditor = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await messengerApi.roles(m.activeId)
    roles.value = data.roles || []
    templates.value = data.templates || []
    allPermissions.value = data.all_permissions || []
  } catch { /* noop */ }
  loading.value = false
}
onMounted(load)

function togglePerm(p) {
  const i = draftPerms.value.indexOf(p)
  if (i >= 0) draftPerms.value.splice(i, 1)
  else draftPerms.value.push(p)
}

function startNew() {
  editing.value = null
  draftName.value = ''
  draftPerms.value = []
  showEditor.value = true
}
function startFromTemplate(t) {
  editing.value = null
  draftName.value = t.name
  draftPerms.value = [...(t.permissions || [])]
  showEditor.value = true
}
function startEdit(r) {
  editing.value = r
  draftName.value = r.name
  draftPerms.value = [...(r.permissions || [])]
  showEditor.value = true
}

async function saveRole() {
  const name = draftName.value.trim()
  if (!name) return
  busy.value = true
  try {
    let role
    if (editing.value) {
      const { data } = await messengerApi.updateRole(m.activeId, editing.value.id,
        { name, permissions: draftPerms.value })
      role = data
    } else {
      const { data } = await messengerApi.createRole(m.activeId, name, draftPerms.value)
      role = data
    }
    await load()
    showEditor.value = false
    return role
  } catch (e) { toast.error(e?.response?.data?.detail || locale.t('roleManager.saveFailed', 'Не удалось сохранить роль')); return null }
  finally { busy.value = false }
}

async function saveAndAssign() {
  const role = await saveRole()
  if (role) await assign(role.id)
}

async function removeRole(r) {
  if (!window.confirm(locale.t('roleManager.confirmDelete', { name: r.name }))) return
  try { await messengerApi.deleteRole(m.activeId, r.id); await load() }
  catch (e) { toast.error(e?.response?.data?.detail || locale.t('roleManager.deleteFailed', 'Не удалось удалить роль')) }
}

async function assign(roleId) {
  const ok = await m.setMemberRole(props.userId, { customRoleId: roleId })
  if (ok) { toast.success(locale.t('roleManager.assigned', 'Роль назначена')); emit('close') }
  else toast.error(locale.t('roleManager.assignFailed', 'Не удалось назначить роль'))
}
async function resetToDefault() {
  const ok = await m.setMemberRole(props.userId, { role: 'member' })
  if (ok) { toast.success(locale.t('roleManager.reset', 'Роль сброшена')); emit('close') }
  else toast.error(locale.t('roleManager.resetFailed', 'Не удалось сбросить роль'))
}
</script>

<template>
  <div class="fixed inset-0 z-[60] grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-sm flex-col rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border p-4">
        <h3 class="font-title text-base font-bold text-text">{{ locale.t('roleManager.title', { name: userName || locale.t('roleManager.participant', 'участник') }) }}</h3>
        <button type="button" @click="emit('close')" class="text-text3 hover:text-text"><X class="size-5" /></button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>

        <template v-else-if="!showEditor">
          <button type="button" @click="resetToDefault"
                  class="mb-3 w-full rounded-lg border border-border2 px-3 py-2 text-left text-sm text-text2 hover:bg-bg2">
            {{ locale.t('roleManager.noCustomRole', 'Без кастомной роли (обычный участник)') }}
          </button>

          <p v-if="roles.length" class="mb-1 text-[11px] uppercase tracking-wide text-text3">{{ locale.t('roleManager.conversationRoles', 'Роли беседы') }}</p>
          <div v-for="r in roles" :key="r.id"
               class="mb-1.5 flex items-center gap-2 rounded-lg border border-border2 px-3 py-2">
            <button type="button" class="min-w-0 flex-1 text-left" @click="assign(r.id)">
              <div class="truncate text-sm font-medium text-text">{{ r.name }}</div>
              <div class="truncate text-[11px] text-text3">
                {{ (r.permissions || []).map(p => PERM_LABELS[p] || p).join(', ') || locale.t('roleManager.noSpecialPerms', 'без особых прав') }}
              </div>
            </button>
            <button type="button" :title="locale.t('roleManager.edit', 'Изменить')" class="shrink-0 text-text3 hover:text-accent" @click="startEdit(r)">✎</button>
            <button type="button" :title="locale.t('common.delete')" class="shrink-0 text-text3 hover:text-red" @click="removeRole(r)">✕</button>
          </div>

          <p class="mb-1 mt-3 text-[11px] uppercase tracking-wide text-text3">{{ locale.t('roleManager.templates', 'Шаблоны') }}</p>
          <button v-for="t in templates" :key="t.name" type="button" @click="startFromTemplate(t)"
                  class="mb-1.5 block w-full rounded-lg border border-dashed border-border2 px-3 py-2 text-left text-sm text-text2 hover:border-accent hover:text-text">
            {{ t.name }}
          </button>
          <button type="button" @click="startNew"
                  class="mt-1 w-full rounded-lg bg-accent-glow px-3 py-2 text-sm font-semibold text-accent hover:bg-accent/20">
            {{ locale.t('roleManager.customRole', '+ Своя роль') }}
          </button>
        </template>

        <template v-else>
          <label class="mb-3 block"><span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('roleManager.roleName', 'Название роли') }}</span>
            <input v-model="draftName" maxlength="60"
                   class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
          </label>
          <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">{{ locale.t('roleManager.permissions', 'Права') }}</p>
          <label v-for="p in allPermissions" :key="p"
                 class="mb-1 flex cursor-pointer items-center gap-2 rounded-md px-1 py-1.5 text-sm text-text hover:bg-bg2">
            <input type="checkbox" :checked="draftPerms.includes(p)" @change="togglePerm(p)" />
            {{ PERM_LABELS[p] || p }}
          </label>
          <div class="mt-4 flex justify-end gap-2">
            <button type="button" @click="showEditor = false" class="rounded-md px-3 py-1.5 text-sm text-text3 hover:bg-bg2">{{ locale.t('common.cancel') }}</button>
            <button type="button" :disabled="busy || !draftName.trim()" @click="saveRole"
                    class="rounded-md border border-border2 px-3 py-1.5 text-sm text-text2 hover:bg-bg2 disabled:opacity-50">
              {{ locale.t('roleManager.saveRole', 'Сохранить роль') }}
            </button>
            <button type="button" :disabled="busy || !draftName.trim()" @click="saveAndAssign"
                    class="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
              {{ locale.t('roleManager.saveAndAssign', 'Сохранить и назначить') }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
