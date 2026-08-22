<script setup>
// Portal: день рождения. Не по шансу — по совпадению дня и месяца.
//
// ⚠️ Торт и Вектор пока СОБРАНЫ ВЁРСТКОЙ. Влад прислал два рисунка (Вектор с тортом и
// «ТОРТ ЭТО ЛОЖЬ»), но они пришли в переписку, а не в репозиторий; как только файлы
// лягут в easter_eggs/portal/, здесь меняются два src и удаляется эта заглушка.
import { ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const lit = ref(true)
const done = ref(false)

async function blow() {
  lit.value = false
  done.value = true
  setTimeout(async () => { await easter.claim('portal_cake'); }, 900)
}
</script>

<template>
  <div class="fixed inset-0 z-[93] grid place-items-center p-4" style="background:var(--gb-overlay)">
    <div class="flex flex-col items-center gap-3 rounded-xl border border-border2 bg-card px-7 py-5 shadow-card">
      <div class="flex items-end gap-4">
        <img v-if="!done" src="/mascot/happy-congrats.webp" alt="" class="w-20 transition-opacity duration-500" />
        <div class="relative w-24">
          <button v-if="lit" type="button" @click="blow" aria-label="Задуть свечу"
                  class="flame absolute -top-6 left-1/2 h-5 w-3.5 -translate-x-1/2 cursor-pointer border-0 p-0"></button>
          <div class="absolute -top-1.5 left-1/2 h-3 w-1 -translate-x-1/2" style="background:#e8e0d0"></div>
          <div class="h-5 rounded-t" style="background:#f3d9e6"></div>
          <div class="h-6" style="background:#d8a7c4"></div>
          <div class="h-2 rounded-b" style="background:#c9c2b6"></div>
        </div>
      </div>
      <p class="font-title text-base" :class="done ? 'text-text2' : 'text-text'">
        {{ done ? 'Торт — это ложь.' : 'С днём рождения!' }}
      </p>
      <button v-if="!done" type="button" @click="emit('close')"
              class="rounded-lg bg-accent px-5 py-1.5 text-sm font-semibold text-white hover:brightness-110">ОК</button>
      <button v-else type="button" @click="emit('close')"
              class="text-xs text-text3 hover:text-text">закрыть</button>
    </div>
  </div>
</template>

<style scoped>
.flame { background: radial-gradient(circle at 50% 65%, #fff3b0, #ffb01f 45%, #ff6a00 75%, transparent 78%);
         border-radius: 50%/60% 60% 40% 40%; animation: flick .38s infinite alternate; }
@keyframes flick { to { transform: translateX(-50%) scaleY(1.18) scaleX(.9) } }
@media (prefers-reduced-motion: reduce) { .flame { animation: none } }
</style>
