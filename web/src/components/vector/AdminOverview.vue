<script setup>
// AdminOverview — сводка администратора на вкладке «ИИ Помощник» (3.6).
//
// Что здесь: состояние боевой машины (когда служба запущена, сколько работает, память,
// диск) и сколько в системе людей. Прямое пожелание: «у админа будет состояние сервера,
// когда запущен и перезапускался, сколько памяти свободно, сколько преподавателей
// сколько студентов».
//
// ⚠️ Цифры берутся из ТЕХ ЖЕ эндпоинтов, что и полноценный раздел «Сервер»
// (`/web/admin/server/metrics` и `/web/admin/overview`). Своего расчёта здесь нет
// СОЗНАТЕЛЬНО: две сводки, считающие «свободно памяти» по-разному, — это два разных
// ответа на один вопрос в зависимости от того, где посмотрел.
//
// «Запущен» — про САМО ПРИЛОЖЕНИЕ (process_uptime/started_at), а не про машину: VPS
// может работать месяцами, а службу перезапускали при последнем деплое, и именно это
// администратор и хочет увидеть после выкладки.
import { ref, computed, onMounted } from 'vue'
import { RotateCw } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const loading = ref(true)
const failed = ref(false)
const metrics = ref(null)
const counts = ref(null)
// «Онлайн сейчас» — тот же источник, что и вкладка «Сервер» → «Мониторинг»
// (events.online(), окно ONLINE_WINDOW_SEC): второго расчёта «кто в сети» не заводим.
const online = ref(null)

async function load() {
  loading.value = true
  failed.value = false
  //Три независимые сводки: сбой одной не должен прятать другие (состояние машины
  //полезно и без счётчиков, и наоборот).
  const [m, c, si] = await Promise.allSettled([
    adminApi.serverMetrics(), adminApi.overview(), adminApi.serverInfo(),
  ])
  metrics.value = m.status === 'fulfilled' ? m.value.data : null
  counts.value = c.status === 'fulfilled' ? c.value.data : null
  online.value = si.status === 'fulfilled' ? si.value.data.online_count : null
  failed.value = !metrics.value && !counts.value
  loading.value = false
}
onMounted(load)

function mb(bytes) { return Math.round((Number(bytes) || 0) / 1048576) }
function gb(bytes) { return ((Number(bytes) || 0) / 1073741824).toFixed(1) }

// Длительность словами: «3 д 4 ч» / «2 ч 15 мин» / «8 мин». Секунды показываем только
// в первую минуту после старта — иначе это шум, который всё равно уже устарел.
function duration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d} ${locale.t('adminOverview.unitDay', 'д')} ${h} ${locale.t('adminOverview.unitHour', 'ч')}`
  if (h) return `${h} ${locale.t('adminOverview.unitHour', 'ч')} ${m} ${locale.t('adminOverview.unitMin', 'мин')}`
  if (m) return `${m} ${locale.t('adminOverview.unitMin', 'мин')}`
  return `${s} ${locale.t('adminOverview.unitSec', 'с')}`
}

const mem = computed(() => metrics.value?.memory || null)
const disk = computed(() => metrics.value?.disk || null)
// Доля ЗАНЯТОГО — она и красится. Свободное место человек считает сам от полного, а
// тревожит именно заполнение.
function usedPct(used, total) {
  const t = Number(total) || 0
  return t ? Math.min(100, Math.round((Number(used) || 0) / t * 100)) : 0
}
// Пороги: до 75 % спокойно, до 90 % внимание, дальше красное. Те же три ступени, что
// у остальных статусных цветов продукта — своего набора не заводим.
function loadStatus(pct) {
  if (pct >= 90) return { text: 'text-red', bg: 'bg-red' }
  if (pct >= 75) return { text: 'text-yellow', bg: 'bg-yellow' }
  return { text: 'text-accent', bg: 'bg-accent' }
}
</script>

<template>
  <section class="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card shadow-card">
    <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
      <h3 class="font-title text-sm font-bold text-text">
        {{ locale.t('adminOverview.title', 'Состояние сервера') }}
      </h3>
      <button type="button" @click="load" :disabled="loading"
              class="grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-accent disabled:opacity-50"
              :title="locale.t('common.refresh', 'Обновить')"
              :aria-label="locale.t('common.refresh', 'Обновить')">
        <RotateCw class="size-3.5" />
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
      <p v-else-if="failed" class="text-sm text-text3">
        {{ locale.t('adminOverview.failed', 'Не удалось получить состояние сервера.') }}
      </p>

      <div v-else class="flex flex-col gap-4">
        <!-- Онлайн сейчас — тот же признак «база живая», но мгновенный, без похода
             в раздел «Сервер». -->
        <div v-if="online != null" class="flex items-center gap-2 rounded-lg border border-accent/25 bg-accent-glow p-3">
          <span class="size-2.5 shrink-0 rounded-full bg-accent" />
          <span class="text-sm text-text">
            {{ locale.t('adminOverview.onlineNow', { n: online }) }}
          </span>
        </div>

        <!-- Когда запущено приложение. Первое, на что смотрят после деплоя. -->
        <div v-if="metrics" class="rounded-lg border border-border bg-bg2/50 p-3">
          <p class="text-[11px] uppercase tracking-wide text-text3">
            {{ locale.t('adminOverview.serviceStarted', 'Служба запущена') }}
          </p>
          <p class="mt-1 font-title text-lg font-extrabold leading-none text-text">
            {{ duration(metrics.process_uptime) }}
          </p>
          <p class="mt-1 text-xs text-text3">{{ metrics.started_at || '—' }}</p>
          <p class="mt-2 text-xs text-text3">
            {{ locale.t('adminOverview.machineUptime', 'Машина') }}: {{ duration(metrics.uptime) }}
          </p>
        </div>

        <!-- Память и диск: полоса + само число (значение не передаётся цветом одним). -->
        <div v-if="mem" class="flex flex-col gap-1">
          <div class="flex items-baseline justify-between gap-2">
            <span class="text-xs text-text2">{{ locale.t('adminOverview.memory', 'Оперативная память') }}</span>
            <span class="shrink-0 text-xs font-bold" :class="loadStatus(usedPct(mem.used, mem.total)).text">
              {{ usedPct(mem.used, mem.total) }}%
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-bg2">
            <div class="h-full rounded-full" :class="loadStatus(usedPct(mem.used, mem.total)).bg"
                 :style="{ width: usedPct(mem.used, mem.total) + '%' }" />
          </div>
          <p class="text-[11px] text-text3">
            {{ locale.t('adminOverview.memFree', { free: mb(mem.total - mem.used), total: mb(mem.total) }) }}
          </p>
        </div>

        <div v-if="disk" class="flex flex-col gap-1">
          <div class="flex items-baseline justify-between gap-2">
            <span class="text-xs text-text2">{{ locale.t('adminOverview.disk', 'Диск') }}</span>
            <span class="shrink-0 text-xs font-bold" :class="loadStatus(usedPct(disk.used, disk.total)).text">
              {{ usedPct(disk.used, disk.total) }}%
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-bg2">
            <div class="h-full rounded-full" :class="loadStatus(usedPct(disk.used, disk.total)).bg"
                 :style="{ width: usedPct(disk.used, disk.total) + '%' }" />
          </div>
          <p class="text-[11px] text-text3">
            {{ locale.t('adminOverview.diskFree', { free: gb(disk.total - disk.used), total: gb(disk.total) }) }}
          </p>
        </div>

        <!-- Сколько людей в системе. Заодно самый дешёвый признак «база живая». -->
        <div v-if="counts" class="grid grid-cols-2 gap-2">
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.students', 'Студентов') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-accent">{{ counts.students ?? '—' }}</p>
          </div>
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.teachers', 'Преподавателей') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-text">{{ counts.teachers ?? '—' }}</p>
          </div>
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.groups', 'Групп') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-text">{{ counts.groups ?? '—' }}</p>
          </div>
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.grades', 'Оценок') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-text">{{ counts.grades ?? '—' }}</p>
          </div>
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.subjects', 'Предметов') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-text">{{ counts.subjects ?? '—' }}</p>
          </div>
          <div class="rounded-lg border border-border bg-bg2/50 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('adminOverview.lessons', 'Занятий') }}
            </p>
            <p class="mt-1 font-title text-xl font-extrabold leading-none text-text">{{ counts.lessons ?? '—' }}</p>
          </div>
        </div>

        <!-- Шифрование базы — свойство, о котором админ обязан знать в лицо: без ключа
             резервная копия бесполезна, и путать эти два состояния нельзя. -->
        <p v-if="metrics?.database" class="text-[11px] text-text3">
          {{ locale.t('adminOverview.database', 'База') }}: {{ gb(metrics.database.size) }} ГБ ·
          <span :class="metrics.database.encrypted ? 'text-accent' : 'text-yellow'">
            {{ metrics.database.encrypted
              ? locale.t('adminOverview.encrypted', 'зашифрована')
              : locale.t('adminOverview.notEncrypted', 'без шифрования') }}
          </span>
        </p>
      </div>
    </div>
  </section>
</template>
