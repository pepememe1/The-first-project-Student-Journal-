<script setup>
// AdminMessenger — модерация мессенджера (только админ): очередь жалоб (тикетов) со
// снимком текста + обработка, и просмотр любой беседы (каждый просмотр пишется в аудит на
// сервере). См. docs/MESSENGER-PLAN.md §10.
import { ref, onMounted } from 'vue'
import { messengerModApi } from '@/api/endpoints'

const REASON_RU = {
  spam: 'Спам', harassment: 'Оскорбления', threats: 'Угрозы', fraud: 'Мошенничество',
  illegal: 'Запрещённый контент', flood: 'Флуд', other: 'Другое',
}
const statusFilter = ref('open')
const reports = ref([])
const loading = ref(false)
const viewer = ref({ open: false, conv: '', messages: [], loading: false })

async function load() {
  loading.value = true
  try { reports.value = (await messengerModApi.reports(statusFilter.value)).data.reports || [] }
  catch { reports.value = [] }
  finally { loading.value = false }
}
onMounted(load)

async function resolve(r, status) {
  const note = status === 'dismissed' ? '' : (window.prompt('Заметка модерации (необязательно):') || '')
  try { await messengerModApi.resolve(r.id, status, note); await load() } catch { /* noop */ }
}

async function openConversation(convId) {
  viewer.value = { open: true, conv: convId, messages: [], loading: true }
  try { viewer.value.messages = (await messengerModApi.conversationMessages(convId)).data.messages || [] }
  catch { viewer.value.messages = [] }
  finally { viewer.value.loading = false }
}
function fmt(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}
</script>

<template>
  <div>
    <div class="mb-4 flex items-center gap-2">
      <label class="text-sm text-text2">Статус:</label>
      <select v-model="statusFilter" @change="load"
              class="rounded-md border border-border2 bg-card2 px-3 py-1.5 text-sm text-text outline-none focus:border-accent">
        <option value="open">Новые</option>
        <option value="in_review">В работе</option>
        <option value="resolved">Решённые</option>
        <option value="dismissed">Отклонённые</option>
        <option value="">Все</option>
      </select>
      <button type="button" @click="load" class="rounded-md border border-border2 px-3 py-1.5 text-sm text-text2 hover:bg-bg2">Обновить</button>
    </div>

    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>
    <p v-else-if="!reports.length" class="rounded-lg border border-dashed border-border2 bg-card2/50 px-6 py-12 text-center text-sm text-text3">
      Жалоб нет.
    </p>

    <div class="space-y-3">
      <div v-for="r in reports" :key="r.id" class="rounded-lg border border-border bg-card p-4 shadow-card">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <span class="rounded-full bg-red/15 px-2.5 py-0.5 text-xs font-semibold text-red">{{ REASON_RU[r.reason_code] || r.reason_code }}</span>
          <span class="text-xs text-text3">{{ fmt(r.created_at) }}</span>
          <span class="ml-auto text-xs text-text3">#{{ r.id }} · {{ r.status }}</span>
        </div>
        <p class="rounded-md border border-border bg-bg2 px-3 py-2 text-sm text-text">«{{ r.message_snapshot }}»</p>
        <p v-if="r.description" class="mt-2 text-sm text-text2">Комментарий: {{ r.description }}</p>
        <p class="mt-2 text-xs text-text3">
          Жалоба от <b class="text-text2">{{ r.reporter_name }}</b> на <b class="text-text2">{{ r.reported_name }}</b>
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button type="button" @click="openConversation(r.conversation_id)"
                  class="rounded-md border border-border2 px-3 py-1.5 text-xs text-text2 hover:bg-bg2">Открыть переписку</button>
          <button v-if="r.status === 'open'" type="button" @click="resolve(r, 'in_review')"
                  class="rounded-md border border-border2 px-3 py-1.5 text-xs text-text2 hover:bg-bg2">В работу</button>
          <button type="button" @click="resolve(r, 'resolved')"
                  class="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent2">Решено</button>
          <button type="button" @click="resolve(r, 'dismissed')"
                  class="rounded-md border border-border2 px-3 py-1.5 text-xs text-text2 hover:bg-bg2">Отклонить</button>
        </div>
      </div>
    </div>

    <!-- Просмотр переписки (аудируется на сервере) -->
    <div v-if="viewer.open" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="viewer.open = false">
      <div class="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-border2 bg-card shadow-card">
        <div class="flex items-center justify-between border-b border-border p-4">
          <h3 class="font-title text-base font-bold text-text">Переписка</h3>
          <button type="button" @click="viewer.open = false" class="text-text3 hover:text-text">✕</button>
        </div>
        <div class="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-4">
          <p v-if="viewer.loading" class="text-sm text-text3">Загрузка…</p>
          <div v-for="mm in viewer.messages" :key="mm.id" class="text-sm">
            <span class="text-text3">[{{ fmt(mm.created_at) }}]</span>
            <span class="text-text">{{ mm.deleted ? '(удалено)' : mm.body }}</span>
          </div>
          <p v-if="!viewer.loading && !viewer.messages.length" class="text-sm text-text3">Пусто.</p>
        </div>
      </div>
    </div>
  </div>
</template>
