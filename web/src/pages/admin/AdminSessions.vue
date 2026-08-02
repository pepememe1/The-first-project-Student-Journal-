<script setup>
// AdminSessions — «Сессии и доступ» (порт admin_dashboard "sessions"): активные токены
// + отзыв. По умолчанию показываем ТОЛЬКО access-сессии (рабочие, живут 5ч). refresh
// живёт 30д (тихое продление) — по построению долгий, показываем по переключателю,
// чтобы «~720ч» не выглядело ошибкой. Отзыв гасит и парный токен (access↔refresh).
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { roleLabel } from '@/config/roles'

const locale = useLocaleStore()
const all = ref([])
const loading = ref(true)
const showRefresh = ref(false)

const rows = computed(() => showRefresh.value ? all.value : all.value.filter((s) => s.kind === 'access'))

async function load() {
  loading.value = true
  try { all.value = (await adminApi.sessions(true)).data.sessions || [] } catch { all.value = [] } finally { loading.value = false }
}
onMounted(load)

async function revoke(jti) {
  try { await adminApi.revoke({ jti }); await load() } catch { /* */ }
}

// Человекочитаемая длительность: минуты / часы / дни.
function dur(sec) {
  if (sec <= 0) return '—'
  if (sec < 3600) return locale.t('adminSessions.minutesShort', { n: Math.round(sec / 60) })
  if (sec < 86400) return locale.t('adminSessions.hoursShort', { n: Math.round(sec / 3600) })
  return locale.t('adminSessions.daysShort', { n: Math.round(sec / 86400) })
}

const columns = computed(() => [
  { key: 'login', label: locale.t('adminSessions.user', 'Пользователь') },
  { key: 'role', label: locale.t('adminSessions.role', 'Роль') },
  { key: 'kind', label: locale.t('adminSessions.kind', 'Тип') },
  { key: 'ip', label: 'IP' },
  { key: 'expires_in_sec', label: locale.t('adminSessions.remaining', 'Осталось'), align: 'right' },
  { key: 'actions', label: '', align: 'right' },
])
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-text3">
        {{ locale.t('adminSessions.workingSessions', { n: all.filter((s) => s.kind === 'access').length }) }}
        <span class="text-text2">{{ locale.t('adminSessions.durationsHint', 'access — 5 ч, refresh — 30 дн (тихое продление).') }}</span>
      </p>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-text3">
          <input type="checkbox" v-model="showRefresh" class="size-4 accent-[var(--gb-accent)]" />
          {{ locale.t('adminSessions.showRefresh', 'Показывать refresh') }}
        </label>
        <AppButton variant="ghost" size="sm" @click="load">{{ locale.t('common.refresh') }}</AppButton>
      </div>
    </div>
    <DataTable :columns="columns" :rows="rows" :loading="loading" :empty="locale.t('adminSessions.noSessions', 'Активных сессий нет')">
      <template #cell-login="{ row }"><span class="font-medium text-text">{{ row.login }}</span></template>
      <template #cell-role="{ row }"><Badge variant="muted">{{ roleLabel(row.role) }}</Badge></template>
      <template #cell-kind="{ row }"><Badge :variant="row.kind === 'refresh' ? 'blue' : 'green'">{{ row.kind === 'refresh' ? locale.t('adminSessions.kindRefresh', 'refresh') : locale.t('adminSessions.kindAccess', 'access') }}</Badge></template>
      <template #cell-expires_in_sec="{ row }">{{ dur(row.expires_in_sec) }}</template>
      <template #cell-actions="{ row }">
        <AppButton variant="red" size="sm" @click="revoke(row.jti)">{{ locale.t('adminSessions.revoke', 'Отозвать') }}</AppButton>
      </template>
    </DataTable>
  </div>
</template>
