<script setup>
// AccessibilityMenu — кнопка-очки «Версия для слабовидящих» + всплывающее меню.
//
// Ровно тот элемент, что стоит на порталах вузов (иконка очков): крупность шрифта в три
// ступени и высокий контраст. Настройки живут в stores/a11y.js (устройство, localStorage).
//
// Размещается в сайдбаре (десктоп) и на мобильной полосе — всегда на виду, потому что
// человеку со слабым зрением её нельзя прятать в глубину настроек.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Glasses, Contrast, X } from '@lucide/vue'
import { useA11yStore } from '@/stores/a11y'
import { useLocaleStore } from '@/stores/locale'

// Открывать меню вверх (в сайдбаре кнопка внизу) или вниз (на мобильной полосе сверху).
// `placement` читается прямо в шаблоне (<script setup> раскрывает пропсы автоматически).
defineProps({ placement: { type: String, default: 'up' } })

const a11y = useA11yStore()
const loc = useLocaleStore()
const open = ref(false)
const rootEl = ref(null)

const t = (k, f) => loc.t(k, f)
// Ступени крупности: подпись и множитель для показа.
const steps = computed(() => [
  { step: 0, label: t('a11y.sizeNormal', 'Обычный') },
  { step: 1, label: t('a11y.sizeLarge', 'Крупнее') },
  { step: 2, label: t('a11y.sizeXL', 'Максимум') },
])

function onDocClick(e) {
  if (open.value && rootEl.value && !rootEl.value.contains(e.target)) open.value = false
}
function onKey(e) { if (e.key === 'Escape') open.value = false }
onMounted(() => {
  document.addEventListener('pointerdown', onDocClick, true)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocClick, true)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="rootEl" class="relative">
    <!-- Кнопка-очки. Подсвечена акцентом, когда режим включён. -->
    <button type="button" @click="open = !open"
            :aria-label="t('a11y.title', 'Версия для слабовидящих')"
            :title="t('a11y.title', 'Версия для слабовидящих')"
            :aria-pressed="a11y.active"
            class="grid size-9 place-items-center rounded-md border transition-colors"
            :class="a11y.active
              ? 'border-accent bg-accent-glow text-accent'
              : 'border-transparent text-text3 hover:bg-accent-glow hover:text-accent'">
      <Glasses class="size-5" />
    </button>

    <!-- Меню -->
    <transition name="a11y-pop">
      <div v-if="open"
           class="absolute z-50 w-60 rounded-xl border border-border2 bg-card p-3 shadow-card"
           :class="placement === 'up'
             ? 'bottom-full left-0 mb-2'
             : 'top-full right-0 mt-2'">
        <div class="mb-2 flex items-center gap-2">
          <Glasses class="size-4 shrink-0 text-accent" />
          <p class="min-w-0 flex-1 truncate font-title text-sm font-bold text-text">
            {{ t('a11y.title', 'Версия для слабовидящих') }}
          </p>
          <button type="button" @click="open = false"
                  :aria-label="t('common.close', 'Закрыть')"
                  class="grid size-6 shrink-0 place-items-center rounded text-text3 hover:bg-bg2 hover:text-text">
            <X class="size-4" />
          </button>
        </div>

        <!-- Крупность шрифта -->
        <p class="mb-1 text-tiny font-medium uppercase tracking-wide text-text2">
          {{ t('a11y.fontSize', 'Размер шрифта') }}
        </p>
        <div class="mb-3 flex gap-1">
          <button v-for="s in steps" :key="s.step" type="button"
                  @click="a11y.setFontScale(s.step)"
                  class="flex-1 rounded-md border px-1 py-1.5 text-center transition-colors"
                  :class="a11y.fontScale === s.step
                    ? 'border-accent bg-accent-glow text-accent'
                    : 'border-border2 text-text3 hover:border-accent hover:text-accent'">
            <span class="block font-bold leading-none"
                  :style="{ fontSize: (12 + s.step * 4) + 'px' }">А</span>
            <span class="mt-0.5 block text-tiny">{{ s.label }}</span>
          </button>
        </div>

        <!-- Высокий контраст -->
        <button type="button" @click="a11y.toggleContrast()"
                class="flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left text-sm transition-colors"
                :class="a11y.contrast
                  ? 'border-accent bg-accent-glow text-accent'
                  : 'border-border2 text-text2 hover:border-accent'">
          <Contrast class="size-4 shrink-0" />
          <span class="min-w-0 flex-1 truncate">{{ t('a11y.contrast', 'Высокий контраст') }}</span>
          <span class="shrink-0 rounded-full px-2 py-0.5 text-tiny font-bold"
                :class="a11y.contrast ? 'bg-accent text-white' : 'bg-bg2 text-text3'">
            {{ a11y.contrast ? t('common.on', 'вкл') : t('common.off', 'выкл') }}
          </span>
        </button>

        <!-- Сброс -->
        <button v-if="a11y.active" type="button" @click="a11y.reset()"
                class="mt-2 w-full rounded-md px-2.5 py-1.5 text-center text-xs text-text3 transition-colors hover:bg-bg2 hover:text-text">
          {{ t('a11y.reset', 'Вернуть обычный вид') }}
        </button>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.a11y-pop-enter-active,
.a11y-pop-leave-active { transition: opacity 0.12s ease, transform 0.12s ease; }
.a11y-pop-enter-from,
.a11y-pop-leave-to { opacity: 0; transform: translateY(4px); }
</style>
