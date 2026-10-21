<script setup>
// ActivityPortfolio — ЖУРНАЛ активностей беседы: список проведённых с номерами и
// датами, и по клику — результаты всех участников с баллами.
//
// ⚠️ Раньше журналов было ДВА, и открывались они из разных мест: старая таблица
// `ActivityJournal.vue` (строка = одно число) висела на втулке колеса, а этот разбор по
// участникам — только ссылкой внутри уже запущенной активности. То есть человек, нажавший
// «Журнал», попадал ровно в ту версию, где не видно ни участников, ни результатов, и
// считал, что их не существует. Старая таблица удалена, осталась одна дверь и один
// журнал; её выгрузка CSV перенесена сюда, чтобы ничего не потерять.
//
// 🔒 Открыт только тому, кто вправе вести активности. Настоящая проверка на сервере:
// `/results` отдаёт чужие результаты лишь ведущему, участнику — только его строку.
import { ref, onMounted } from 'vue'
import { X, ChevronDown, ChevronRight } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'
import { formatCollege } from '@/utils/collegeTime'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const items = ref([])
const loading = ref(true)
const openId = ref('')
const results = ref({})          // id активности -> строки участников
const hostOf = ref({})           // id активности -> ведущий ли я (разбор вопросов — ему)
const analysis = ref({})         // id активности -> разбор вопросов викторины
const busy = ref('')

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
function fmt(iso) {
  const d = new Date(iso || '')
  return isNaN(d) ? '—' : formatCollege(d, BCP47[locale.active] || 'ru-RU',
    { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(async () => {
  try {
    const { data } = await activitiesApi.journal(props.conversationId)
    items.value = data.items || []
  } catch { items.value = [] } finally { loading.value = false }
})

/**
 * Выгрузка таблицей — прямо из уже загруженных строк: второй серверный формат ради одной
 * кнопки заводить незачем. Перенесена из удалённого ActivityJournal.vue.
 *
 * ⚠️ BOM в начале файла обязателен: без него Excel открывает кириллицу кракозябрами, и
 * выгрузка выглядит сломанной, хотя данные целы.
 */
function exportCsv() {
  const head = ['date', 'kind', 'title', 'host', 'participants']
  const rows = items.value.map((r) => [r.started_at, r.kind, r.title, r.host_name, r.participants])
  const csv = [head, ...rows]
    .map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'activities.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function toggle(a) {
  if (openId.value === a.id) { openId.value = ''; return }
  openId.value = a.id
  if (results.value[a.id]) return
  busy.value = a.id
  try {
    const { data } = await activitiesApi.results(a.id)
    results.value = { ...results.value, [a.id]: data.results || [] }
    hostOf.value = { ...hostOf.value, [a.id]: !!data.is_host }
  } catch {
    results.value = { ...results.value, [a.id]: [] }
  } finally { busy.value = '' }
}
// Разбор вопросов (исследование 20.10.2026) — считает сервер (`estimators.item_analysis`),
// здесь только показ. Отрицательная различающая сила почти всегда значит неверный ключ.
async function loadAnalysis(a) {
  try {
    const { data } = await activitiesApi.itemAnalysis(a.id)
    analysis.value = { ...analysis.value, [a.id]: data }
  } catch {
    analysis.value = { ...analysis.value, [a.id]: { items: [], failed: true } }
  }
}

const VERDICT_CLASS = { key: 'text-red font-semibold', weak: 'text-orange', trivial: 'text-text3', ok: 'text-accent', unknown: 'text-text3' }
</script>

<template>
  <div class="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border2 px-4 py-3">
        <h3 class="min-w-0 flex-1 truncate font-title text-base font-bold text-text">
          {{ locale.t('activity.portfolio.title', 'Журнал активностей') }}
        </h3>
        <button v-if="items.length" type="button" @click="exportCsv"
                class="shrink-0 rounded-lg border border-border2 px-2 py-1 text-xs text-text2 hover:border-accent hover:text-accent">
          {{ locale.t('activity.journal.export', 'Выгрузить') }}
        </button>
        <button :aria-label="locale.t('common.close', 'Закрыть')" type="button" @click="emit('close')" class="shrink-0 text-text3 hover:text-text">
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
              <div v-if="a.kind === 'quiz' && hostOf[a.id] && (results[a.id] || []).length" class="mt-2">
                <button v-if="!analysis[a.id]" type="button" @click="loadAnalysis(a)"
                        class="rounded-lg border border-border2 px-2 py-1 text-xs text-text2 hover:border-accent hover:text-accent">
                  {{ locale.t('activity.analysis.open') }}
                </button>
                <div v-else class="flex flex-col gap-1 text-xs">
                  <p v-if="!analysis[a.id].enough" class="text-text3">
                    {{ locale.t('activity.analysis.few', { n: analysis[a.id].participants || 0 }) }}
                  </p>
                  <p v-if="analysis[a.id].alpha !== null && analysis[a.id].alpha !== undefined" class="text-text3">
                    {{ locale.t('activity.analysis.alpha', { alpha: analysis[a.id].alpha }) }}
                  </p>
                  <div v-for="q in analysis[a.id].items" :key="q.question_id"
                       class="flex min-w-0 items-center gap-2 rounded-lg bg-card px-2.5 py-1.5">
                    <span class="w-6 shrink-0 text-center font-bold text-text3">{{ q.order_no + 1 }}</span>
                    <span class="min-w-0 flex-1 truncate text-text">{{ q.text }}</span>
                    <span class="shrink-0 tabular-nums text-text3"
                          :title="q.facility_low === null || q.facility_low === undefined ? '' : locale.t('activity.analysis.range', { low: Math.round(q.facility_low * 100), high: Math.round(q.facility_high * 100) })">{{ q.facility === null ? '—' : Math.round(q.facility * 100) + '%' }}<template v-if="q.facility_low !== null && q.facility_low !== undefined"> ({{ Math.round(q.facility_low * 100) }}–{{ Math.round(q.facility_high * 100) }})</template></span>
                    <span class="shrink-0 tabular-nums text-text3">r {{ q.discrimination === null ? '—' : q.discrimination }}</span>
                    <span class="shrink-0" :class="VERDICT_CLASS[q.verdict]">{{ locale.t(`activity.analysis.${q.verdict}`) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
