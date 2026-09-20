<script setup>
// StorageFailedBadge — «вы работаете, но устройство ничего не запоминает».
//
// 🔥 Зачем заведён (20.09.2026, находка ревью O01). Очередь офлайн-правок писалась в
// localStorage, и отказ записи (переполнена квота, приватный режим, запрет сайту)
// ГЛОТАЛСЯ с комментарием «очередь короткая, терять нечего». Терять было что: очередь и
// есть та работа преподавателя, которую он сделал без сети. Журнал при этом honestly
// писал «оценка сохранена и уйдёт, когда появится связь» — то есть продукт подтверждал
// сохранение, которого не было, а следующая же перезагрузка очереди читала пустой диск.
//
// ⚠️ Это НЕ «сервер отказал» (для того есть RejectedWritesBadge) и НЕ «нет связи» (для
// того ConnectionBadge). Здесь третье состояние, и оно срочнее обоих: работа жива ровно
// пока открыта вкладка. Поэтому отдельная плашка и прямой совет, а не значок в ряду.
//
// ⚠️ Кнопки «повторить» нет по той же причине, что у соседа: повторять нечего — отказал
// диск, а не отправка. Помогает либо освободить место, либо выйти из приватного режима,
// либо просто дождаться связи, не закрывая вкладку. Это и сказано словами.
import { computed } from 'vue'
import { HardDriveDownload } from '@lucide/vue'

import { pendingCount, storageFailed } from '@/api/outbox'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

// Показываем, только когда есть ЧТО потерять: сам по себе сломанный localStorage при
// пустой очереди человека не касается, а плашка «на всякий случай» приучает не читать.
const visible = computed(() => storageFailed.value && pendingCount.value > 0)
</script>

<template>
  <div v-if="visible"
       class="rounded-sm border border-yellow/40 bg-yellow/10 px-2.5 py-2 text-tiny text-text2">
    <div class="flex items-start gap-2">
      <HardDriveDownload class="mt-px size-3.5 shrink-0 text-yellow" />
      <span class="min-w-0 flex-1">
        <span class="block font-semibold text-text">
          {{ locale.t('storageFailed.title', 'Не сохранено на устройстве') }}
        </span>
        <span class="block opacity-80">
          {{ locale.t('storageFailed.hint', 'Браузер не даёт сохранить очередь. Не закрывайте вкладку, пока правки не уйдут.') }}
        </span>
        <span class="block opacity-70">{{ locale.t('storageFailed.count', { n: pendingCount }) }}</span>
      </span>
    </div>
  </div>
</template>
