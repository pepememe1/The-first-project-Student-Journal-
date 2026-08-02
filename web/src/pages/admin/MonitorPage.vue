<script setup>
// MonitorPage — «Мониторинг» админа (порт admin_dashboard "mon"). Опирается на УЖЕ
// существующие серверные эндпоинты /admin/online и /admin/events (дельта-опрос).
import { ref, onMounted, onUnmounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useLocaleStore } from '@/stores/locale'
import { roleLabel } from '@/config/roles'

const locale = useLocaleStore()
const online = ref([])
const events = ref([])
const lastId = ref(0)
const error = ref('')
let timer = null

const LEVEL_VARIANT = { info: 'green', warn: 'blue', error: 'red' }

async function tick() {
  try {
    const [on, ev] = await Promise.all([adminApi.online(), adminApi.events(lastId.value)])
    online.value = on.data.online || []
    const rows = ev.data.events || ev.data.items || []
    if (rows.length) {
      events.value = [...rows.reverse(), ...events.value].slice(0, 200)
      lastId.value = Math.max(lastId.value, ...rows.map((r) => r.id || 0))
    }
    error.value = ''
  } catch (e) {
    error.value = e.response?.status === 404 ? '' : locale.t('monitorPage.noConnection', 'Нет связи с сервером мониторинга')
  }
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 5000)
})
onUnmounted(() => timer && clearInterval(timer))
</script>

<template>
  <div class="grid gap-6 lg:grid-cols-5">
    <Card class="lg:col-span-2" :title="locale.t('monitorPage.onlineNow', 'Сейчас онлайн')" :subtitle="locale.t('monitorPage.connectedCount', { n: online.length })">
      <EmptyState v-if="!online.length" :title="locale.t('monitorPage.nobodyOnline', 'Никого онлайн')" :message="locale.t('monitorPage.onlineHint', 'Активность за последние ~90 секунд.')" />
      <ul v-else class="divide-y divide-border">
        <li v-for="(u, i) in online" :key="i" class="flex items-center justify-between py-2.5">
          <div>
            <p class="text-sm font-medium text-text">{{ u.name || u.login }}</p>
            <p class="text-xs text-text3">{{ u.ip }}</p>
          </div>
          <Badge variant="muted">{{ roleLabel(u.role) }}</Badge>
        </li>
      </ul>
    </Card>

    <Card class="lg:col-span-3" :title="locale.t('monitorPage.eventLog', 'Журнал событий')" :subtitle="locale.t('monitorPage.eventLogSubtitle', 'Действия и ошибки сервера')">
      <p v-if="error" class="mb-3 text-sm text-red">{{ error }}</p>
      <EmptyState v-if="!events.length" :title="locale.t('monitorPage.noEvents', 'Событий пока нет')" :message="locale.t('monitorPage.noEventsHint', 'Здесь появятся входы, синхронизации и ошибки.')" />
      <ul v-else class="space-y-2">
        <li v-for="(e, i) in events" :key="i" class="flex items-start gap-3 text-sm">
          <Badge :variant="LEVEL_VARIANT[e.level] || 'muted'">{{ e.level }}</Badge>
          <div class="min-w-0">
            <p class="truncate text-text">{{ e.message }}</p>
            <p class="text-xs text-text3">{{ e.kind }} · {{ e.login || '—' }}</p>
          </div>
        </li>
      </ul>
    </Card>
  </div>
</template>
