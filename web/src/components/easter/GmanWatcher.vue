<script setup>
// G-Man в «Настройках»: проявляется по мере того, как человек там сидит.
//
// ⚠️ Потолок непрозрачности — 5%, и это не осторожность, а суть: он должен КАЗАТЬСЯ, а
// не смотреть в упор. На стенде пробовали 20% и 55% — оба раза читалось как баннер.
//
// 🔥 РАССИНХРОН МИГАНИЯ (найдено 23.08.2026, отзыв Влада: «сначала мигает, потом спустя
// секунду он пропадает»). Причина — ОДНА длительность перехода на оба направления:
// проявление идёт 45 секунд, и то же самое значение применялось к ИСЧЕЗНОВЕНИЮ. То есть
// экран моргал, а лицо после этого таяло ещё три четверти минуты у всех на виду — ровно
// наоборот тому, ради чего мигание и задумано.
//
// Порядок теперь жёсткий и весь смысл в нём: гасим экран → ПОКА ОН ЧЁРНЫЙ убираем лицо
// мгновенно → открываем экран. Исчезновения не видно вовсе, и остаётся ровно то
// ощущение, которое нужно: только что он был, а теперь его нет, и непонятно, был ли.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const face = ref(0)
const blink = ref(false)
// ⚠️ Длительность перехода — ВЕЛИЧИНА, а не константа в стилях. Именно попытка обойтись
// одним числом на оба направления и дала дефект.
const fadeMs = ref(45000)
let timers = []

const wait = (ms) => new Promise((r) => { timers.push(setTimeout(r, ms)) })

onMounted(async () => {
  requestAnimationFrame(() => { face.value = 0.05 })
  await wait(45000)              // проявление идёт около минуты — торопить его незачем

  blink.value = true             // экран гаснет
  await wait(110)                // ждём, пока он ДЕЙСТВИТЕЛЬНО стал чёрным
  fadeMs.value = 0               // и только теперь снимаем лицо — под прикрытием черноты
  face.value = 0
  await wait(60)
  blink.value = false            // открываем экран: лица уже нет

  await wait(1800)
  await easter.claim('gman_observer')
  emit('close')
})

onBeforeUnmount(() => timers.forEach(clearTimeout))
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[88]">
    <div class="absolute inset-0 bg-contain bg-center bg-no-repeat"
         style="background-image:url(/easter/img/gman.webp);mix-blend-mode:soft-light"
         :style="{ opacity: face, transition: `opacity ${fadeMs}ms linear` }"></div>
    <!-- Чернота гаснет и открывается быстро и ОДИНАКОВО в обе стороны: это моргание, а
         не затемнение. 100 мс сюда, 100 мс обратно. -->
    <div class="absolute inset-0 bg-black transition-opacity duration-100"
         :style="{ opacity: blink ? 1 : 0 }"></div>
  </div>
</template>
