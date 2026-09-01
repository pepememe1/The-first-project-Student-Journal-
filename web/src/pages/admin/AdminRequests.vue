<script setup>
// AdminRequests — «Запросы на подключение» (порт admin_dashboard "requests"):
// новые устройства (в т.ч. браузеры персонала) просят доступ; админ одобряет
// (сервер выдаёт 6-значный код, его диктуют пользователю) или отклоняет.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { connectApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const rows = ref([])
const loading = ref(true)
const codes = ref({}) // device_id -> выданный код
let timer = null
let onVisible = null

async function load() {
  try { rows.value = (await connectApi.list()).data.requests || [] } catch { rows.value = [] } finally { loading.value = false }
}
//⚠️ В СВЁРНУТОМ ПРИЛОЖЕНИИ И СКРЫТОЙ ВКЛАДКЕ НА СЕРВЕР НЕ ХОДИМ (01.09.2026).
//Опрос раз в 5 секунд — это двенадцать запросов в минуту с каждого открытого экрана, и в
//WebView Capacitor таймеры продолжают тикать после сворачивания приложения: телефон
//лежит в кармане, экран погашен, а мы будим радиомодуль. Человек, который экрана не
//видит, ничего от этих запросов не получает — а батарею они тратят. Вернувшись, он
//получит свежие данные первым же тиком.
onMounted(() => {
  load()
  timer = setInterval(() => { if (!document.hidden) load() }, 5000)
  onVisible = () => { if (!document.hidden) load() }
  document.addEventListener('visibilitychange', onVisible)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (onVisible) document.removeEventListener('visibilitychange', onVisible)
})

async function approve(dev) {
  try { codes.value = { ...codes.value, [dev]: (await connectApi.approve(dev)).data.code }; await load() } catch { /* */ }
}
async function reject(dev) { try { await connectApi.reject(dev); await load() } catch { /* */ } }

const STATUS = computed(() => ({
  pending: ['muted', locale.t('adminRequests.pending', 'Ожидает')],
  code_issued: ['green', locale.t('adminRequests.codeIssued', 'Код выдан')],
}))
const columns = computed(() => [
  { key: 'hostname', label: locale.t('adminRequests.device', 'Устройство') },
  { key: 'ip', label: 'IP' },
  { key: 'status', label: locale.t('adminRequests.status', 'Статус') },
  { key: 'actions', label: '', align: 'right' },
])
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-text3">{{ locale.t('adminRequests.hint', 'Одобрение новых устройств. Код диктуется пользователю — он вводит его на своём устройстве.') }}</p>
    <DataTable :columns="columns" :rows="rows" :loading="loading" :empty="locale.t('adminRequests.noRequests', 'Запросов на подключение нет')">
      <template #cell-hostname="{ row }"><span class="font-medium text-text">{{ row.hostname || locale.t('adminRequests.unknownDevice', 'Неизвестное устройство') }}</span></template>
      <template #cell-status="{ row }"><Badge :variant="(STATUS[row.status] || ['muted', row.status])[0]">{{ (STATUS[row.status] || ['', row.status])[1] }}</Badge></template>
      <template #cell-actions="{ row }">
        <div class="flex items-center justify-end gap-2">
          <span v-if="codes[row.device_id]" class="rounded-sm bg-accent-glow px-2.5 py-1 font-title text-base font-bold tracking-widest text-accent">{{ codes[row.device_id] }}</span>
          <AppButton v-else variant="green" size="sm" @click="approve(row.device_id)">{{ locale.t('adminRequests.approve', 'Одобрить') }}</AppButton>
          <AppButton variant="red" size="sm" @click="reject(row.device_id)">{{ locale.t('adminRequests.reject', 'Отклонить') }}</AppButton>
        </div>
      </template>
    </DataTable>
  </div>
</template>
