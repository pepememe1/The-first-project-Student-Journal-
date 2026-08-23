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

/**
 * Обёртка над ленивой загрузкой сцены.
 *
 * 🔥 ЗАЧЕМ (найдено 23.08.2026). Каждая сцена лежит отдельным файлом и подгружается в
 * момент показа. Если файла на сервере уже нет — а после выкладки старые файлы именно
 * исчезали, — `import()` падает, `defineAsyncComponent` МОЛЧА не рисует ничего, а стор
 * продолжает считать, что сцена играет. Наружу это выглядит так: продукт говорит «на
 * экране пасхалка», а на экране пусто, и слот занят до конца сессии.
 *
 * Само исчезновение файлов чинится в `deploy/deploy-web.sh` (старые чанки теперь
 * переживают выкладку), но полагаться только на это нельзя: файл может не доехать и по
 * сети. Поэтому здесь — второй рубеж: не смогли загрузить, значит СНИМАЕМ пасхалку и
 * пишем в консоль причину. Лучше не показать находку, чем запереть все следующие.
 *
 * ⚠️ `suspensible: false` обязателен: иначе ошибка всплывает наружу, к ближайшему
 * <Suspense> в дереве страницы, и роняет уже её.
 */
function lazyScene(loader, id) {
  return defineAsyncComponent({
    loader,
    suspensible: false,
    onError(err, retry, fail, attempts) {
      if (attempts <= 1) { retry(); return }     // одна повторная попытка — на случай сети
      console.warn('[пасхалки] не загрузилась сцена', id, '— снимаем:', err?.message || err)
      useEasterStore().close()
      fail()
    },
  })
}

// ⚠️ `dark_souls_logout` здесь НЕТ намеренно. Она прощальная и обязана пережить
// `logout()`, который обнуляет стор пасхалок; поэтому её рисует сама страница настроек
// своим состоянием (`Settings.vue`), рядом с обычным прощанием Вектора. Вернёшь сюда —
// сцена снова будет стираться за мгновение до показа, а выход подвисать на пустом
// экране. Держит `easterEggsWired.test.mjs`.
const SCENES = {
  deltarune_tree:      lazyScene(() => import('./DeltaruneTree.vue'), 'deltarune_tree'),
  cyberpunk_login:     lazyScene(() => import('./CyberpunkGlitch.vue'), 'cyberpunk_login'),
  stanley_parable_404: lazyScene(() => import('./StanleyNarrator.vue'), 'stanley_parable_404'),
  rdr2_404:            lazyScene(() => import('./Rdr2Plan.vue'), 'rdr2_404'),
  gman_observer:       lazyScene(() => import('./GmanWatcher.vue'), 'gman_observer'),
  hotline_miami:       lazyScene(() => import('./HotlineScene.vue'), 'hotline_miami'),
  skyrim_wake_up:      lazyScene(() => import('./SkyrimCart.vue'), 'skyrim_wake_up'),
  farcry_vaas_quote:   lazyScene(() => import('./FarCryQuote.vue'), 'farcry_vaas_quote'),
  portal_cake:         lazyScene(() => import('./PortalCake.vue'), 'portal_cake'),
  fnaf_night_mode:     lazyScene(() => import('./FnafOffice.vue'), 'fnaf_night_mode'),
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
