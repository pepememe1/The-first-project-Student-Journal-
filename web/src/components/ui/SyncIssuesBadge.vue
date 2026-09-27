<script setup>
// SyncIssuesBadge — «твои правки НЕ уехали на сервер».
//
// Отдельно от ConnectionBadge намеренно: тот отвечает на вопрос «есть ли связь», а этот —
// «дошло ли». Состояния разные и не совпадают: связь может быть прекрасной, а оценка
// всё равно останется только на этом компьютере — потому что сервер её отверг (админ
// снял назначение, пока преподаватель работал) или потому что она конфликтует с чужой
// правкой и разрешить конфликт пока нечем.
//
// ⚠️ Виден ТОЛЬКО когда есть о чём сказать. Постоянно горящее «всё синхронизировано» —
// шум, который перестают замечать; то же правило уже принято для ConnectionBadge на
// сайте, для порога риска отчисления и для подтверждения опасных команд.
//
// ⚠️ Работает только ВНУТРИ программы: источник (`/desk/sync/status`) существует лишь в
// локальном сервере. На сайте запрос получает 404, модуль замолкает навсегда, и значок
// не появляется никогда — специальной проверки «мы в браузере» для этого не нужно.
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ShieldCheck, TriangleAlert } from '@lucide/vue'

import { refresh, start, stop, syncIssues, syncState, verifiedAt } from '@/api/desktopSync'
import { useLocaleStore } from '@/stores/locale'
import SyncProblemsPanel from '@/components/ui/SyncProblemsPanel.vue'

const locale = useLocaleStore()

const issues = computed(() => syncIssues())
const visible = computed(() => issues.value.length > 0)
//«Сверено» — тихая строка, а не плашка: главное здесь по-прежнему беды, и спокойное
//состояние не имеет права кричать (правило значка выше). Только внутри программы и только
//свежая сверка — см. `verifiedAt`.
const verified = computed(() => (visible.value ? '' : verifiedAt(syncState.value)))
//Разбирать есть что, только когда очередь хранит конфликты или отказы: у остальных бед
//(нет связи, вход) лечение не на этом экране.
const canResolve = computed(() => issues.value.some((i) => i.kind === 'conflicts' || i.kind === 'rejected'))
const showProblems = ref(false)

function hhmm(iso) {
  try {
    return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
  } catch { return '' }
}

// Одна строка на проблему: их редко больше одной, а перечисление сразу отвечает
// «что именно не так», без второго клика.
const lines = computed(() => issues.value.map((i) => {
  if (i.kind === 'auth') return locale.t('syncIssues.auth', 'Вход не проходит — правки не отправляются')
  if (i.kind === 'conflicts') return locale.t('syncIssues.conflicts', { n: i.count })
  if (i.kind === 'pending') return locale.t('syncIssues.pending', { n: i.count })
  if (i.kind === 'verify') return locale.t('syncIssues.verify', { n: i.count })
  if (i.kind === 'mirror') {
    return i.since
      ? locale.t('syncIssues.mirrorSince', { time: hhmm(i.since) })
      : locale.t('syncIssues.mirror', 'Данные на экране могут быть устаревшими: копия не обновилась')
  }
  return locale.t('syncIssues.rejected', { n: i.count })
}))

onMounted(start)
// Значок живёт в сайдбаре и не размонтируется при переходах, но опрос всё равно гасим
// явно: без этого он пережил бы выход из аккаунта и продолжил стучаться с чужим токеном.
onBeforeUnmount(stop)
</script>

<template>
  <div v-if="visible"
       class="flex items-start gap-2 rounded-sm border border-yellow/40 bg-yellow/10 px-2.5 py-2 text-tiny text-text2">
    <TriangleAlert class="mt-px size-3.5 shrink-0 text-yellow" />
    <div class="min-w-0">
      <div class="font-semibold text-text">{{ locale.t('syncIssues.title', 'Не всё уехало на сервер') }}</div>
      <div v-for="(l, i) in lines" :key="i" class="mt-0.5 break-words">{{ l }}</div>
      <button v-if="canResolve" type="button"
              class="mt-1.5 font-semibold text-accent underline-offset-2 hover:underline focus-visible:underline"
              @click="showProblems = true">
        {{ locale.t('syncIssues.resolve', 'Разобрать') }}
      </button>
    </div>
    <SyncProblemsPanel v-if="showProblems" @close="showProblems = false" @changed="refresh" />
  </div>
  <div v-else-if="verified" class="flex items-center gap-1.5 px-1 text-tiny text-text3"
       :title="locale.t('syncIssues.verifiedHint', 'Сверщик сравнил копию на этом компьютере с сервером — сходится')">
    <ShieldCheck class="size-3.5 shrink-0 text-green" aria-hidden="true" />
    <span>{{ locale.t('syncIssues.verified', { time: hhmm(verified) }) }}</span>
  </div>
</template>
