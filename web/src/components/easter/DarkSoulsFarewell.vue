<script setup>
// Dark Souls на выходе из аккаунта. Заменяет обычное прощание Вектора.
//
// ⚠️ Ачивка закрывается СРАЗУ при показе, а не по завершении анимации: следом идёт
// реальный выход, страница перезагрузится, и «доиграть» будет уже негде.
import { onMounted, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()
const veil = ref(false), band = ref(false), text = ref(false)

onMounted(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))
  veil.value = true
  await wait(400); band.value = true
  await wait(300); text.value = true
  easter.claim('dark_souls_logout')
  await wait(2600); veil.value = band.value = text.value = false
  await wait(1700); emit('close')
})
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[94]">
    <div class="absolute inset-0 bg-black transition-opacity duration-1000"
         :style="{ opacity: veil ? 0.42 : 0 }"></div>
    <div class="absolute inset-x-0 top-1/2 grid h-[23%] -translate-y-1/2 place-items-center
                transition-opacity duration-1000"
         :style="{ background:'rgba(0,0,0,.55)', opacity: band ? 1 : 0 }">
      <p class="whitespace-nowrap transition-opacity duration-1000"
         :style="{ fontFamily:'\'Cormorant Garamond\', Georgia, serif',
                   fontSize:'clamp(20px,4.6vw,40px)', letterSpacing:'.24em',
                   color:'#d9c07a', textShadow:'0 0 22px rgba(217,192,122,.45)',
                   opacity: text ? 1 : 0 }">СЕССИЯ ЗАВЕРШЕНА</p>
    </div>
  </div>
</template>
