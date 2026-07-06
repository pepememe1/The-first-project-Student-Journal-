<script setup>
// StudentDashboard — «Главная» студента (порт ui/dashboards.py _build_dash):
// заголовок, «Умный совет» (много советов, ротация), маскот-эмоция ПО ФАКТАМ
// (грустный при среднем <3 / многих пропусках; спокойный 3–4; радостный ≥4),
// карточки статистики, проактивные инсайты и список предметов.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { RotateCw } from '@lucide/vue'
import { studentApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import Mascot from '@/components/Mascot.vue'
import InsightCards from '@/components/InsightCards.vue'
import { dashboardEmote } from '@/config/mascot'

const loading = ref(true)
const data = ref(null)
const insights = ref([])

async function load() {
  loading.value = true
  try { data.value = (await studentApi.overview()).data } catch { data.value = null } finally { loading.value = false }
  try { insights.value = (await studentApi.insights()).data.cards || [] } catch { insights.value = [] }
}
onMounted(load)

const avg = computed(() => Number(data.value?.average ?? 0))
const debts = computed(() => Number(data.value?.debts ?? 0))
const attendance = computed(() => Number(data.value?.attendance ?? 100))

// Поза Вектора — строго по фактам (не по клику). Низкая посещаемость трактуется как
// «много пропусков» для эмоции.
const sprite = computed(() =>
  dashboardEmote({ average: avg.value, absences: attendance.value < 80 ? 20 : 0 }))

// «Умный совет» — КОНКРЕТНО про ситуацию студента (что делать), а не про приложение.
// Плохо → «посещай пары, отвечай, делай домашку, закрой долги»; хорошо → короткая
// похвала. Советы ротируются, если их несколько.
const TIPS = computed(() => {
  if (!data.value) return ['Загрузка…']
  const t = []
  const low = attendance.value < 85
  const weak = avg.value > 0 && avg.value < 3
  const mid = avg.value >= 3 && avg.value < 4
  if (debts.value) t.push(`У тебя ${debts.value} незакрытых долг(ов) — договорись с преподавателем о пересдаче и не откладывай.`)
  if (low) t.push(`Посещаемость ${attendance.value}% — старайся не пропускать занятия, пропуски напрямую тянут оценку вниз.`)
  if (weak) {
    t.push('Средний ниже 3 — активнее отвечай на парах и разбирай сложные темы, не копи пробелы.')
    t.push('Делай домашние задания регулярно — это самый быстрый способ поднять оценки.')
  } else if (mid) {
    t.push('Средний в норме, но до отличного немного не хватает — чуть активнее на парах и с домашкой.')
  }
  if (!t.length) t.push(avg.value >= 4 ? 'У тебя всё хорошо — так держать! 👍' : 'Начни набирать оценки на практиках — и средний пойдёт вверх.')
  return t
})
const tipI = ref(0)
const tip = computed(() => TIPS.value[tipI.value % TIPS.value.length])
function nextTip() { tipI.value++ }
let tipTimer = null
onMounted(() => { tipTimer = setInterval(() => { if (data.value) tipI.value++ }, 9000) })
onBeforeUnmount(() => clearInterval(tipTimer))
</script>

<template>
  <div class="space-y-5">
    <div>
      <h2 class="font-title text-2xl font-extrabold text-text">{{ data?.name || '—' }}</h2>
      <p class="mt-0.5 text-sm text-text3">Группа: {{ data?.group || '—' }}</p>
    </div>
    <div class="h-px bg-border" />

    <!-- Умный совет: много советов, ротация; кнопка — следующий -->
    <div class="rounded-lg border p-4" style="background: var(--gb-accent-glow); border-color: color-mix(in srgb, var(--gb-accent) 20%, transparent);">
      <div class="mb-1 flex items-center justify-between">
        <p class="text-sm font-bold text-accent">💡 Умный совет</p>
        <button class="grid size-7 place-items-center rounded-md border border-accent/25 text-accent hover:bg-accent-glow"
                title="Следующий совет" @click="nextTip">
          <RotateCw class="size-3.5" />
        </button>
      </div>
      <p class="text-sm text-text">{{ tip }}</p>
    </div>

    <InsightCards :cards="insights" />

    <div class="grid gap-6 lg:grid-cols-[minmax(180px,260px)_1fr]">
      <div class="flex items-start justify-center">
        <Mascot :sprite="sprite" class="h-72 w-56" />
      </div>

      <div class="space-y-5">
        <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <StatCard label="Предметов" :value="data?.subjects_count ?? '—'" accent />
          <StatCard label="Средний балл" :value="data?.average || '—'" />
          <StatCard label="Посещаемость" :value="data ? data.attendance + '%' : '—'" />
          <StatCard label="Оценок" :value="data?.grades_total ?? '—'" />
        </div>

        <div>
          <h3 class="mb-3 font-title text-lg font-bold text-text">Мои предметы</h3>
          <p v-if="loading" class="text-sm text-text3">Загрузка…</p>
          <p v-else-if="!data?.subjects?.length" class="text-sm text-text3">Предметов пока нет.</p>
          <ul v-else class="space-y-2">
            <li v-for="s in data.subjects" :key="s.subject"
                class="flex items-center justify-between rounded-md border border-border bg-card px-4 py-3 shadow-card">
              <span class="text-sm font-semibold text-text">{{ s.subject }}</span>
              <span class="text-xs text-text3">{{ s.grades }} оценок</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>
