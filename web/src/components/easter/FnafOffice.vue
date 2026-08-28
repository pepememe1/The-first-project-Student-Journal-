<script setup>
// FNAF: вход между 00:00 и 06:00, 1/87. Ночная смена поверх всего журнала.
//
// ━━ ПРАВИЛА ИГРЫ (Влад, 25.08.2026) ━━
//   зашёл ночью   → офис;
//   нажал ноутбук → гуляешь по сайту, внизу висит «в офис»;
//   пришёл к Вектору (вкладка ИЛИ шторка) → его нет на месте;
//   написал вопрос → вернулся сразу в обоих местах;
//   вернул три раза → на четвёртый не приманить: скример и ачивка.
//
// 🔥 ЭТА СЦЕНА — ЕДИНСТВЕННАЯ, КОТОРАЯ НЕ МЕШАЕТ ХОДИТЬ ПО САЙТУ, и это не поблажка,
// а условие её существования. До правки продукт вёл себя прямо противоположно замыслу:
// Влад открыл ноутбук, пошёл к Вектору, получил «точно уйти?», подтвердил — и пасхалка
// закрылась. То есть единственное действие, которого игра от человека ждёт, она же и
// запрещала. Исключение живёт в `easterEggs.pending`, а состояние ночи — в сторе, а не
// здесь: кнопка «в офис» и пропажа Вектора обязаны переживать смену вкладки.
//
// ⚠️ Проём измерен ПО КАРТИНКЕ (x 68…89.5%, y 9…82%), а не на глаз. Контейнер шире
// проёма влево: правый край двери режет Вектора, пока он в темноте, а выйдя, он стоит
// в комнате целиком.
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const inOffice = ref(true)
const boo = ref(false)
const out = ref(false)
let amb = [], hideTimer = null, scareTimer = null

// Сколько даётся на вопрос, пока Вектора нет. Минута — не «сложность», а запас: человек
// в этот момент ещё соображает, куда делся маскот.
const ANSWER_MS = 60000
// Пауза между возвращением Вектора и его следующей пропажей. Короткая намеренно: игра
// должна идти, а не ждать. Но не мгновенная — иначе ответ Вектора не успевают прочитать.
const NEXT_HIDE_MS = 14000

onMounted(() => {
  amb = ['/easter/snd/office-amb-1.m4a', '/easter/snd/office-amb-2.m4a'].map((src) => {
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
onBeforeUnmount(() => {
  amb.forEach((a) => a.pause())
  clearTimeout(hideTimer); clearTimeout(scareTimer)
  easter.fnafEnd()
})

function duck(q) { amb.forEach((a) => { a.volume = q ? 0.04 : 0.35 }) }

/**
 * Следим за пропажей Вектора ИЗ СТОРА, а не командуем ею отсюда.
 *
 * ⚠️ Вернуть его может и вкладка «ИИ Помощник», и боковая шторка — два места, о которых
 * сцена ничего не знает и знать не должна. Поэтому сцена только РЕАГИРУЕТ: пропал —
 * завожу отсчёт до скримера; вернулся — глушу отсчёт и через паузу прячу снова.
 */
watch(() => easter.fnaf.hidden, (hidden) => {
  clearTimeout(hideTimer); clearTimeout(scareTimer)
  if (!easter.fnaf.roaming) return
  if (hidden) {
    scareTimer = setTimeout(scare, ANSWER_MS)
  } else {
    hideTimer = setTimeout(() => easter.fnafHide(), NEXT_HIDE_MS)
  }
})

// Приманить больше нельзя — пугаем немедленно, не дожидаясь отсчёта.
watch(() => easter.fnaf.doomed, (v) => { if (v) scare() })

function openJournal() {
  inOffice.value = false
  duck(true)
  easter.fnafRoam(true)          //Вектор пропадает в обоих местах сразу
}

function backToOffice() {
  clearTimeout(hideTimer); clearTimeout(scareTimer)
  inOffice.value = true
  duck(false)
  //Вернулся в офис — Вектор на месте: игра идёт, только пока человек гуляет по сайту.
  easter.fnafRoam(false)
}

async function scare() {
  clearTimeout(hideTimer); clearTimeout(scareTimer)
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
  easter.fnafEnd()
  emit('close')
}
</script>

<template>
  <div v-if="inOffice" class="fixed inset-0 z-[94] bg-black bg-cover bg-center bg-no-repeat"
       style="background-image:url(/easter/img/office.webp)">
    <!-- ⚠️ ХИТБОКС НОУТБУКА БЕЗ ОБВОДКИ (просьба Влада): пунктирная рамка поверх
         фотографии офиса читалась как элемент интерфейса и ломала погружение —
         единственное, ради чего эта сцена и сделана. Область осталась той же,
         подсказка — курсор и `title`; нашедший ночной офис доведёт мышь до ноутбука. -->
    <button type="button" @click="openJournal" aria-label="Открыть ноутбук"
            title="Открыть ноутбук"
            class="absolute left-[52%] top-[53%] h-[31%] w-[19%] cursor-pointer bg-transparent
                   focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#ffd98a]"></button>

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

  <!-- Кнопка возврата висит поверх ЛЮБОЙ страницы: сцена живёт в оболочке, а не внутри
       маршрута, поэтому переход между вкладками её не размонтирует. -->
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
