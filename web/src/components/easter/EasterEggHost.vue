<script setup>
// EasterEggHost — единственное место, где пасхалка попадает на экран.
//
// Висит в оболочке (AppShell) и рисует ту сцену, которую выбрал стор. Почему один хост,
// а не по компоненту на страницу: сцены полноэкранные и должны переживать переход между
// вкладками (дерево Делтарун выпадает ИМЕННО на переходе), а ещё их нельзя показывать
// по две сразу. И то и другое проще держать в одной точке, чем повторять пятнадцать раз.
//
// ⚠️ Каждая сцена — ЛЕНИВАЯ (`defineAsyncComponent`). Вместе они весят прилично, а
// сработает за сессию в лучшем случае одна: попади они в основной чанк, мы бы удлинили
// первую загрузку журнала всем и каждый день ради того, что случается раз в месяц.
import { defineAsyncComponent, computed } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { BY_ID } from '@/config/achievements'

const easter = useEasterStore()

const SCENES = {
  deltarune_tree:      defineAsyncComponent(() => import('./DeltaruneTree.vue')),
  cyberpunk_login:     defineAsyncComponent(() => import('./CyberpunkGlitch.vue')),
  stanley_parable_404: defineAsyncComponent(() => import('./StanleyNarrator.vue')),
  rdr2_404:            defineAsyncComponent(() => import('./Rdr2Plan.vue')),
  dark_souls_logout:   defineAsyncComponent(() => import('./DarkSoulsFarewell.vue')),
  gman_observer:       defineAsyncComponent(() => import('./GmanWatcher.vue')),
  hotline_miami:       defineAsyncComponent(() => import('./HotlineScene.vue')),
  skyrim_wake_up:      defineAsyncComponent(() => import('./SkyrimCart.vue')),
  farcry_vaas_quote:   defineAsyncComponent(() => import('./FarCryQuote.vue')),
  portal_cake:         defineAsyncComponent(() => import('./PortalCake.vue')),
  fnaf_night_mode:     defineAsyncComponent(() => import('./FnafOffice.vue')),
}

const scene = computed(() => SCENES[easter.active] || null)
const toast = computed(() => (easter.lastUnlocked ? BY_ID[easter.lastUnlocked] : null))
</script>

<template>
  <component :is="scene" v-if="scene" @close="easter.close()" />

  <!-- Тост о находке. Живёт ОТДЕЛЬНО от сцены: сцена к этому моменту уже закрылась,
       а сказать про ачивку надо — иначе человек не поймёт, что что-то получил. -->
  <Transition name="ach">
    <div v-if="toast" class="pointer-events-auto fixed bottom-4 right-4 z-[95] flex items-center gap-3
                             rounded-xl border border-accent bg-card px-4 py-3 shadow-card"
         role="status" @click="easter.clearToast()">
      <span class="text-2xl">{{ toast.icon }}</span>
      <span class="flex flex-col leading-tight">
        <span class="text-sm font-semibold text-text">{{ toast.title }}</span>
        <span class="font-mono text-[10px] uppercase tracking-wider text-text3">Достижение открыто</span>
      </span>
    </div>
  </Transition>
</template>

<style scoped>
.ach-enter-active, .ach-leave-active { transition: opacity .3s, transform .3s; }
.ach-enter-from, .ach-leave-to { opacity: 0; transform: translateY(12px); }
</style>
