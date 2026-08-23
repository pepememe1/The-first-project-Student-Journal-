<script setup>
// Hotline Miami: вход в «Сообщения» и выход из беседы — две разные реплики.
//
// Собрано ПО РЕФЕРЕНСУ: неоновый фильтр, снизу выезжает чёрная полоса, справа
// наклонённый переливающийся четырёхугольник с головой Вектора.
//
// ⚠️ Голова лежит ОТДЕЛЬНЫМ слоем поверх четырёхугольника. Положи её внутрь — и она
// перекрасится вместе с фоном: перелив сделан через hue-rotate, а он красит всех
// потомков. Качается она медленно и своей анимацией, независимо от фона.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const props = defineProps({ variant: { type: String, default: 'enter' } })
const emit = defineEmits(['close'])
const easter = useEasterStore()

const TEXTS = {
  enter: 'Тебе действительно нравится писать людям сообщения, не так ли?',
  leave: 'Чувак, эта беседа просто отстой. Мне не интересны эти люди.',
}

const filter = ref(0), inPlace = ref(false), text = ref(''), step = ref(0)
let timers = []

// ⚠️ АЧИВКУ ЗАКРЫВАЕМ СРАЗУ, а не в конце сцены (просьба Влада 23.08.2026). Сцена идёт
// несколько секунд, а человек в мессенджере в этот момент уже кликает по чатам — уйдёт
// раньше конца, и награда пропадёт, хотя пасхалку он видел. Условие ачивки — «попалась»,
// а не «досмотрел до конца»: досматривать никто никому не обещал.
onMounted(() => {
  easter.claim('hotline_miami')
  requestAnimationFrame(() => { filter.value = 1 })
  timers.push(setTimeout(() => { filter.value = 0.32; inPlace.value = true }, 1300))
})
onBeforeUnmount(() => timers.forEach(clearTimeout))

async function onClick() {
  if (!inPlace.value) return           // пока не выехало — не скипается
  if (step.value === 0) {
    step.value = 1
    const full = TEXTS[props.variant] || TEXTS.enter
    for (let i = 1; i <= full.length; i++) {
      text.value = full.slice(0, i)
      await new Promise((r) => setTimeout(r, 30))
    }
  } else if (step.value === 1) {
    step.value = 2
    inPlace.value = false
    filter.value = 0
    setTimeout(() => emit('close'), 1200)   // ачивка уже выдана при показе, см. выше
  }
}
</script>

<template>
  <div class="fixed inset-0 z-[93]" @click="onClick">
    <div class="absolute inset-0 transition-opacity duration-300"
         style="background:linear-gradient(120deg,#ffdf3d55,#ff2fb955);mix-blend-mode:hard-light"
         :style="{ opacity: filter }"></div>

    <!-- ⚠️ ФОРМА — НАКЛОННЫЙ ЧЕТЫРЁХУГОЛЬНИК СПРАВА, а не полоса во всю ширину.
         Промежуточная версия растянула его горизонтально через весь экран, и от кадра
         Hotline не осталось ничего — получилась просто цветная лента. Нужна прежняя
         косая фигура, только КРУПНЕЕ: она уходит за верхний, нижний и правый край, и
         поэтому пустых углов больше нет.
         ⚠️ Выход за края обязателен именно с трёх сторон: скос сдвигает верхнюю и нижнюю
         грани по горизонтали, и фигура, обрезанная ровно по границе окна, оставляла бы
         у краёв треугольные прорехи — то самое, из-за чего кадр читался как
         незагрузившаяся картинка.
         ⚠️ Слой НИЖНИЙ (z-0): чёрная полоса с репликой ложится поверх. -->
    <div class="quad absolute -top-[6%] -right-[8%] z-0 h-[86%] w-[46%] transition-transform duration-500"
         :style="{ transform: inPlace ? 'skewX(-7deg)' : 'skewX(-7deg) translateX(140%)' }"></div>

    <div class="absolute inset-x-0 bottom-0 z-10 h-[31%] bg-[#0a0a0a] transition-transform duration-500"
         :style="{ transform: inPlace ? 'none' : 'translateY(100%)' }"></div>

    <img src="/easter/img/head.webp" alt=""
         class="absolute right-[9%] top-[13%] z-[5] w-[24%] transition-transform duration-500"
         :class="inPlace ? 'sway' : ''"
         :style="{ transform: inPlace ? 'none' : 'translateX(140%)',
                   filter: 'drop-shadow(0 6px 14px rgba(0,0,0,.5))' }" />

    <!-- Реплика и подсказка — поверх чёрной полосы, иначе она их накроет. -->
    <p v-if="step >= 1" class="px absolute bottom-[17%] left-[5%] right-[38%] z-20 text-[11px] leading-[1.9]"
       style="color:#ffe27a">{{ text }}</p>
    <p v-else-if="inPlace" class="absolute bottom-[5%] left-[5%] z-20 font-mono text-[9px]"
       style="color:#6d6a5f">кликните</p>
  </div>
</template>

<style scoped>
.quad { background: linear-gradient(150deg, #ffb01f, #ff2fb9); box-shadow: 0 0 26px #ff2fb977;
        animation: shimmer 3.4s linear infinite; }
@keyframes shimmer { to { filter: hue-rotate(360deg) } }
.sway { animation: sway 3.2s ease-in-out infinite; transform-origin: 50% 90%; }
@keyframes sway { 0%,100% { transform: rotate(-3.5deg) } 50% { transform: rotate(3.5deg) } }
.px { font-family: 'Press Start 2P', monospace; }
@media (prefers-reduced-motion: reduce) { .quad, .sway { animation: none } }
</style>
