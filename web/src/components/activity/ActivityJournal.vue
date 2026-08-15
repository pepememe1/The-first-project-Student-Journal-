<script setup>
// ActivityJournal — журнал активностей беседы (PLAN-ACTIVITIES §9).
//
// Замена тому, чего сделать нельзя: автоматически выставить оценку в учебный журнал не
// получится — беседа не связана с учебной группой. Собственный журнал беседы честен: он
// про то, что происходило именно здесь.
//
// Кто что видит решает СЕРВЕР (`full`): ведущий и обладатели права `activities` — таблицу
// целиком, участник — только свои строки.
import { ref, onMounted, computed } from 'vue'
import { X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const items = ref([])
const full = ref(false)
const loading = ref(true)

onMounted(async () => {
  try {
    const { data } = await activitiesApi.journal(props.conversationId)
    items.value = data.items || []
    full.value = !!data.full
  } catch { items.value = [] } finally { loading.value = false }
})

const fmt = (iso) => {
  const d = new Date(iso)
  return Number.isFinite(d.getTime()) ? d.toLocaleString() : ''
}

function exportCsv() {
  // Выгрузка таблицей — прямо из уже загруженных строк: второй серверный формат ради
  // одной кнопки заводить незачем.
  const head = ['date', 'kind', 'title', 'host', 'participants', 'my_score']
  const rows = items.value.map((r) => [r.started_at, r.kind, r.title, r.host_name,
                                       r.participants, r.my_score ?? ''])
  const csv = [head, ...rows].map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'activities.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

const hasRows = computed(() => items.value.length > 0)
</script>

<template>
  <div class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-3"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border2 px-4 py-3">
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">
          {{ locale.t('activity.journal.title', 'Журнал активностей') }}
        </h2>
        <button v-if="hasRows" type="button" @click="exportCsv"
                class="shrink-0 rounded-lg border border-border2 px-2 py-1 text-xs text-text2 hover:border-accent hover:text-accent">
          {{ locale.t('activity.journal.export', 'Выгрузить') }}
        </button>
        <button type="button" @click="emit('close')" class="shrink-0 rounded-lg p-1 text-text3 hover:text-accent">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-4">
        <p v-if="loading" class="py-8 text-center text-sm text-text3">
          {{ locale.t('common.loading', 'Загрузка…') }}
        </p>
        <p v-else-if="!hasRows" class="py-8 text-center text-sm text-text3">
          {{ locale.t('activity.journal.empty', 'Активностей ещё не было') }}
        </p>
        <!-- Таблица в своей прокрутке: на телефоне она иначе распирает страницу целиком. -->
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[560px] text-left text-sm">
            <thead class="text-xs text-text3">
              <tr>
                <th class="pb-2 pr-3 font-medium">{{ locale.t('activity.journal.date', 'Дата') }}</th>
                <th class="pb-2 pr-3 font-medium">{{ locale.t('activity.journal.kind', 'Категория') }}</th>
                <th class="pb-2 pr-3 font-medium">{{ locale.t('activity.journal.name', 'Название') }}</th>
                <th class="pb-2 pr-3 font-medium">{{ locale.t('activity.journal.people', 'Участники') }}</th>
                <th class="pb-2 font-medium">{{ locale.t('activity.journal.result', 'Результат') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in items" :key="r.id" class="border-t border-border2">
                <td class="py-2 pr-3 text-text2">{{ fmt(r.started_at) }}</td>
                <td class="py-2 pr-3 text-text2">{{ locale.t(`activity.kind.${r.kind}`, r.kind) }}</td>
                <td class="max-w-[220px] truncate py-2 pr-3 text-text">{{ r.title || '—' }}</td>
                <td class="py-2 pr-3 text-text2">{{ r.participants }}</td>
                <td class="py-2 font-semibold text-accent">
                  <template v-if="full">{{ r.average ?? '—' }}</template>
                  <template v-else-if="r.my_score !== null">
                    {{ r.my_score }}<span v-if="r.my_total" class="font-normal text-text3"> · {{ r.my_correct }}/{{ r.my_total }}</span>
                  </template>
                  <template v-else>—</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
