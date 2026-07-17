<script setup>
// Mascot — маскот «Вектор» (арт Арины). Два режима отображения одного персонажа:
//   • ЭМОЦИЯ (prop `sprite`) — один из 30 статичных спрайтов «морда+жест» (§5): настроение
//     по успеваемости на дашборде. `animate` добавляет мягкое «дыхание».
//   • ДЕЙСТВИЕ (prop `anim`) — анимированный WebP с альфой (idle/greeting/thinking/speaking):
//     что Вектор делает в ЧАТЕ. Один WebP-файл играет и в браузере (веб/мобилка), и в Qt
//     (десктоп) — общий формат на все платформы. `anim` имеет приоритет над `sprite`.
// Смена кадра — настоящий КРОСС-ФЕЙД (оба видны одновременно), без мига пустоты.
import { computed, onMounted } from 'vue'
import { preloadMascots, preloadAnims } from '@/config/mascot'
const props = defineProps({
  sprite: { type: String, default: 'neutral-idle' },
  animate: { type: Boolean, default: true },
  // Активность для анимированного режима: idle | greeting | thinking | speaking.
  // Пусто — показываем статичный спрайт эмоции (§5).
  anim: { type: String, default: '' },
})
// anim (WebP) приоритетнее статичного спрайта. WebP сам зациклен (loop=0) — «дыхание»
// в этом режиме не нужно (персонаж и так двигается: уши/хвост/рот).
const src = computed(() =>
  props.anim ? `/mascot/anim/${props.anim}.webp` : `/mascot/${props.sprite}.png`)
onMounted(() => { preloadMascots(); preloadAnims() })
</script>

<template>
  <div class="mascot" :class="{ 'mascot--float': animate && !anim }">
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
/* Смена состояния — МГНОВЕННО (снаппи): очень короткий кросс-фейд только чтобы скрыть
   микро-декод нового WebP, без ощутимой задержки между переключениями анимаций. */
.mascot-swap-enter-active, .mascot-swap-leave-active { transition: opacity 0.06s linear; }
.mascot-swap-enter-from, .mascot-swap-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .mascot--float .mascot__img { animation: none; } }
</style>
