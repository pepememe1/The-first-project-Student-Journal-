<script setup>
// Mascot — маскот «Вектор» (арт Арины). Два режима отображения одного персонажа:
//   • ЭМОЦИЯ (prop `sprite`) — один из 30 статичных спрайтов «морда+жест» (§5): настроение
//     по успеваемости на дашборде. `animate` добавляет мягкое «дыхание».
//   • ДЕЙСТВИЕ (prop `anim`) — анимированный WebP с альфой (idle/greeting/thinking/speaking):
//     что Вектор делает в ЧАТЕ. Один WebP-файл играет и в браузере (веб/мобилка), и в Qt
//     (десктоп) — общий формат на все платформы. `anim` имеет приоритет над `sprite`.
// Смена кадра — настоящий КРОСС-ФЕЙД (оба видны одновременно), без мига пустоты.
import { computed, onMounted } from 'vue'
import { preloadMascots, preloadAnims, ART_VERSION } from '@/config/mascot'
const props = defineProps({
  sprite: { type: String, default: 'neutral-idle' },
  animate: { type: Boolean, default: true },
  // Активность для анимированного режима: idle | greeting | thinking | speaking.
  // Пусто — показываем статичный спрайт эмоции (§5).
  anim: { type: String, default: '' },
  // Что предзагружать заранее: 'chat' (состояния Вектора) | 'login' (покой + глаза).
  scope: { type: String, default: 'chat' },
})
// ⚠️ ВЕРСИЯ АРТА в адресе (`ART_VERSION`, живёт в `config/mascot.js` — одна на проект,
// её же использует предзагрузчик). Файлы маскота лежат в `public/` и потому НЕ получают
// хеш в имени при сборке: `idle.webp` остаётся `idle.webp` навсегда, и браузер продолжает
// показывать копию из кэша даже после нового деплоя. На этом уже обожглись: при пересборке
// анимаций общий кроп кадра изменился (524→442 px), новые состояния приехали, а старые
// достались из кэша — и маскот на экране входа менял размер при вводе пароля.
// Поднимать при КАЖДОЙ пересборке файлов в `public/mascot/`.

// anim (WebP) приоритетнее статичного спрайта. WebP сам зациклен (loop=0) — «дыхание»
// в этом режиме не нужно (персонаж и так двигается: уши/хвост/рот).
const src = computed(() =>
  props.anim
    ? `/mascot/anim/${props.anim}.webp?v=${ART_VERSION}`
    : `/mascot/${props.sprite}.webp?v=${ART_VERSION}`)
// Предзагрузка — ПО ОБЛАСТИ, которую назвал вызывающий (см. config/mascot.js):
//   • `scope="login"` → покой и жест с глазами (три файла);
//   • `scope="chat"` (по умолчанию) → состояния чата Вектора;
//   • режим спрайтов (`sprite` без `anim`) → эмоции дашборда, анимации там не нужны.
// Раньше звалось и то и другое сразу, на каждом экране с маскотом: вход тянул 2.3 МБ
// анимаций чата и восемь спрайтов дашборда, которых там нет.
//
// ⚠️ Область задаёт ВЫЗЫВАЮЩИЙ, а не догадка по имени анимации: состояние `idle` есть и
// на входе, и в чате, и любое «определим по props.anim» ошибётся ровно на нём — чат
// остался бы без предзагруженных `thinking`/`speaking`, то есть с паузой на первом же
// вопросе. Это ровно тот случай, где угадывание дешевле выглядит и дороже стоит.
onMounted(() => {
  if (props.anim) preloadAnims(props.scope)
  else preloadMascots()
})
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
