<script setup>
// FNAF: вход между 00:00 и 06:00, 1/87. Офис — отдельная вкладка поверх кабинета.
//
// Ноутбук открывает журнал, кнопка внизу возвращает в офис. Дальше цикл: открыл
// «ИИ Помощник» — Вектора нет — минута на вопрос; спросил — вернулся, не спросил —
// вкладка сворачивается в офис, и он говорит «Бу-у-у-у-у». Мягко, без крика.
//
// ⚠️ Проём измерен ПО КАРТИНКЕ (x 68…89.5%, y 9…82%), а не на глаз. Контейнер шире
// проёма влево: правый край двери режет Вектора, пока он в темноте, а выйдя, он стоит
// в комнате целиком.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const inOffice = ref(true)
const boo = ref(false)
const out = ref(false)
let amb = [], timer = null

onMounted(() => {
  amb = ['/easter/snd/office-amb-1.mp4', '/easter/snd/office-amb-2.mp4'].map((src) => {
    const a = new Audio(src)
    a.volume = 0.35
    a.play().catch(() => {})
    // ⚠️ Хвост обрезаем: в одном из файлов в конце идёт речь. Зацикливаем первые 55% —
    // для ровного шума это безопасно, какой бы из двух ни оказался «говорящим».
    a.addEventListener('timeupdate', () => {
      if (a.duration && isFinite(a.duration) && a.currentTime > a.duration * 0.55) a.currentTime = 0
    })
    return a
  })
})
onBeforeUnmount(() => { amb.forEach((a) => a.pause()); clearTimeout(timer) })

function duck(q) { amb.forEach((a) => { a.volume = q ? 0.04 : 0.35 }) }

function openJournal() {
  inOffice.value = false
  duck(true)
  // В продукте — минута: столько даётся, чтобы задать Вектору вопрос.
  timer = setTimeout(scare, 60000)
}
function backToOffice() { clearTimeout(timer); inOffice.value = true; duck(false) }

async function scare() {
  inOffice.value = true
  duck(false)
  await new Promise((r) => setTimeout(r, 260))
  out.value = true
  await new Promise((r) => setTimeout(r, 560))
  boo.value = true
}
async function shoo() {
  boo.value = false
  out.value = false
  await new Promise((r) => setTimeout(r, 700))
  await easter.claim('fnaf_night_mode')
  emit('close')
}
</script>

<template>
  <div v-if="inOffice" class="fixed inset-0 z-[94] bg-black bg-cover bg-center bg-no-repeat"
       style="background-image:url(/easter/img/office.webp)">
    <button type="button" @click="openJournal" aria-label="Открыть журнал"
            class="absolute left-[52%] top-[53%] h-[31%] w-[19%] rounded border border-dashed"
            style="border-color:rgba(255,217,138,.3)"></button>

    <div class="pointer-events-none absolute left-[68%] top-[9%] h-[73%] w-[21.5%] overflow-hidden">
      <img src="/easter/img/boo.webp" alt=""
           class="absolute bottom-0 right-[2%] h-[76%] w-auto transition-transform duration-[600ms]"
           :style="{ transform: out ? 'translateX(0) scale(1)' : 'translateX(112%) scale(.92)',
                     transformOrigin: '100% 100%',
                     filter: 'drop-shadow(-8px 0 16px rgba(0,0,0,.7))' }" />
    </div>

    <div v-if="boo" class="px absolute right-[23%] top-[22%] rounded-xl bg-white px-3 py-2 text-[11px]"
         style="color:#15202b;box-shadow:0 4px 16px rgba(0,0,0,.5)">
      Бу-у-у-у-у
      <span class="absolute -right-1.5 top-[62%] h-0 w-0"
            style="border:7px solid transparent;border-left-color:#fff;border-right:0"></span>
    </div>

    <button v-if="out" type="button" @click="shoo" aria-label="Прогнать Вектора"
            class="absolute left-[70%] top-[9%] h-[73%] w-[20%]"></button>
  </div>

  <button v-else type="button" @click="backToOffice"
          class="fixed bottom-2 left-1/2 z-[94] -translate-x-1/2 rounded-md border px-4 py-1.5 font-mono text-[10.5px]
                 backdrop-blur-sm"
          style="background:rgba(10,14,18,.5);color:#dfe8ec;border-color:rgba(255,255,255,.18)">
    ▲ в офис
  </button>
</template>

<style scoped>
.px { font-family: 'Press Start 2P', monospace; line-height: 1.5; }
</style>
