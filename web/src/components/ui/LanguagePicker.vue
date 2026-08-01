<script setup>
// LanguagePicker — глобус, за которым прячется выбор языка интерфейса.
//
// Флаг вместо подписи — по просьбе заказчика и по делу: человек, который не читает
// по-русски, не найдёт слово «Язык», но флаг своей страны узнает мгновенно. Название
// языка всё равно показываем В САМОМ СПИСКЕ и на родном языке («中文», а не «китайский»):
// подпись на чужом языке в выпадающем списке помогает ничуть не больше, чем её отсутствие.
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Globe, Check } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'

defineProps({
  // На тёмной картинке экрана входа кнопка должна быть светлой, в кабинете — обычной.
  tone: { type: String, default: 'default' },
})

const loc = useLocaleStore()
const open = ref(false)
const root = ref(null)

function pick(code) {
  loc.set(code)
  open.value = false
}
// Клик мимо закрывает список: без этого он остаётся висеть поверх формы входа, и человек
// тычет в поле логина, а попадает в меню.
function onDocClick(e) {
  if (open.value && root.value && !root.value.contains(e.target)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="relative">
    <button type="button" :aria-label="loc.t('login.language')" :title="loc.t('login.language')"
            :aria-expanded="open" aria-haspopup="listbox"
            class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm transition-colors"
            :class="tone === 'light'
              ? 'border-white/25 bg-black/25 text-white hover:border-white/50'
              : 'border-border bg-card2 text-text2 hover:border-accent'"
            @click="open = !open">
      <Globe class="size-4" />
      <span class="text-base leading-none">{{ loc.current.flag }}</span>
    </button>

    <ul v-if="open" role="listbox"
        class="absolute right-0 z-50 mt-1.5 min-w-[160px] overflow-hidden rounded-lg border border-border bg-card shadow-xl">
      <li v-for="l in loc.locales" :key="l.code" role="option"
          :aria-selected="l.code === loc.locale">
        <button type="button"
                class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-card2"
                :class="l.code === loc.locale ? 'text-accent' : 'text-text2'"
                @click="pick(l.code)">
          <span class="text-base leading-none">{{ l.flag }}</span>
          <span class="flex-1">{{ l.name }}</span>
          <Check v-if="l.code === loc.locale && loc.translateUi" class="size-4" />
        </button>
      </li>
    </ul>
  </div>
</template>
