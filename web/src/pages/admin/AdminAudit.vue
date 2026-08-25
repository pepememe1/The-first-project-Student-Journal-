<script setup>
// AdminAudit — журнал значимых действий (входы, правки оценок и ПДн, регистрации).
//
// 🔥 ЖУРНАЛ ПИСАЛСЯ, А ПОСМОТРЕТЬ ЕГО БЫЛО НЕГДЕ. Ручка `GET /web/admin/audit`
// существовала и работала, а звать её было некому — классическое «обещание без
// вызывающего», найденное сверкой контракта (`tools/graph_api_bridge.py`).
//
// ⚠️ Для продукта с ПДн это не косметика. Аудит существует ровно для разбора «кто
// изменил оценку», «откуда был вход», «кто выдал доступ родителю» — и журнал, к
// которому нет доступа, эту задачу не решает вообще. Покупателю (152-ФЗ) мы обещаем
// именно возможность разобраться, а не факт записи в таблицу.
//
// ⚠️ ТОЛЬКО ЧТЕНИЕ. Записи неизменяемы по смыслу: журнал, который можно поправить,
// не журнал. Кнопок удаления и правки здесь нет и быть не должно.
import { ref, computed, onMounted } from 'vue'
import { RefreshCw, Search, ShieldAlert } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import Card from '@/components/ui/Card.vue'

const locale = useLocaleStore()
const rows = ref([])
const loading = ref(false)
const error = ref('')
const qAction = ref('')
const qActor = ref('')
const limit = ref(200)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await adminApi.audit({
      limit: limit.value,
      action: qAction.value.trim(),
      actor: qActor.value.trim(),
    })
    rows.value = data.events || []
  } catch (e) {
    error.value = e?.response?.data?.detail || locale.t('audit.failed', 'Не удалось загрузить журнал')
  } finally { loading.value = false }
}
onMounted(load)

// Уровень важности красим, но НЕ прячем ничего: фильтр по уровню в журнале аудита —
// способ не заметить именно то, ради чего в него заходят.
function levelClass(level) {
  if (level === 'error' || level === 'critical') return 'text-red'
  if (level === 'warn' || level === 'warning') return 'text-yellow-500'
  return 'text-text3'
}

// Время показываем в часовом поясе устройства: администратор сверяет журнал со своими
// часами, а не с UTC сервера.
function when(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d) ? ts : d.toLocaleString()
}

const empty = computed(() => !loading.value && !error.value && !rows.value.length)
</script>

<template>
  <div class="flex flex-col gap-3">
    <Card :title="locale.t('nav.audit', 'Журнал действий')"
          :subtitle="locale.t('audit.subtitle', 'Входы, правки оценок и персональных данных, выдача доступов. Только чтение.')">

      <div class="mb-3 flex flex-wrap items-end gap-2">
        <label class="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
          <Search :size="14" class="shrink-0 text-text3" />
          <input v-model="qActor" type="search" @keyup.enter="load"
                 class="w-full bg-transparent text-sm outline-none"
                 :placeholder="locale.t('audit.byActor', 'Кто (логин)')" />
        </label>
        <label class="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
          <Search :size="14" class="shrink-0 text-text3" />
          <input v-model="qAction" type="search" @keyup.enter="load"
                 class="w-full bg-transparent text-sm outline-none"
                 :placeholder="locale.t('audit.byAction', 'Действие (код)')" />
        </label>
        <select v-model.number="limit" @change="load"
                class="rounded-lg border border-border bg-card px-2 py-1.5 text-sm">
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="500">500</option>
          <option :value="1000">1000</option>
        </select>
        <button type="button" @click="load" :disabled="loading"
                class="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          <RefreshCw :size="14" :class="loading ? 'animate-spin' : ''" />
          {{ locale.t('common.refresh', 'Обновить') }}
        </button>
      </div>

      <p v-if="error" class="flex items-center gap-2 rounded-lg border border-red/40 px-3 py-2 text-sm text-red">
        <ShieldAlert :size="15" />{{ error }}
      </p>

      <p v-else-if="empty" class="py-10 text-center text-sm text-text3">
        {{ locale.t('audit.empty', 'Записей нет — либо журнал пуст, либо фильтр слишком узкий') }}
      </p>

      <!-- ⚠️ Своя прокрутка у таблицы: без неё длинные значения (IP, устройство,
           подробности) утаскивают в горизонтальную прокрутку всю страницу. -->
      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="text-text3">
            <tr class="border-b border-border">
              <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ locale.t('audit.when', 'Когда') }}</th>
              <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ locale.t('audit.who', 'Кто') }}</th>
              <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ locale.t('audit.action', 'Действие') }}</th>
              <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ locale.t('audit.target', 'Над чем') }}</th>
              <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ locale.t('audit.from', 'Откуда') }}</th>
              <th class="py-1.5 font-medium">{{ locale.t('audit.detail', 'Подробности') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id" class="border-b border-border-soft align-top">
              <td class="whitespace-nowrap py-1.5 pr-3 tabular-nums text-text3">{{ when(r.ts) }}</td>
              <td class="whitespace-nowrap py-1.5 pr-3">
                {{ r.actor || '—' }}
                <span v-if="r.role" class="text-text3">· {{ r.role }}</span>
              </td>
              <td class="whitespace-nowrap py-1.5 pr-3 font-medium" :class="levelClass(r.level)">{{ r.action }}</td>
              <td class="py-1.5 pr-3 text-text2">{{ r.target || '—' }}</td>
              <td class="whitespace-nowrap py-1.5 pr-3 text-text3">
                {{ r.ip || '—' }}
                <span v-if="r.device" class="opacity-70">· {{ r.device }}</span>
              </td>
              <td class="py-1.5 text-text2">{{ r.detail || '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
