<script setup>
// StudentDashboard — «Главная» студента (порт ui/dashboards.py _build_dash):
// заголовок (ФИО + группа), «Умный совет» с обновлением, маскот-эмоция по фактам,
// карточки Предметов/Средний/Посещаемость/Оценок и список «Мои предметы».
import { ref, computed, onMounted } from 'vue'
import { RotateCw } from '@lucide/vue'
import { studentApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import Mascot from '@/components/Mascot.vue'
import { dashboardEmote } from '@/config/mascot'

const loading = ref(true)
const data = ref(null)

async function load() {
  loading.value = true
  try { data.value = (await studentApi.overview()).data } catch { data.value = null } finally { loading.value = false }
}
onMounted(load)

const avg = computed(() => Number(data.value?.average ?? 0))
const debts = computed(() => Number(data.value?.debts ?? 0))

// Поза покоя — по фактам; клик по Вектору на пару секунд включает бодрую позу.
const POKES = ['happy-cheer', 'neutral-cheer', 'happy-congrats', 'surprise-cheer', 'think-cheer']
const poke = ref(null)
let pokeI = 0
let pokeTimer = null
const sprite = computed(() => poke.value || dashboardEmote({ average: avg.value, debts: debts.value }))
function pokeMascot() {
  pokeI = (pokeI + 1) % POKES.length
  poke.value = POKES[pokeI]
  clearTimeout(pokeTimer)
  pokeTimer = setTimeout(() => { poke.value = null }, 1800)
}

const tip = computed(() => {
  if (!data.value) return 'Загрузка совета…'
  const parts = []
  parts.push(avg.value ? `Твой средний балл — ${avg.value}.` : 'Оценок по практикам пока нет — самое время начать набирать.')
  parts.push(debts.value ? `Есть незакрытые долги (${debts.value}). Загляни к преподавателю и договорись о пересдаче.` : 'Долгов нет — так держать!')
  return parts.join(' ')
})
</script>

<template>
  <div class="space-y-5">
    <!-- Заголовок -->
    <div>
      <h2 class="font-title text-2xl font-extrabold text-text">{{ data?.name || '—' }}</h2>
      <p class="mt-0.5 text-sm text-text3">Группа: {{ data?.group || '—' }}</p>
    </div>
    <div class="h-px bg-border" />

    <!-- Умный совет -->
    <div class="rounded-lg border p-4" style="background: var(--gb-accent-glow); border-color: color-mix(in srgb, var(--gb-accent) 20%, transparent);">
      <div class="mb-1 flex items-center justify-between">
        <p class="text-sm font-bold text-accent">Умный совет</p>
        <button class="grid size-7 place-items-center rounded-md border border-accent/25 text-accent hover:bg-accent-glow"
                aria-label="Обновить" @click="load">
          <RotateCw class="size-3.5" />
        </button>
      </div>
      <p class="text-sm text-text">{{ tip }}</p>
    </div>

    <!-- Тело: маскот слева + контент справа -->
    <div class="grid gap-6 lg:grid-cols-[minmax(180px,260px)_1fr]">
      <div class="flex items-start justify-center">
        <Mascot :sprite="sprite" class="h-72 w-56 cursor-pointer" title="Кликни Вектора" @click="pokeMascot" />
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
