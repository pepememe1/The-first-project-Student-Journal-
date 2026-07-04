<script setup>
// Mascot — маскот «Вектор» (арт Арины): один из 30 спрайтов эмоций (морда+жест).
// Слаг — через prop `sprite`; выбор слага — config/mascot.js. `animate` добавляет
// мягкое «дыхание». Смена эмоции — настоящий КРОСС-ФЕЙД (оба кадра видны одновременно),
// а не мгновенная подмена. Дыхание идёт на GPU-слое (translateZ) — без дрожи.
import { computed } from 'vue'
const props = defineProps({
  sprite: { type: String, default: 'neutral-idle' },
  animate: { type: Boolean, default: true },
})
const src = computed(() => `/mascot/${props.sprite}.png`)
</script>

<template>
  <div class="mascot" :class="{ 'mascot--float': animate }">
    <transition name="mascot-swap">
      <img :key="src" :src="src" alt="Вектор"
           class="mascot__img select-none object-contain" draggable="false" />
    </transition>
  </div>
</template>

<style scoped>
.mascot { position: relative; }
/* Оба кадра занимают одно место (absolute) — при смене эмоции идёт кросс-фейд без
   мига пустоты, который раньше давал mode="out-in". */
.mascot__img {
  position: absolute;
  inset: 0;
  height: 100%;
  width: 100%;
  transform: translateZ(0);         /* свой GPU-слой → дыхание без дрожи/ресемплинга */
  backface-visibility: hidden;
  will-change: transform, opacity;
}
/* Дыхание: очень мягкий масштаб от нижней точки (как будто вдох-выдох), медленно. */
.mascot--float .mascot__img {
  transform-origin: 50% 100%;
  animation: mascot-breathe 9s ease-in-out infinite;
}
@keyframes mascot-breathe {
  0%, 100% { transform: translateZ(0) scale(1); }
  50%      { transform: translateZ(0) scale(1.015); }
}
/* Плавная смена кадра эмоции (кросс-фейд). */
.mascot-swap-enter-active, .mascot-swap-leave-active { transition: opacity 0.45s ease; }
.mascot-swap-enter-from, .mascot-swap-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .mascot--float .mascot__img { animation: none; } }
</style>
