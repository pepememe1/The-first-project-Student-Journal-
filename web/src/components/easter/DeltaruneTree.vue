<script setup>
// Дерево Делтарун — выпадает на переключении между вкладками.
//
// ⚠️ ОВЕРЛЕЙ БЕЗ РОУТИНГА, и это принципиально: адрес не меняется, значит и подсмотреть
// нечего, и напрямую зайти невозможно — это не URL, а временный элемент, который
// существует, только пока показан. Перезагрузка страницы его убирает.
//
// 🔥 ЗАКРЫТЬ ЕГО КЛИКОМ «КУДА ПОПАЛО» НЕЛЬЗЯ (правка Влада 23.08.2026). Раньше поверх
// всей сцены лежала кнопка «закрыть», и ОДИН промах мимо дерева уносил находку целиком:
// человек кликал, чтобы заговорить, попадал мимо — и сцены больше нет, а ачивки не
// будет. Влад с Ярославом ловили дерево специально и не могли его пройти.
//
// Поэтому сцена ведёт себя как то самое окно про cookie, из которого нельзя выйти мимо
// кнопок: кликабельны РОВНО два места — само дерево и окно диалога. Выход появляется
// только ПОСЛЕ последней реплики: снизу открывается проход, душа уходит вниз (как
// персонаж выходит из комнаты), и полоса внизу становится живой.
//
// ⚠️ Выход НЕ активен, пока диалог не дочитан до конца. Иначе, прокликивая реплики,
// человек проскакивал бы в проход и терял ачивку ровно тем же промахом, от которого
// эта правка и защищает.
//
// Реплики листаются КЛИКОМ по окну. Взял яйцо — дальше при любом заходе остаётся только
// «Это дерево».
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { mumble } from '@/utils/mumble'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const FULL = ['* (Он за деревом.)', '* (Он предлагает тебе что-то.)', '* (Вы получили "Яйцо")',
              '* (Ну, здесь теперь никого нет.)', '* (Это дерево.)']
const SHORT = ['* (Это дерево.)']

// Яйцо уже брали? Помним на устройстве: сервер знает про ачивку, но спрашивать его
// ради одной строки диалога — лишний запрос ровно в тот момент, когда важна плавность.
const taken = ref(localStorage.getItem('gb.egg.tree') === '1')
const lines = ref([])
const dlg = ref('')
const started = ref(false)
const shown = ref(false)
// Проход внизу. Открывается ТОЛЬКО когда диалог дочитан до последней реплики.
const wayOut = ref(false)
const leaving = ref(false)
// ⚠️ ПРЕДОХРАНИТЕЛЬ ОТ ЛОВУШКИ. Сцена намеренно модальная: выйти можно только через
// проход внизу, а он открывается лишь после разговора с деревом. Но человек, который не
// играл в Deltarune, может просто не понять, что дерево кликабельно, — и окажется заперт
// в журнале, пока не сработает пятиминутный предохранитель стора. Пять минут «продукт
// завис» — цена, несопоставимая с пасхалкой.
// Поэтому через 25 секунд БЕЗ ЕДИНОГО действия в углу появляется скромный выход. Он
// поздний и мелкий: случайно попасть в него в первые секунды, ради чего всё и затевалось,
// невозможно.
const escapeShown = ref(false)
let escapeTimer = 0
let busy = false, music = null

function armEscape() {
  clearTimeout(escapeTimer)
  escapeShown.value = false
  escapeTimer = setTimeout(() => { escapeShown.value = true }, 25000)
}

onMounted(() => {
  requestAnimationFrame(() => { shown.value = true })
  music = new Audio('/easter/snd/tree.ogg')
  music.loop = true
  music.volume = 0
  music.play().catch(() => {})
  const t0 = performance.now()
  const id = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / 1400)
    music.volume = 0.3 * k
    if (k >= 1) clearInterval(id)
  }, 50)
  armEscape()
})
onBeforeUnmount(() => { clearTimeout(escapeTimer); if (music) music.pause() })

async function type(text) {
  busy = true
  dlg.value = ''
  for (let i = 1; i <= text.length; i++) {
    dlg.value = text.slice(0, i)
    if (i % 2 === 0 && text[i - 1] !== ' ') mumble()
    await new Promise((r) => setTimeout(r, 30))
  }
  busy = false
}

let step = 0
async function talk() {
  armEscape()                    //человек разобрался — выход снова не нужен
  if (started.value) return
  started.value = true
  lines.value = taken.value ? SHORT : FULL
  await type(lines.value[0])
}

async function advance() {
  armEscape()
  if (!started.value || busy) return
  step += 1
  if (step < lines.value.length) { await type(lines.value[step]); return }

  // Диалог дочитан. Ачивку закрываем ЗДЕСЬ — до того, как человек пойдёт к выходу:
  // между «дочитал» и «ушёл» он может передумать, а находка уже состоялась.
  const first = lines.value.length > 1
  started.value = false; step = 0; dlg.value = ''
  if (first && !taken.value) {
    taken.value = true
    localStorage.setItem('gb.egg.tree', '1')
    await easter.claim('deltarune_tree')
  }
  wayOut.value = true          //только теперь снизу можно уйти
}

/** Уйти вниз. Работает лишь после последней реплики — см. докстринг. */
async function leave() {
  if (!wayOut.value || leaving.value) return
  leaving.value = true
  if (music) {
    //Гасим музыку, а не обрываем: резкий обрыв слышен как сбой.
    const v0 = music.volume, t0 = performance.now()
    const id = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / 600)
      music.volume = Math.max(0, v0 * (1 - k))
      if (k >= 1) { clearInterval(id); music.pause() }
    }, 40)
  }
  await new Promise((r) => setTimeout(r, 900))   //душа успевает уйти за нижний край
  shown.value = false
  await new Promise((r) => setTimeout(r, 400))
  emit('close')
}
</script>

<template>
  <!-- ⚠️ Кнопки «закрыть на весь экран» здесь НЕТ и быть не должно: именно она уносила
       находку одним промахом. Кликабельны только дерево, окно диалога и проход внизу. -->
  <div class="soul fixed inset-0 z-[95] grid place-items-center overflow-hidden bg-black
              transition-opacity duration-500"
       :style="{ opacity: shown ? 1 : 0 }">

    <!-- 🔥 КЛИКАБЕЛЬНО САМО ДЕРЕВО, а не прямоугольник рядом с ним. Раньше хитбокс
         стоял отдельным блоком «внизу по центру» и с картинкой не совпадал: Влад жал
         туда, где дерево нарисовано, и не попадал — приходилось искать место ниже.
         Область клика обязана совпадать с тем, что человек видит; иначе это не
         секрет, а угадайка. -->
    <button type="button" @click.stop="talk" aria-label="Осмотреть дерево"
            class="soul relative z-[1] block w-[31%] max-w-[280px] border-0 bg-transparent p-0">
      <img src="/easter/img/tree.gif" alt="" class="block w-full"
           style="image-rendering:pixelated;filter:drop-shadow(0 0 26px rgba(200,30,90,.3))" />
    </button>

    <div v-if="started" class="utbox soul absolute inset-x-[7%] bottom-[6%]" @click.stop="advance">
      <span>{{ dlg }}</span>
      <span class="absolute bottom-1 right-2.5 text-[9px] text-[#8a8a8a]">▼ клик</span>
    </div>

    <!-- 🔥 ВЫХОД НЕ СУЩЕСТВУЕТ, ПОКА ИДЁТ ДИАЛОГ (`!started`), и это куплено ошибкой:
         поздний выход появлялся прямо во время разговора, человек жал «дальше» по
         реплике, попадал в него и вылетал из пасхалки не дочитав. Ровно тот промах, от
         которого вся эта модальность и защищает.
         Заодно и проход внизу прячется на время повторного разговора: открыл диалог
         снова — выхода нет, пока не дочитаешь. -->
    <button v-if="escapeShown && !wayOut && !started" type="button" @click.stop="emit('close')"
            class="soul absolute right-3 top-3 rounded border border-[#3a3a3a] px-2 py-1
                   font-mono text-[9px] text-[#6d6a5f] hover:text-[#c9c9c9]">
      выйти
    </button>

    <!-- Проход вниз. До конца диалога его нет вовсе — ни полосы, ни подсказки.
         ⚠️ Второго красного сердца здесь БЫЛО и убрано: курсор и так душа, и две
         одинаковые метки на экране читались как ошибка отрисовки. Подписи достаточно. -->
    <template v-if="wayOut && !started">
      <button type="button" @click.stop="leave" aria-label="Уйти вниз"
              class="soul absolute inset-x-0 bottom-0 h-[13%] border-0 bg-transparent p-0">
        <span class="pointer-events-none block pb-2 text-center text-[10px] tracking-[.3em] text-[#6d6a5f]">
          ▼ УЙТИ ▼
        </span>
      </button>
    </template>
  </div>
</template>

<style scoped>
/* Курсор-душа: смысловая часть сцены, а не украшение. */
.soul { cursor: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 8 8'%3E%3Cpath fill='%23f00' d='M1 1h2v1h2V1h2v1h1v3H7v1H6v1H5v1H3V7H2V6H1V5H0V2h1z'/%3E%3C/svg%3E") 9 9, auto; }
.utbox { background:#000; border:4px solid #fff; color:#fff; padding:14px 16px; min-height:58px;
         font-family:'Press Start 2P', monospace; font-size:11px; line-height:1.95; }

@media (prefers-reduced-motion: reduce) {
  .utbox { transition: none }
}
</style>
