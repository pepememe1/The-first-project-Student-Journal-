<script setup>
// StampEgg — штамп Papers, Please. Ложится в СЛУЧАЙНОЕ место карточки профиля: своей,
// чужой, открытой из группы или из личного чата — везде, где показывают человека.
//
// 🔥 ПОЧЕМУ ШТАМПА НЕ БЫЛО ВИДНО (23.08.2026). Проверка `if (easter.inPage.papers…)`
// стояла ОДИН раз, в момент создания компонента. А бросок делает сервер, и ответ
// приходит позже — то есть условие было ложным ВСЕГДА. Подтверждение при уходе честно
// говорило «где-то тут штамп», потому что стор про него знал; не знала разметка.
// ⚠️ Правило общее: состояние, которое приходит по сети, проверяется НАБЛЮДЕНИЕМ, а не
// однократным `if` в setup. Ошибка тихая — ни исключения, ни следа в консоли.
//
// ⚠️ Слой прозрачен для мыши, право на клик выдано только самому штампу: иначе он
// накрывает собой кнопки карточки, и это выглядит не как пасхалка, а как поломка.
import { ref, watch, onBeforeUnmount } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'

const easter = useEasterStore()
const stamp = ref(null)
let timer = 0

function place() {
  if (stamp.value) return
  stamp.value = {
    // Что написано на штампе — принято или отказано — значения не имеет: ачивку дают
    // за то, что его НАШЛИ. Поэтому просто монетка.
    src: Math.random() < 0.5 ? '/easter/img/stamp-ok.webp' : '/easter/img/stamp-no.webp',
    rot: (Math.random() * 26 - 13).toFixed(1),
    left: `${14 + Math.random() * 62}%`,
    top: `${18 + Math.random() * 58}%`,
    shown: false,
    hit: false,
  }
  //Кадр на «прилёт»: штамп должен ПРИЛОЖИТЬСЯ на глазах, а не оказаться на месте сразу.
  requestAnimationFrame(() => { if (stamp.value) stamp.value.shown = true })
}

watch(() => easter.inPage.papers_please_stamp, (on) => { if (on) place() }, { immediate: true })

function hit() {
  if (!stamp.value || stamp.value.hit) return
  stamp.value.hit = true
  easter.claim('papers_please_stamp')
  timer = setTimeout(() => {
    stamp.value = null
    easter.closeInPage('papers_please_stamp')
  }, 1400)
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div v-if="stamp" class="pointer-events-none absolute inset-0 z-40 overflow-hidden">
    <button type="button" aria-label="Штамп"
            class="gb-stamp pointer-events-auto absolute w-[22%] min-w-[110px] border-0 bg-transparent p-0"
            :style="{ left: stamp.left, top: stamp.top,
                      transform: `rotate(${stamp.rot}deg) scale(${stamp.hit ? 1.12 : stamp.shown ? 1 : 2.4})`,
                      opacity: stamp.shown ? 1 : 0 }"
            :disabled="stamp.hit" @click.stop="hit">
      <img :src="stamp.src" alt="" class="block w-full drop-shadow-lg" style="image-rendering:pixelated" />
    </button>
  </div>
</template>

<style scoped>
.gb-stamp {
  cursor: pointer;
  transition: transform .18s cubic-bezier(.3, 1.6, .5, 1), opacity .12s;
}
@media (prefers-reduced-motion: reduce) { .gb-stamp { transition: none } }
</style>
