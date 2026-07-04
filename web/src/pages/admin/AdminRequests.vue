<script setup>
// AdminRequests — «Запросы на подключение» (порт admin_dashboard "requests"):
// новые устройства (в т.ч. браузеры персонала) просят доступ; админ одобряет
// (сервер выдаёт 6-значный код, его диктуют пользователю) или отклоняет.
import { ref, onMounted, onUnmounted } from 'vue'
import { connectApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import AppButton from '@/components/ui/AppButton.vue'

const rows = ref([])
const loading = ref(true)
const codes = ref({}) // device_id -> выданный код
let timer = null

async function load() {
  try { rows.value = (await connectApi.list()).data.requests || [] } catch { rows.value = [] } finally { loading.value = false }
}
onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => timer && clearInterval(timer))

async function approve(dev) {
  try { codes.value = { ...codes.value, [dev]: (await connectApi.approve(dev)).data.code }; await load() } catch { /* */ }
}
async function reject(dev) { try { await connectApi.reject(dev); await load() } catch { /* */ } }

const STATUS = { pending: ['muted', 'Ожидает'], code_issued: ['green', 'Код выдан'] }
const columns = [
  { key: 'hostname', label: 'Устройство' },
  { key: 'ip', label: 'IP' },
  { key: 'status', label: 'Статус' },
  { key: 'actions', label: '', align: 'right' },
]
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-text3">Одобрение новых устройств. Код диктуется пользователю — он вводит его на своём устройстве.</p>
    <DataTable :columns="columns" :rows="rows" :loading="loading" empty="Запросов на подключение нет">
      <template #cell-hostname="{ row }"><span class="font-medium text-text">{{ row.hostname || 'Неизвестное устройство' }}</span></template>
      <template #cell-status="{ row }"><Badge :variant="(STATUS[row.status] || ['muted', row.status])[0]">{{ (STATUS[row.status] || ['', row.status])[1] }}</Badge></template>
      <template #cell-actions="{ row }">
        <div class="flex items-center justify-end gap-2">
          <span v-if="codes[row.device_id]" class="rounded-sm bg-accent-glow px-2.5 py-1 font-title text-base font-bold tracking-widest text-accent">{{ codes[row.device_id] }}</span>
          <AppButton v-else variant="green" size="sm" @click="approve(row.device_id)">Одобрить</AppButton>
          <AppButton variant="red" size="sm" @click="reject(row.device_id)">Отклонить</AppButton>
        </div>
      </template>
    </DataTable>
  </div>
</template>
