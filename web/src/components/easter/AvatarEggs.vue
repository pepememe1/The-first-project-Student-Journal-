<script setup>
// AvatarEggs — две пасхалки, живущие НА АВАТАРКЕ в панели пользователя.
//
// Они не оверлеи и не могут ими быть: обе меняют постоянный элемент интерфейса, а не
// накрывают экран. Поэтому компонент кладётся рядом с аватаркой и рисует поверх неё.
//
//   Detroit — LED-кольцо ВМЕСТО кружка статуса. Выпадает по шансу при входе, цвет
//             зависит от ситуации: синий — всё сдано, жёлтый — есть задачи, красный
//             мигающий — дедлайн близко.
//   DOOM    — состояние по среднему баллу, от двойки до пятёрки. ⚠️ Ачивка даётся за
//             САМ ФАКТ выпадения, а не за балл: оценка лишь определяет, что показать.
//             Крови и синяков на лице нет и не будет — только рамка и свечение.
//
// ⚠️ Лучи на пятёрке НЕЛЬЗЯ класть внутрь аватарки с z-index:-1 — они уедут за
// непрозрачный фон сайдбара и не будут видны вовсе (проверено на стенде). Поэтому они
// соседний слой, а аватарка поднята над ними.
//
// ⚠️ Вращение задаётся ТОЛЬКО через rotate, а центрирование — через margin: @keyframes
// с transform заменяет весь transform целиком, и центрирующий translate стирается —
// лучи прыгают на старте и возвращаются в конце.
import { computed, onMounted, watch } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'

const props = defineProps({
  //Средний балл человека. Пусто/0 — DOOM не показываем: выдумывать состояние не из чего.
  average: { type: Number, default: 0 },
})

const easter = useEasterStore()

const led = computed(() => !!easter.inPage.detroit_led)
const doom = computed(() => !!easter.inPage.doom_avatar)

// Цвет кольца по ситуации. Порог тот же, что уже красит продукт, второго набора не заводим.
const ledColor = computed(() => (props.average >= 4 ? '#2b8cff'
  : props.average >= 3 ? '#e0a72b' : '#e04b3c'))
const ledBlink = computed(() => props.average > 0 && props.average < 3)

const doomColor = computed(() => (props.average >= 4.5 ? '#e8b923'
  : props.average >= 3.5 ? '#4fa87a'
  : props.average >= 2.5 ? '#b8860b' : '#c0392b'))
const doomRays = computed(() => doom.value && props.average >= 4.5)

// Ачивку закрываем, как только показали: обе сцены живут на аватарке и «доиграть» их
// нельзя — человек просто уходит с экрана.
//
// ⚠️ Уже полученную не переспрашиваем. Метка висит на аватарке ПОСТОЯННО, а сторож
// стоит на `inPage` с `deep: true` — то есть без этой проверки каждое изменение любой
// пасхалки в странице слало бы на сервер ещё один заведомо бесполезный `claim`. На
// одноядерном VPS это не «лишний байт», а лишний поход в базу на каждый чих.
// ⚠️ Пустой `owned` (список ещё не приехал) означает «не получена» — и это правильная
// сторона ошибки: лучше один лишний запрос, чем незакрытая находка.
function claimOnce() {
  if (led.value && !easter.owned.has('detroit_led')) easter.claim('detroit_led')
  if (doom.value && !easter.owned.has('doom_hud_face')) easter.claim('doom_avatar')
}
onMounted(claimOnce)
watch(() => easter.inPage, claimOnce, { deep: true })
</script>

<template>
  <!-- Кольцо Detroit ВМЕСТО кружка статуса: сам кружок прячет родитель, когда led=true -->
  <!-- Кольцо стоит НА МЕСТЕ кружка статуса, значит и слой у него тот же (z-20):
       оно не декорация поверх лица, а замена элемента интерфейса. -->
  <span v-if="led" class="pointer-events-none absolute -bottom-1 -right-1 z-20 size-[15px] rounded-full"
        :class="ledBlink ? 'gb-led-blink' : ''"
        :style="{ border: `3px solid ${ledColor}`, boxShadow: `0 0 9px ${ledColor}` }"></span>

  <!-- ⚠️ Свечение и лучи — ПОД аватаркой (z-0). Они обрамляют лицо, а не закрывают его. -->
  <span v-if="doom" class="pointer-events-none absolute inset-0 z-0 rounded-full transition-shadow duration-500"
        :style="{ boxShadow: `0 0 0 3px ${doomColor}88` }"></span>

  <span v-if="doomRays" class="gb-doom-rays pointer-events-none absolute left-1/2 top-1/2 z-0"></span>
</template>

<style scoped>
.gb-led-blink { animation: gb-led .85s steps(2) infinite; }
@keyframes gb-led { 50% { opacity: .25 } }

/* Лучи: конический градиент даёт сами лучи, радиальная маска гасит их к краю —
   у основания насыщенно, дальше прозрачно. */
.gb-doom-rays {
  width: 104px; height: 104px; margin-left: -52px; margin-top: -52px;
  background: conic-gradient(
    transparent 0deg, #ffd257 3deg, #ffb300 8deg, transparent 13deg,
    transparent 22.5deg, #ffd257 25.5deg, #ffb300 30.5deg, transparent 35.5deg,
    transparent 45deg, #ffd257 48deg, #ffb300 53deg, transparent 58deg,
    transparent 67.5deg, #ffd257 70.5deg, #ffb300 75.5deg, transparent 80.5deg,
    transparent 90deg, #ffd257 93deg, #ffb300 98deg, transparent 103deg,
    transparent 112.5deg, #ffd257 115.5deg, #ffb300 120.5deg, transparent 125.5deg,
    transparent 135deg, #ffd257 138deg, #ffb300 143deg, transparent 148deg,
    transparent 157.5deg, #ffd257 160.5deg, #ffb300 165.5deg, transparent 170.5deg,
    transparent 180deg, #ffd257 183deg, #ffb300 188deg, transparent 193deg,
    transparent 202.5deg, #ffd257 205.5deg, #ffb300 210.5deg, transparent 215.5deg,
    transparent 225deg, #ffd257 228deg, #ffb300 233deg, transparent 238deg,
    transparent 247.5deg, #ffd257 250.5deg, #ffb300 255.5deg, transparent 260.5deg,
    transparent 270deg, #ffd257 273deg, #ffb300 278deg, transparent 283deg,
    transparent 292.5deg, #ffd257 295.5deg, #ffb300 300.5deg, transparent 305.5deg,
    transparent 315deg, #ffd257 318deg, #ffb300 323deg, transparent 328deg,
    transparent 337.5deg, #ffd257 340.5deg, #ffb300 345.5deg, transparent 350.5deg);
  -webkit-mask: radial-gradient(circle, #000 13%, rgba(0,0,0,.85) 26%, rgba(0,0,0,.3) 48%, transparent 68%);
  mask: radial-gradient(circle, #000 13%, rgba(0,0,0,.85) 26%, rgba(0,0,0,.3) 48%, transparent 68%);
  filter: drop-shadow(0 0 8px rgba(255,190,50,.85));
  animation: gb-rays 14s linear infinite;
}
@keyframes gb-rays { to { rotate: 360deg } }
@media (prefers-reduced-motion: reduce) {
  .gb-doom-rays, .gb-led-blink { animation: none }
}
</style>
