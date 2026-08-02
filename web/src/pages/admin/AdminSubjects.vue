<script setup>
// AdminSubjects — каталог предметов + CRUD (Phase B). Добавить/удалить. Пишется в
// таблицу subjects (id=subj:name) → синкается в десктоп (там список аддитивный, поэтому
// удаление убирает предмет из веба, но на десктопе может остаться до ручной чистки).
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()
const rows = ref([])
const loading = ref(true)
const showForm = ref(false)
const name = ref('')
const saving = ref(false)
const formError = ref('')

async function reload() {
  loading.value = true
  try { rows.value = (await adminApi.subjects()).data.subjects || [] } catch { rows.value = [] } finally { loading.value = false }
}
onMounted(reload)

function openCreate() { name.value = ''; formError.value = ''; showForm.value = true }
async function save() {
  if (!name.value.trim()) { formError.value = locale.t('adminSubjects.enterName', 'Введите название'); return }
  saving.value = true; formError.value = ''
  try { await adminApi.createSubject(name.value.trim()); showForm.value = false; await reload() }
  catch (e) { formError.value = e?.response?.data?.detail || locale.t('adminSubjects.saveFailed', 'Не удалось сохранить') }
  finally { saving.value = false }
}
async function del(s) {
  if (!(await confirm({ title: locale.t('adminSubjects.confirmDelete', { name: s.name }), okText: locale.t('common.delete'), danger: true }))) return
  try { await adminApi.deleteSubject(s.name); await reload() }
  catch (e) { toast.error(e?.response?.data?.detail || locale.t('adminSubjects.deleteFailed', 'Не удалось удалить')) }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-end">
      <AppButton variant="green" size="sm" @click="openCreate">{{ locale.t('adminSubjects.addAction', '+ Добавить') }}</AppButton>
    </div>

    <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border2 bg-bg2 text-left text-tiny uppercase tracking-wide text-text2">
            <th class="px-4 py-2.5 font-semibold">{{ locale.t('adminSubjects.subject', 'Предмет') }}</th>
            <th class="px-4 py-2.5 text-right font-semibold">{{ locale.t('adminSubjects.actions', 'Действия') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="2" class="px-4 py-6 text-center text-text3">{{ locale.t('common.loading') }}</td></tr>
          <tr v-else-if="!rows.length"><td colspan="2" class="px-4 py-6 text-center text-text3">{{ locale.t('adminSubjects.noSubjects', 'Предметов нет') }}</td></tr>
          <tr v-for="(s, i) in rows" :key="i" class="border-b border-border last:border-0 hover:bg-bg2/60">
            <td class="px-4 py-2.5 font-medium text-text">{{ s.name }}</td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right">
              <button class="text-text3 hover:text-red" :title="locale.t('common.delete')" @click="del(s)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showForm = false">
      <div class="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-card">
        <h3 class="mb-4 font-title text-lg font-bold text-text">{{ locale.t('adminSubjects.addSubject', 'Добавить предмет') }}</h3>
        <input v-model="name" :placeholder="locale.t('adminSubjects.subjectNamePlaceholder', 'Название предмета')" @keyup.enter="save"
               class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
        <p v-if="formError" class="mt-2 text-sm text-red">{{ formError }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="showForm = false">{{ locale.t('common.cancel') }}</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving" @click="save">{{ saving ? locale.t('adminSubjects.saving', 'Сохранение…') : locale.t('adminSubjects.addAction2', 'Добавить') }}</AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
