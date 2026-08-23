<script setup>
// JournalEggs — три пасхалки журнала оценок: кубик Isaac, счётчик ULTRAKILL и
// внутренний голос Disco Elysium.
//
// ━━ ПОЧЕМУ ОДИН КОМПОНЕНТ, А НЕ ТРИ ━━
// Все три живут на ОДНОЙ странице и делят её ячейки оценок. Разложи их по трём файлам,
// и каждый будет по-своему искать `[data-egg-grade]`, по-своему прибирать за собой, и
// однажды кубик испортит клетку, на которую в этот момент смотрит голос.
//
// ━━ ЧТО СЧИТАЕТ СЕРВЕР ━━
// Всё, что можно подделать: и «отличник ли», и оба броска. Клиент получает готовый
// ответ `GET /web/easter-eggs/journal` и только рисует.
//
// ⚠️ Слой НЕ перехватывает мышь (`pointer-events:none`), а право на клик выдаётся
// точечно самому кубику. Иначе подсказки на клетках и кнопки под слоем перестают
// работать — на это уже наступали на стенде.
import { onMounted, onBeforeUnmount, ref, computed, nextTick } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'

const props = defineProps({
  // Средний балл — им выбирается пул реплик Disco Elysium. Ноль означает «оценок нет»:
  // голос тогда берёт самый нижний пул, но выпасть ему всё равно почти не на чем.
  average: { type: Number, default: 0 },
})

const easter = useEasterStore()
const isaac = computed(() => !!easter.inPage.binding_of_isaac_d6)
const ultra = computed(() => !!easter.inPage.ultrakill_rank)
const disco = computed(() => !!easter.inPage.disco_elysium_voice)

// ── ULTRAKILL ──────────────────────────────────────────────────────────────
const ultraIn = ref(false)
const ultraBar = ref(0)

// ── Isaac ──────────────────────────────────────────────────────────────────
const ITEMS = Array.from({ length: 10 }, (_, i) => `/easter/img/item-${i + 1}.png`)
const dicePlayed = ref(false)
const diceGone = ref(false)
const tears = ref([])
let rollTimer = 0
const cells = () => [...document.querySelectorAll('[data-egg-grade]')]
const pick = (a) => a[Math.floor(Math.random() * a.length)]

function paintCell(td) {
  td.innerHTML = `<img src="${pick(ITEMS)}" alt="" style="width:19px;image-rendering:pixelated;`
    + `vertical-align:middle;display:inline-block">`
}

async function throwDice() {
  if (dicePlayed.value) return
  dicePlayed.value = true
  const list = cells()
  // Настоящий балл не теряем: убираем его в подсказку, а не затираем насовсем.
  list.forEach((td) => { td.dataset.real = td.textContent.trim() })
  rollTimer = setInterval(() => list.forEach(paintCell), 70)
  await new Promise((r) => setTimeout(r, 1150))
  clearInterval(rollTimer); rollTimer = 0
  list.forEach((td) => {
    td.title = `Настоящий балл: ${td.dataset.real}`
    paintCell(td)
  })
  diceGone.value = true
  tears.value = Array.from({ length: 16 }, () => ({
    left: `${Math.random() * 100}%`,
    dur: `${1 + Math.random() * 1.2}s`,
    delay: `${Math.random() * 0.6}s`,
  }))
  setTimeout(() => easter.claim('binding_of_isaac_d6'), 1300)
}

// ── Disco Elysium ──────────────────────────────────────────────────────────
// Реплики разложены по уровню успеваемости: у слабого балла одни голоса, у крепкого
// другие. Пул выбирается по среднему, конкретная реплика — случайно.
const DISCO = [
  [['ЛОГИКА — Провал', 'Вы абсолютно уверены, что 2 + 2 = 5. Преподаватель просто не дорос до вашей математики.'],
   ['ЭЛЕКТРОХИМИЯ — Успех', 'А что если не идти на пересдачу? Что если вообще никуда не идти? Подумай, как это будет свободно.'],
   ['ВНУТРЕННЯЯ ИМПЕРИЯ', 'Эта двойка смотрит на тебя. Она знает про тебя что-то, чего не знаешь ты.'],
   ['РАССУДОК — Провал', 'Ну да, можно оставить и двойку. Но где ты окажешься потом, с таким-то отношением?'],
   ['БОЛЕВОЙ ПОРОГ', 'Не так уж и больно. Больно будет в сессию, а сейчас — просто цифра.'],
   ['ВОЛЯ К ЖИЗНИ', 'Одна пересдача. Всего одна. Ты справлялся и с худшим — например, с прошлой пересдачей.']],
  [['ДРАМА — Средний успех', 'Скажите, что болели. Нет, лучше — что помогали бабушке. Сир, вы неубедительны, но вам поверят.'],
   ['ЭНЦИКЛОПЕДИЯ', 'Тройка — самая устойчивая оценка в системе. Она не требует ни оправданий, ни объяснений.'],
   ['СИЛА ВОЛИ — Провал', 'Можно было выучить. Времени было ровно столько же, сколько у отличников.'],
   ['ЛОГИКА', 'Тройка — это ровно середина. Отсюда одинаково близко и до пятёрки, и до пересдачи.'],
   ['ПОЛУСВЕТ', 'Никто не помнит, кто получил тройку. В этом и утешение, и приговор.']],
  [['САМООБЛАДАНИЕ — Успех', 'Четвёрка. Достойно. Не показывайте виду, что рассчитывали на большее.'],
   ['ЭСПРИ ДЕ КОР', 'Где-то в другом кабинете преподаватель ставит такую же четвёрку и думает: «а мог бы и на пять».'],
   ['ВОСПРИЯТИЕ', 'Вы замечаете: до пятёрки не хватило одной практики. Той самой, что вы «сдадите завтра».'],
   ['ДРАМА', 'Четвёрка — оценка человека, который всё понял, но поздно. Сир, это почти комплимент.']],
  [['АВТОРИТЕТ — Успех', 'Пятёрка. Теперь важно не подать виду, что вам это тоже далось трудом.'],
   ['ВНУТРЕННЯЯ ИМПЕРИЯ', 'Ты держишь идеальный балл. Ты понимаешь, что это значит? Теперь его можно только потерять.'],
   ['ЛОГИКА — Успех', 'Средний растёт. Система работает. Вы, кажется, тоже.'],
   ['ЭЛЕКТРОХИМИЯ — Провал', 'Отпразднуем? Одна ночь без сна ничего не изменит. Кроме завтрашней практики.'],
   ['ЭНЦИКЛОПЕДИЯ', 'Пятёрка по этому предмету у группы третья за семестр. Вы в редкой компании.']],
]
const voice = ref(null)
const voiceIn = ref(false)

/**
 * Голос выходит САМ, внизу экрана, и висит, пока по нему не кликнут.
 *
 * ⚠️ Раньше он ждал наведения на клетку оценки — и это было ошибкой дважды. Во-первых,
 * догадаться было не о чем: пасхалка «сработала», а на экране пусто. Во-вторых, уход со
 * страницы честно спрашивал «точно уйти?» про то, чего не видно, и это читалось как
 * сбой продукта, а не как находка.
 *
 * ⚠️ Ачивку даёт КЛИК, а не показ. Реплика — это голос, к которому предлагают
 * прислушаться; сама ачивка так и называется. Выдать её за то, что человек просто
 * посмотрел на экран, значит обессмыслить и то и другое.
 */
function speak() {
  const avg = props.average
  const level = avg >= 4.5 ? 3 : avg >= 3.5 ? 2 : avg >= 2.5 ? 1 : 0
  const [skill, line] = pick(DISCO[level])
  voice.value = { skill, line }
  nextTick(() => { voiceIn.value = true })
}

function heedVoice() {
  if (!voice.value) return
  easter.claim('disco_elysium_voice')
  voiceIn.value = false
  setTimeout(() => { voice.value = null; easter.closeInPage('disco_elysium_voice') }, 320)
}

onMounted(async () => {
  if (ultra.value) {
    requestAnimationFrame(() => { ultraIn.value = true })
    setTimeout(() => { ultraBar.value = 78 }, 300)
    setTimeout(() => easter.claim('ultrakill_rank'), 1800)
  }
  //Небольшая пауза перед голосом — он должен ПОЯВИТЬСЯ на глазах, а не оказаться на
  //экране сразу вместе со страницей: во втором случае его принимают за часть интерфейса.
  if (disco.value) { await new Promise((r) => setTimeout(r, 1200)); speak() }
})

onBeforeUnmount(() => {
  if (rollTimer) clearInterval(rollTimer)
})
</script>

<template>
  <!-- aria-hidden тут НЕЛЬЗЯ: внутри живая кнопка кубика, а спрятанный от
       читалки экрана интерактивный элемент — это недоступная кнопка. -->
  <div class="pointer-events-none absolute inset-0 z-20 overflow-hidden">
    <!-- Кубик D6: единственный элемент слоя, которому разрешена мышь -->
    <button v-if="isaac && !diceGone" type="button" aria-label="Бросить D6"
            class="gb-d6 pointer-events-auto absolute right-4 top-3 size-[34px] border-0 p-0"
            :disabled="dicePlayed" @click="throwDice"></button>

    <span v-for="(t, i) in tears" :key="i" class="gb-tear absolute w-[3px] rounded-sm"
          :style="{ left: t.left, animationDuration: t.dur, animationDelay: t.delay }"></span>

    <!-- ULTRAKILL: плашка развёрнута НАСТОЯЩЕЙ перспективой (perspective + rotateY),
         а не плоским скосом — при скосе текст остаётся прямым и «смотрит» не туда. -->
    <div v-if="ultra" class="gb-uk absolute right-4 top-[8%] w-[min(27%,240px)] px-3.5 pb-3.5 pt-3"
         :class="ultraIn ? 'gb-uk-in' : ''">
      <div class="gb-uk-title">ULTRAKILL</div>
      <div class="my-2 h-[7px] overflow-hidden bg-black">
        <div class="h-full bg-white transition-[width] duration-1000" :style="{ width: ultraBar + '%' }"></div>
      </div>
      <div class="font-mono text-[clamp(8px,1.05vw,12px)] font-bold leading-[1.75]">
        <div class="text-white">+ ПЯТЁРКА</div>
        <div style="color:#4fd6ff">+ ПОСЕЩАЕМОСТЬ</div>
        <div style="color:#4fd6ff">+ СДАНО В СРОК</div>
        <div style="color:#ff5b4a">+ БЕЗ ПЕРЕСДАЧ</div>
        <div style="color:#ffb01f">+ ИДЕАЛЬНЫЙ СЕМЕСТР</div>
      </div>
      <div class="mt-2.5 flex items-baseline gap-[7px]">
        <span class="font-mono text-[clamp(7px,.9vw,11px)] font-bold text-white">MULTIPLIER</span>
        <span class="gb-uk-mul font-mono text-[clamp(13px,1.8vw,20px)] font-bold">x3.00</span>
      </div>
      <div class="mt-[7px] py-[3px] text-center font-mono text-[clamp(7px,.9vw,11px)] font-bold"
           style="background:#ffb01f;color:#1a1206">FRESH: 1.50x</div>
    </div>

    <!-- Внутренний голос: только владельцу дневника, в базе ничего не остаётся -->
    <!-- Голос ЛИПНЕТ К НИЗУ ОКНА (fixed), а не к низу карточки: журнал длинный, и у
         его подвала человека в этот момент обычно нет — реплику он бы не увидел. -->
    <button v-if="voice" type="button" @click="heedVoice"
            class="pointer-events-auto fixed inset-x-4 bottom-4 z-[88] mx-auto block max-w-xl rounded-[5px]
                   border px-4 py-3 text-left transition duration-300 hover:brightness-125"
            :class="voiceIn ? 'translate-y-0 opacity-100' : 'translate-y-2.5 opacity-0'"
            style="background:rgba(12,16,22,.96);border-color:#3c4f63">
      <div class="font-mono text-[11px] font-bold tracking-wide" style="color:#d9a441">{{ voice.skill }}</div>
      <div class="mt-1.5 text-[12.5px] leading-normal" style="color:#c9d6e0">{{ voice.line }}</div>
      <div class="mt-2 font-mono text-[10px]" style="color:#6d7f8f">
        [ Прислушаться ]
      </div>
    </button>
  </div>
</template>

<style scoped>
.gb-d6 {
  background: center/contain no-repeat url('/easter/img/d6.png');
  cursor: pointer;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, .4));
  animation: gb-bob 1.6s ease-in-out infinite;
}
.gb-d6:disabled { animation: gb-spin 1.15s cubic-bezier(.25, .1, .2, 1) }
@keyframes gb-bob { 50% { translate: 0 -4px } }
@keyframes gb-spin { to { rotate: 720deg } }

.gb-tear { top: -8px; height: 10px; background: #7fd7ff; opacity: .7; animation: gb-drip linear infinite }
@keyframes gb-drip { to { translate: 0 100vh } }

.gb-uk {
  transform-origin: 100% 50%;
  transform: perspective(720px) rotateY(-17deg) translateX(18%);
  opacity: 0;
  transition: .5s cubic-bezier(.2, .9, .3, 1);
  background: linear-gradient(160deg, rgba(255, 255, 255, .22), rgba(255, 255, 255, .05));
  backdrop-filter: blur(2px);
  box-shadow: -8px 0 28px rgba(0, 0, 0, .35);
}
.gb-uk-in { opacity: 1; transform: perspective(720px) rotateY(-17deg) }
.gb-uk-title {
  font-family: Unbounded, sans-serif; font-weight: 800;
  font-size: clamp(18px, 3.1vw, 34px); line-height: .92;
  color: #ffb01f; text-shadow: 3px 3px 0 #c0392b; white-space: nowrap;
}
.gb-uk-mul { color: #ff2d2d; display: inline-block; animation: gb-jitter .09s steps(2) infinite }
@keyframes gb-jitter { 50% { translate: 1px -1px } }

@media (prefers-reduced-motion: reduce) {
  .gb-d6, .gb-tear, .gb-uk-mul { animation: none }
}
</style>
