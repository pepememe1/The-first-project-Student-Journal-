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
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { TriangleAlert } from '@lucide/vue'

import { start, stop, syncIssues } from '@/api/desktopSync'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const issues = computed(() => syncIssues())
const visible = computed(() => issues.value.length > 0)

// Одна строка на проблему: их редко больше одной, а перечисление сразу отвечает
// «что именно не так», без второго клика.
const lines = computed(() => issues.value.map((i) => {
  if (i.kind === 'auth') return locale.t('syncIssues.auth', 'Вход не проходит — правки не отправляются')
  if (i.kind === 'conflicts') return locale.t('syncIssues.conflicts', { n: i.count })
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
    </div>
  </div>
</template>
