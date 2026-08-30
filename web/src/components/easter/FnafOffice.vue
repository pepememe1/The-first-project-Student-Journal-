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

// ━━ ПОВОРОТ ЭКРАНА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Кадр офиса нарисован широким (office.webp — 1600x891, соотношение 1.80), а лежит под
// `bg-cover`. Замер на телефоне 360x740: видно 27 % ШИРИНЫ кадра, то есть три четверти
// сцены срезано — остаётся центральная колонка со столом, а ноутбук у края и вентилятор
// пропадают. Ноутбук при этом — единственная кнопка, ради которой сцена и существует.
// Поэтому на узком экране сперва просим повернуть, а на время смены держим ландшафт.
//
// ⚠️ ЗАМОК ОРИЕНТАЦИИ НЕЛЬЗЯ ПОСТАВИТЬ БЕЗ ПОЛНОЭКРАННОГО РЕЖИМА, а полноэкранный — без
// ЖЕСТА человека. Пасхалка же выпадает сама, на входе, без единого нажатия. Отсюда
// кнопка на заставке: она и есть тот жест. Без неё `lock()` отвергается браузером
// молча, и «замок» существовал бы только в наших словах.
// ⚠️ Настольный браузер не трогаем вовсе: `lock()` там не поддержан, а разворачивать
// окно человеку на весь экран ради пасхалки — наглость.
const NARROW_PX = 900
const needRotate = ref(false)     // показываем заставку «поверните экран»
const lockFailed = ref(false)     // замок не дали — значит ждём поворота руками
let fsEl = null

function isNarrow() { return window.innerWidth < NARROW_PX || window.innerHeight < NARROW_PX }
function isPortrait() { return window.innerHeight > window.innerWidth }

function updateGate() {
  // Заставка нужна только пока человек В ОФИСЕ: открыв ноутбук, он ходит по обычному
  // сайту, и требовать от него ландшафт там не за что.
  needRotate.value = inOffice.value && isNarrow() && isPortrait()
}

/** Полный экран + замок ландшафта. Зовётся ТОЛЬКО из обработчика нажатия. */
async function lockLandscape() {
  try {
    fsEl = document.documentElement
    if (fsEl.requestFullscreen) await fsEl.requestFullscreen({ navigationUI: 'hide' })
    await screen.orientation.lock('landscape')
    lockFailed.value = false
  } catch {
    // Не дали — не беда и не повод прятать сцену: просим повернуть руками и живём
    // дальше. Молчаливый провал здесь честнее исключения: пасхалка не обязана падать
    // из-за того, что браузер не разрешил замок.
    lockFailed.value = true
    // ⚠️ И полноэкранный режим тогда ОТДАЁМ обратно. Он брался не сам по себе, а как
    // условие замка (без него `lock()` отвергают); замка нет — значит мы забрали у
    // человека весь экран ни за что, да ещё и не спросив. Проверено на настольном
    // Chromium: полный экран даётся, замок нет — ровно этот случай.
    try { if (document.fullscreenElement) await document.exitFullscreen() } catch { /* уже вышли */ }
  }
  updateGate()
}

function releaseLock() {
  try { screen.orientation.unlock() } catch { /* не был поставлен — нечего снимать */ }
  try { if (document.fullscreenElement) document.exitFullscreen() } catch { /* уже вышли */ }
  fsEl = null
}

// Ушёл в журнал и вернулся — заставку надо пересчитать: пока он ходил по сайту, телефон
// мог оказаться в портрете (замок не дали), и офис снова показался бы обрезанным.
watch(inOffice, updateGate)

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
  updateGate()
  window.addEventListener('resize', updateGate)
  // `orientationchange` — на случай поворота при неизменившемся размере окна (бывает в
  // WebView). Дублирует resize намеренно: пропущенный поворот оставит заставку висеть
  // поверх уже правильно повёрнутого экрана, и это читается как зависание.
  window.addEventListener('orientationchange', updateGate)
})
onBeforeUnmount(() => {
  amb.forEach((a) => a.pause())
  clearTimeout(hideTimer); clearTimeout(scareTimer)
  window.removeEventListener('resize', updateGate)
  window.removeEventListener('orientationchange', updateGate)
  // ⚠️ Замок снимаем ВСЕГДА и здесь, а не в `shoo()`: сцена закрывается ещё и Esc'ом,
  // и уходом со страницы. Оставленный замок означал бы телефон, застрявший в ландшафте
  // до перезагрузки вкладки, — цена ошибки несоизмерима с пасхалкой.
  releaseLock()
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
  <!-- Заставка «поверните экран». Стоит ПЕРЕД офисом и перекрывает его (z выше): пока
       телефон в портрете, показывать обрезанный на три четверти кадр незачем — человек
       увидит стол без ноутбука и решит, что пасхалка сломана. -->
  <div v-if="needRotate" class="fixed inset-0 z-[95] grid place-items-center bg-black px-6 text-center">
    <div>
      <!-- Значок телефона, доворачивающийся в ландшафт: он объясняет просьбу быстрее
           текста, а на этой сцене текста и так минимум. -->
      <div class="mx-auto mb-6 h-12 w-20 rounded-[7px] border-2 gb-turn"
           style="border-color:#dfe8ec"></div>
      <p class="px text-[13px] leading-relaxed" style="color:#dfe8ec">Поверните экран</p>
      <p class="px mt-3 text-[9px] leading-relaxed" style="color:#7f8c93">
        ночная смена идёт в&nbsp;ландшафте
      </p>
      <button type="button" @click="lockLandscape"
              class="px mt-7 rounded-md border px-5 py-2.5 text-[10px]"
              style="background:rgba(255,255,255,.06);color:#dfe8ec;border-color:rgba(255,255,255,.25)">
        {{ lockFailed ? 'жду поворота' : 'заступить на смену' }}
      </button>
      <!-- Говорим правду, когда замок не дали: иначе человек крутит телефон и не
           понимает, почему «не поворачивается» — при том что это МЫ не смогли. -->
      <p v-if="lockFailed" class="px mx-auto mt-4 max-w-[15rem] text-[8px] leading-relaxed"
         style="color:#6d6a5f">
        браузер не дал повернуть сам — поверните телефон рукой
      </p>
    </div>
  </div>

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

/* Телефон, доворачивающийся в ландшафт и обратно. Пауза в конце цикла нужна, иначе
   значок «дёргается» без передышки и читается как ошибка отрисовки, а не как просьба. */
.gb-turn { animation: gb-turn 2.6s ease-in-out infinite; }
@keyframes gb-turn {
  0%, 25%   { transform: rotate(90deg) }
  45%, 100% { transform: rotate(0deg) }
}
/* Тем, кто просил уменьшить анимацию, показываем значок сразу в конечном положении —
   просьба «поверните» остаётся понятной и без движения. */
@media (prefers-reduced-motion: reduce) {
  .gb-turn { animation: none; }
}
</style>
