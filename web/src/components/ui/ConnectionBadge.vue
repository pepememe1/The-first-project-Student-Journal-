<script setup>
// ConnectionBadge — «сейчас онлайн / сейчас офлайн» и с какого момента данные.
//
// Зачем вообще. Без сети экраны показывают СОХРАНЁННУЮ копию и выглядят точно так же,
// как свежие: студент видит оценки и не знает, что они вчерашние. Значок отвечает на
// оба вопроса сразу — есть ли связь и насколько стары данные.
//
// ⚠️ В приложении значок виден ВСЕГДА, а в браузере — только когда связи нет. Постоянно
// горящее «Онлайн» на сайте не сообщает ничего (браузер и так открыт по сети) и быстро
// перестаёт замечаться; в приложении же режим — существенная часть состояния, и его
// отсутствие пришлось бы угадывать по тому, что данные не меняются.
import { computed } from 'vue'
import { WifiOff, Wifi } from '@lucide/vue'

import { cacheVersion } from '@/api/offlineCache'
import { lastOnlineAt, online } from '@/api/offlineSession'
import { isNativeApp } from '@/api/server'
import { pendingCount } from '@/api/outbox'
import { useLocaleStore } from '@/stores/locale'
import { freshness } from '@/utils/freshness'

const locale = useLocaleStore()
const native = isNativeApp()

const visible = computed(() => native || !online.value)

const since = computed(() => {
  // cacheVersion упомянут НАМЕРЕННО: он двигается на каждой записи в кэш и заставляет
  // подпись пересчитаться. Без него она застыла бы на первом значении — время в
  // localStorage меняется мимо системы реактивности Vue.
  void cacheVersion.value
  return freshness(lastOnlineAt.value)
})

const sinceText = computed(() => {
  const f = since.value
  if (f.kind === 'never') return ''
  if (f.kind === 'now') return locale.t('freshness.now', 'только что')
  if (f.kind === 'minutes') return locale.t('freshness.minutes', { n: f.n })
  if (f.kind === 'today') return locale.t('freshness.today', { time: f.time })
  if (f.kind === 'yesterday') return locale.t('freshness.yesterday', { time: f.time })
  return locale.t('freshness.date', { date: f.date, time: f.time })
})
</script>

<template>
  <div
    v-if="visible"
    class="flex items-center gap-1.5 text-[11px] leading-none"
    :class="online ? 'text-text3' : 'text-yellow'"
    :title="online
      ? locale.t('offline.onlineHint', 'Связь с сервером есть')
      : locale.t('offline.offlineHint', 'Связи нет — показаны сохранённые данные')"
  >
    <component :is="online ? Wifi : WifiOff" class="w-3.5 h-3.5 shrink-0" />
    <span class="truncate">
      {{ online ? locale.t('offline.online', 'Онлайн') : locale.t('offline.offline', 'Офлайн') }}
      <template v-if="!online && sinceText">· {{ sinceText }}</template>
    </span>
    <!-- Счётчик неотправленного важнее самого режима: он говорит, что работа ещё не
         уехала на сервер, и не даёт закрыть день в уверенности, что всё сохранено. -->
    <span
      v-if="pendingCount"
      class="px-1.5 py-0.5 rounded-full bg-yellow/15 text-yellow shrink-0"
      :title="locale.t('offline.pendingHint', 'Оценки уйдут на сервер, как только появится сеть')"
    >{{ locale.t('offline.pending', { n: pendingCount }) }}</span>
  </div>
</template>
