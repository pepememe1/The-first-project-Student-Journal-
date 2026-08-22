<script setup>
// G-Man в «Настройках»: проявляется по мере того, как человек там сидит.
//
// ⚠️ Потолок непрозрачности — 5%, и это не осторожность, а суть: он должен КАЗАТЬСЯ, а
// не смотреть в упор. На стенде пробовали 20% и 55% — оба раза читалось как баннер.
// На пороге экран моргает ОДИН раз, лицо исчезает, и через две секунды даётся ачивка.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()
const face = ref(0), blink = ref(false)
let timers = []

onMounted(() => {
  requestAnimationFrame(() => { face.value = 0.05 })
  timers.push(setTimeout(async () => {
    blink.value = true
    setTimeout(() => { blink.value = false; face.value = 0 }, 140)
    setTimeout(async () => { await easter.claim('gman_observer'); emit('close') }, 2000)
  }, 45000))                     // проявление идёт около минуты — торопить его незачем
})
onBeforeUnmount(() => timers.forEach(clearTimeout))
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[88]">
    <div class="absolute inset-0 bg-contain bg-center bg-no-repeat transition-opacity"
         style="background-image:url(/easter/img/gman.webp);mix-blend-mode:soft-light;transition-duration:45s"
         :style="{ opacity: face }"></div>
    <div class="absolute inset-0 bg-black transition-opacity duration-100"
         :style="{ opacity: blink ? 1 : 0 }"></div>
  </div>
</template>
