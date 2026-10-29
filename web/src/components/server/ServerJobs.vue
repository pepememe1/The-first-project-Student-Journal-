<script setup>
// ServerJobs — вкладка «Автоматика»: что боевой сервер делает сам и как это прошло (29.10.2026).
//
// Данные — снимок systemd, его раз в 5 минут пишет сторож тревог (`server/app/jobs_status.py`),
// плюс итоги, которые задачи пишут сами (копии, учения, обновление ОС). Вопрос «а копии
// вообще делаются?» вкладка закрывает одним взглядом: сверху итог, ниже каждая задача —
// когда отработала, чем кончилось и когда следующий раз. Подписи задач — в словаре по
// их имени юнита: сервер отдаёт смысл, а не текст.
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import GbIcon from '@/components/ui/GbIcon.vue'
import { formatCollege } from '@/utils/collegeTime'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const t = locale.t
const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }

const data = ref(null)
const error = ref('')
const busy = ref(false)
const showSystem = ref(false)

async function reload() {
  busy.value = true
  error.value = ''
  try {
    data.value = (await adminApi.serverJobs()).data
  } catch (e) {
    error.value = e?.response?.data?.detail || t('adminJobs.loadFailed', 'Не удалось получить список задач.')
  } finally {
    busy.value = false
  }
}
onMounted(reload)

const BAD = ['failed', 'overdue', 'missing']
const LOOK = {
  ok: { icon: 'ok', tone: 'text-accent', badge: 'green' },
  running: { icon: 'loading', tone: 'text-blue animate-spin', badge: 'blue' },
  failed: { icon: 'fail', tone: 'text-red', badge: 'red' },
  overdue: { icon: 'warn', tone: 'text-orange', badge: 'red' },
  missing: { icon: 'warn', tone: 'text-orange', badge: 'red' },
  never: { icon: 'pending', tone: 'text-text3', badge: 'muted' },
}
const look = (j) => LOOK[j.status] || LOOK.never

// Подписи — полными ключами, а не склейкой: сторож словаря видит только литерал в t('…').
const STATUS = computed(() => ({
  ok: t('adminJobs.status.ok'), failed: t('adminJobs.status.failed'),
  overdue: t('adminJobs.status.overdue'), never: t('adminJobs.status.never'),
  missing: t('adminJobs.status.missing'), running: t('adminJobs.status.running'),
}))
const JOB = computed(() => ({
  'gb-backup': [t('adminJobs.job.backup.title'), t('adminJobs.job.backup.what'), t('adminJobs.job.backup.when')],
  'gb-vulnwatch': [t('adminJobs.job.vulnwatch.title'), t('adminJobs.job.vulnwatch.what'), t('adminJobs.job.vulnwatch.when')],
  'apt-daily-upgrade': [t('adminJobs.job.aptUpgrade.title'), t('adminJobs.job.aptUpgrade.what'), t('adminJobs.job.aptUpgrade.when')],
  'gb-report': [t('adminJobs.job.report.title'), t('adminJobs.job.report.what'), t('adminJobs.job.report.when')],
  'gb-drill': [t('adminJobs.job.drill.title'), t('adminJobs.job.drill.what'), t('adminJobs.job.drill.when')],
  'gb-os-update': [t('adminJobs.job.osUpdate.title'), t('adminJobs.job.osUpdate.what'), t('adminJobs.job.osUpdate.when')],
  'gb-cleanup': [t('adminJobs.job.cleanup.title'), t('adminJobs.job.cleanup.what'), t('adminJobs.job.cleanup.when')],
  logrotate: [t('adminJobs.job.logrotate.title'), t('adminJobs.job.logrotate.what'), t('adminJobs.job.logrotate.when')],
  'gb-alarm': [t('adminJobs.job.alarm.title'), t('adminJobs.job.alarm.what'), t('adminJobs.job.alarm.when')],
  offsite: [t('adminJobs.job.offsite.title'), t('adminJobs.job.offsite.what'), t('adminJobs.job.offsite.when')],
}))
// Новая задача сервера без подписи покажет имя юнита, а не пустую строку.
const jobText = (j) => JOB.value[j.id] || [j.id, j.description || '', '']

const jobs = computed(() => data.value?.jobs || [])
const system = computed(() => data.value?.system || [])
const bad = computed(() => jobs.value.filter((j) => BAD.includes(j.status)))
const systemBad = computed(() => system.value.filter((j) => j.status === 'failed').length)

function when(ts) {
  return ts
    ? formatCollege(new Date(ts * 1000), BCP47[locale.active] || 'ru-RU',
      { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : ''
}

function duration(s) {
  if (s === null || s === undefined) return ''
  return s < 90
    ? t('adminJobs.durSec', { sec: Math.max(1, Math.round(s)) })
    : t('adminJobs.durMin', { min: Math.round(s / 60) })
}

function statusLabel(j) {
  if (j.kind === 'daemon') {
    return j.status === 'ok' ? t('adminJobs.status.daemonOk', 'работает') : t('adminJobs.status.daemonDown', 'остановлен')
  }
  return STATUS.value[j.status] || j.status
}

function lastLine(j) {
  if (j.kind === 'daemon') return j.since ? t('adminJobs.since', { time: when(j.since) }) : ''
  if (!j.last) return ''
  const d = duration(j.duration_s)
  return d ? t('adminJobs.lastRunDuration', { time: when(j.last), dur: d }) : t('adminJobs.lastRun', { time: when(j.last) })
}

function detailText(j) {
  const d = j.detail || {}
  const parts = []
  if (j.id === 'gb-backup' && d.count) {
    parts.push(t('adminJobs.detail.backup', { count: d.count, size: d.size_mb ?? '—' }))
  } else if (j.id === 'gb-vulnwatch' && d.holes !== undefined) {
    parts.push(t('adminJobs.detail.vulnwatch', { holes: d.holes, ours: d.kev_ours ?? 0, hit: d.kev_hit ?? 0 }))
    if (d.errors) parts.push(t('adminJobs.detail.vulnwatchErrors', { count: d.errors }))
  } else if (j.id === 'gb-drill' && d.ok === false) {
    parts.push(t('adminJobs.detail.drillFail', 'Копия не поднялась — подробности в вечерней сводке.'))
  } else if (j.id === 'gb-drill' && d.users) {
    parts.push(t('adminJobs.detail.drill', { boot: d.boot_s ?? '—', users: d.users, grades: d.grades ?? '—', chain: d.chain ?? '—' }))
  } else if (j.id === 'gb-os-update' && d.ok === false) {
    parts.push(t('adminJobs.detail.osUpdateFail', { error: d.error || '—' }))
  } else if (j.id === 'gb-os-update' && d.count !== undefined && d.count !== null) {
    parts.push(t('adminJobs.detail.osUpdate', { count: d.count })
      + (d.reboot ? t('adminJobs.detail.osUpdateReboot', ', с перезагрузкой') : ''))
  } else if (j.id === 'offsite' && d.name) {
    parts.push(t('adminJobs.detail.offsite', { name: d.name }))
  }
  if (j.status === 'failed' && j.exit) parts.push(t('adminJobs.exitCode', { code: j.exit }))
  return parts.join(' · ')
}
</script>

<template>
  <Card :title="t('adminJobs.title', 'Автоматика сервера')"
        :subtitle="t('adminJobs.subtitle', 'Задачи, которые боевой сервер выполняет сам. Время — по Улан-Удэ.')">
    <template #header>
      <AppButton variant="ghost" :disabled="busy" @click="reload">
        <GbIcon name="refresh" class="mr-1.5 inline size-4" :class="busy && 'animate-spin'" />{{ t('adminJobs.refresh', 'Обновить') }}
      </AppButton>
    </template>

    <p v-if="error" class="text-sm text-red">{{ error }}</p>
    <p v-else-if="!data" class="text-sm text-text3">{{ t('common.loading') }}</p>
    <div v-else-if="!data.known" class="rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
      {{ t('adminJobs.unknown', 'Сведений о задачах пока нет. Их снимает сторож тревог на боевом сервере раз в 5 минут — вкладка заполнится после его первого прохода.') }}
    </div>

    <template v-else>
      <!-- Итог одной строкой: ради него вкладку и открывают -->
      <div class="mb-4 flex items-start gap-3 rounded-lg border p-3"
           :class="bad.length ? 'border-red/50 bg-red/5' : 'border-accent/40 bg-accent-glow'">
        <GbIcon :name="bad.length ? 'fail' : 'ok'" class="mt-0.5 size-5 shrink-0"
                :class="bad.length ? 'text-red' : 'text-accent'" />
        <div class="min-w-0 text-sm">
          <p class="font-medium text-text">
            {{ bad.length
              ? t('adminJobs.summaryBad', { bad: bad.length, total: jobs.length })
              : t('adminJobs.summaryOk', { total: jobs.length }) }}
          </p>
          <p class="mt-0.5 text-xs text-text3">{{ t('adminJobs.snapshotAt', { time: when(data.checked_at) }) }}</p>
        </div>
      </div>

      <p v-if="data.stale" class="mb-4 flex items-start gap-2 rounded-lg border border-orange/50 bg-card2 p-3 text-sm text-text2">
        <GbIcon name="warn" class="mt-0.5 size-4 shrink-0 text-orange" />
        {{ t('adminJobs.stale', { time: when(data.checked_at) }) }}
      </p>

      <ul class="divide-y divide-border">
        <li v-for="j in jobs" :key="j.id" class="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
          <GbIcon :name="look(j).icon" class="mt-0.5 size-5 shrink-0" :class="look(j).tone" />
          <div class="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:gap-4">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <p class="font-medium text-text">{{ jobText(j)[0] }}</p>
                <Badge :variant="look(j).badge">{{ statusLabel(j) }}</Badge>
              </div>
              <p class="mt-0.5 text-sm text-text3">{{ jobText(j)[1] }}</p>
              <p v-if="detailText(j)" class="mt-1 text-sm text-text2">{{ detailText(j) }}</p>
            </div>
            <div class="shrink-0 text-sm sm:w-60 sm:text-right">
              <p v-if="jobText(j)[2]" class="text-text2">
                <GbIcon name="hours" class="mr-1 inline size-3.5 align-[-2px] text-text3" />{{ jobText(j)[2] }}
              </p>
              <p v-if="lastLine(j)" class="text-text3">{{ lastLine(j) }}</p>
              <p v-if="j.next" class="text-text3">{{ t('adminJobs.nextRun', { time: when(j.next) }) }}</p>
            </div>
          </div>
        </li>
      </ul>

      <!-- Служебные задачи Ubuntu: настраивает система, нам важен только сбой -->
      <div v-if="system.length" class="mt-5 border-t border-border pt-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="font-medium text-text">
              {{ t('adminJobs.systemTitle', 'Задачи Ubuntu') }}
              <Badge v-if="systemBad" variant="red" class="ml-1">{{ t('adminJobs.systemFailed', { count: systemBad }) }}</Badge>
            </p>
            <p class="text-xs text-text3">{{ t('adminJobs.systemHint', 'Служебные задачи самой системы: списки пакетов, журналы, диск.') }}</p>
          </div>
          <AppButton variant="ghost" @click="showSystem = !showSystem">
            {{ showSystem ? t('adminJobs.systemHide', 'Скрыть') : t('adminJobs.systemShow', { count: system.length }) }}
          </AppButton>
        </div>
        <ul v-if="showSystem" class="mt-3 divide-y divide-border text-sm">
          <li v-for="j in system" :key="j.id" class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <GbIcon :name="look(j).icon" class="size-4 shrink-0" :class="look(j).tone" />
            <span class="min-w-0 flex-1">
              <span class="font-mono text-xs text-text2">{{ j.id }}</span>
              <span v-if="j.description" class="ml-2 text-text3">{{ j.description }}</span>
            </span>
            <span class="text-xs text-text3">
              <template v-if="j.last">{{ t('adminJobs.lastRun', { time: when(j.last) }) }}</template>
              <template v-if="j.next"> · {{ t('adminJobs.nextRun', { time: when(j.next) }) }}</template>
            </span>
          </li>
        </ul>
      </div>
    </template>
  </Card>
</template>
