<script setup>
// Экран «обновите приложение»: сервер ответил 426 — сборка отстала на пять выпусков
// (server/app/client_app.py). Закрыть нельзя намеренно: старая сборка пишет в журнал по
// старым правилам. «Назад» на Android экран не снимает (v-back-close с пустым действием).
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useLocaleStore } from '@/stores/locale'
import { appPlatform } from '@/utils/appTag'
import GbIcon from '@/components/ui/GbIcon.vue'

const locale = useLocaleStore()
const behind = ref(0)
const platform = appPlatform()
const STORE_URL = 'https://www.rustore.ru/catalog/app/ru.esstu.gradebook'

function onRequired(e) { behind.value = Number(e.detail?.behind) || 5 }
function stay() {}
function reload() { window.location.reload() }
onMounted(() => window.addEventListener('gb:update-required', onRequired))
onBeforeUnmount(() => window.removeEventListener('gb:update-required', onRequired))
</script>

<template>
  <div v-if="behind" v-back-close="stay" role="alertdialog" aria-modal="true" aria-labelledby="gb-force-update-title"
       class="fixed inset-0 z-200 flex items-center justify-center bg-bg/95 p-4">
    <div class="w-full max-w-md rounded-2xl border border-line bg-card p-6 text-center shadow-card">
      <GbIcon name="download" class="mx-auto mb-3 size-10 text-accent" />
      <h2 id="gb-force-update-title" class="mb-2 text-lg font-semibold text-text">
        {{ locale.t('forceUpdate.title', 'Нужно обновить приложение') }}
      </h2>
      <p class="mb-3 text-sm text-text2">
        {{ locale.t('forceUpdate.text', { n: behind }) }}
      </p>
      <p class="mb-5 text-sm text-text2">
        {{ platform === 'apk' ? locale.t('forceUpdate.apk', 'Откройте RuStore и обновите GradeBookAI.')
                              : locale.t('forceUpdate.exe', 'Закройте и снова откройте программу — обновление скачается и установится само.') }}
      </p>
      <div class="flex flex-wrap justify-center gap-2">
        <a v-if="platform === 'apk'" :href="STORE_URL" target="_blank" rel="noopener"
           class="inline-flex min-h-11 items-center rounded-xl bg-accent px-5 font-semibold text-white">
          {{ locale.t('forceUpdate.openStore', 'Открыть RuStore') }}
        </a>
        <button type="button" class="min-h-11 rounded-xl border border-line px-5 font-semibold text-text"
                @click="reload">
          {{ locale.t('forceUpdate.retry', 'Проверить снова') }}
        </button>
      </div>
    </div>
  </div>
</template>
