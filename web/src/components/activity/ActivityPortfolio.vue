<script setup>
// ActivityPortfolio — «Портфолио»: список проведённых активностей с номерами и датами,
// и по клику — результаты ВСЕХ участников.
//
// Отличие от журнала беседы: журнал отвечает «что тут было», портфолио — «как это
// прошло». Поэтому здесь список сразу разворачивается в таблицу участников, а не в
// строку с одним числом.
//
// 🔒 Открыт только тому, кто вправе вести активности. Настоящая проверка на сервере:
// `/results` отдаёт чужие результаты лишь ведущему, участнику — только его строку.
import { ref, onMounted } from 'vue'
import { X, ChevronDown, ChevronRight } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const items = ref([])
const loading = ref(true)
const openId = ref('')
const results = ref({})          // id активности -> строки участников
const busy = ref('')

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
function fmt(iso) {
  const d = new Date(iso || '')
  return isNaN(d) ? '—' : d.toLocaleString(BCP47[locale.active] || 'ru-RU',
    { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(async () => {
  try {
    const { data } = await activitiesApi.journal(props.conversationId)
    items.value = data.items || []
  } catch { items.value = [] } finally { loading.value = false }
})

async function toggle(a) {
  if (openId.value === a.id) { openId.value = ''; return }
  openId.value = a.id
  if (results.value[a.id]) return
  busy.value = a.id
  try {
    const { data } = await activitiesApi.results(a.id)
    results.value = { ...results.value, [a.id]: data.results || [] }
  } catch {
    results.value = { ...results.value, [a.id]: [] }
  } finally { busy.value = '' }
}
</script>

<template>
  <div class="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border2 px-4 py-3">
        <h3 class="font-title text-base font-bold text-text">
          {{ locale.t('activity.portfolio.title', 'Портфолио активностей') }}
        </h3>
        <button type="button" @click="emit('close')" class="text-text3 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-3">
        <p v-if="loading" class="py-8 text-center text-sm text-text3">
          {{ locale.t('common.loading', 'Загрузка…') }}
        </p>
        <p v-else-if="!items.length" class="py-8 text-center text-sm text-text3">
          {{ locale.t('activity.portfolio.empty', 'Активностей ещё не было') }}
        </p>

        <div v-else class="flex flex-col gap-2">
          <div v-for="(a, i) in items" :key="a.id" class="rounded-xl border border-border2 bg-bg2">
            <button type="button" @click="toggle(a)"
                    class="flex w-full min-w-0 items-center gap-2 px-3 py-2.5 text-left">
              <!-- Номер — по порядку проведения, как просил заказчик: «Активность №3»
                   узнаётся быстрее, чем дата с точностью до минуты. -->
              <span class="w-8 shrink-0 text-center text-sm font-bold text-text3">№{{ items.length - i }}</span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-text">
                  {{ a.title || locale.t(`activity.kind.${a.kind}`, a.kind) }}
                </span>
                <span class="block truncate text-tiny text-text3">
                  {{ locale.t(`activity.kind.${a.kind}`, a.kind) }} · {{ fmt(a.started_at) }}
                </span>
              </span>
              <span class="shrink-0 text-xs text-text3">
                {{ locale.t('activity.portfolio.people', { n: a.participants || 0 }) }}
              </span>
              <component :is="openId === a.id ? ChevronDown : ChevronRight"
                         class="size-4 shrink-0 text-text3" />
            </button>

            <div v-if="openId === a.id" class="border-t border-border2 px-3 py-2">
              <p v-if="busy === a.id" class="py-3 text-center text-xs text-text3">
                {{ locale.t('common.loading', 'Загрузка…') }}
              </p>
              <div v-else-if="(results[a.id] || []).length" class="flex flex-col gap-1">
                <div v-for="r in results[a.id]" :key="r.user_id"
                     class="flex min-w-0 items-center gap-2 rounded-lg bg-card px-2.5 py-1.5">
                  <span class="w-6 shrink-0 text-center text-xs font-bold"
                        :class="r.place <= 3 ? 'text-accent' : 'text-text3'">{{ r.place }}</span>
                  <span class="min-w-0 flex-1 truncate text-sm text-text">{{ r.name }}</span>
                  <span class="shrink-0 text-xs text-text3">{{ r.correct_count }}/{{ r.total_count }}</span>
                  <span class="shrink-0 text-sm font-semibold tabular-nums text-accent">{{ r.score }}</span>
                </div>
              </div>
              <p v-else class="py-3 text-center text-xs text-text3">
                {{ locale.t('activity.portfolio.noResults', 'Результатов нет — в этой активности их не считают') }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
