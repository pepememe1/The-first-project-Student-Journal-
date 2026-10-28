<script setup>
// VectorPage — вкладка «ИИ Помощник» (порт vector/widget.py). Компоновка как в
// десктопе (_AvatarChatOverlay): ОДИН крупный Вектор во всю площадь + переписка
// полупрозрачным слоем ПОВЕРХ него. Маскот РЕАГИРУЕТ: приветствие → «думает» →
// эмоция по настроению ответа → покой. Цифры считает СЕРВЕР (/web/vector/ask).
// Чат живёт в общем store — ОДНА переписка с боковым доком (как в десктопе).
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, LayoutGrid } from '@lucide/vue'
import Mascot from '@/components/Mascot.vue'
import { useEasterStore } from '@/stores/easterEggs'
import MicButton from '@/components/vector/MicButton.vue'
import GradesOverview from '@/components/vector/GradesOverview.vue'
import TeacherOverview from '@/components/vector/TeacherOverview.vue'
import AdminOverview from '@/components/vector/AdminOverview.vue'
import { useVectorStore } from '@/stores/vector'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const vector = useVectorStore()
const auth = useAuthStore()
const toast = useToast()
const locale = useLocaleStore()
const easter = useEasterStore()
// Правая колонка — СВОЯ у каждой роли (3.6). Раньше здесь была только сводка студента,
// а у преподавателя и администратора вкладка «ИИ Помощник» пустовала наполовину, хотя
// это самая просторная страница продукта. Что кому показываем:
//   student/parent — успеваемость (общий средний + предметы; родитель видит ровно то же,
//                    что его студент, по /web/parent/stats того же формата);
//   teacher        — его группы и предметы со средним + сколько студентов в зоне риска;
//   admin          — состояние сервера и сколько в системе людей.
// Сопоставление ролей и компонентов держим ОДНОЙ картой: разбросанные по шаблону
// v-if="role === ..." разъезжаются при добавлении следующей роли.
const SIDE_PANELS = {
  student: GradesOverview,
  parent: GradesOverview,
  teacher: TeacherOverview,
  admin: AdminOverview,
}
const sidePanel = computed(() => SIDE_PANELS[auth.role] || null)
// Имя маскота уже переведено в общем ключе (мессенджер показывает те же ответы от
// его лица) — переиспользуем его, а не заводим вторую копию «Вектор»/«Vector».
const vectorName = () => locale.t('chatThread.vectorName', 'Вектор')

// Голос только ЗАПОЛНЯЕТ поле — отправка всё равно по кнопке/Enter человеком: так
// можно поправить неверно распознанное слово перед отправкой Вектору.
function onVoiceText(text) { vector.input = text }
function onVoiceError(msg) { toast.error(msg) }
const { messages, input, queued, state, anim, label, cmds, tick, typingReveal } = storeToRefs(vector)

// Анимация «печати» ответа по символам — ТОЛЬКО здесь (в доке остаётся мгновенный вывод,
// см. docs — правка). Двойной клик по печатающемуся сообщению сразу показывает целиком.
function displayText(i) {
  const tr = typingReveal.value
  return (tr.index === i && !tr.done) ? tr.text : messages.value[i].text
}
function isTyping(i) {
  return typingReveal.value.index === i && !typingReveal.value.done
}
function onMessageDblClick(i) {
  if (isTyping(i)) vector.skipTyping()
}
const scroller = ref(null)
const showQuick = ref(false)
// На телефоне при вводе (клавиатура открыта) прячем крупный маскот-фон и разворачиваем
// чат на всю высоту — так клавиатура закрывает пустое место, а не «красивый интерфейс».
const focused = ref(false)

// ⚠️ Живой баг (отзыв 3.5.6): развёрнутый чат ЗАСТРЕВАЛ поверх маскота после того, как
// клавиатуру убрали. Причина — режим снимался ТОЛЬКО по @blur, а закрытие клавиатуры
// системной кнопкой «назад» (Android) или свайпом фокус с поля НЕ снимает: событие blur
// не приходит никогда, и полупрозрачная панель остаётся развёрнутой навсегда, пока не
// уйдёшь со страницы. Слушаем САМУ клавиатуру: visualViewport сжимается ровно на её
// высоту, и её уход — единственный надёжный признак, что режим ввода закончился.
const KEYBOARD_MIN_PX = 120   //меньше — это адресная строка браузера, а не клавиатура
function onViewportResize() {
  const vv = window.visualViewport
  if (!vv) return
  if (window.innerHeight - vv.height < KEYBOARD_MIN_PX) focused.value = false
}
onMounted(() => window.visualViewport?.addEventListener('resize', onViewportResize))
onBeforeUnmount(() => window.visualViewport?.removeEventListener('resize', onViewportResize))

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}
watch(tick, scrollDown)
// greetOnce — приветствие голосом ровно при открытии этой вкладки (не на бургер-меню).
onMounted(() => { vector.greetSettle(); scrollDown(); vector.greetOnce() })

function send() { vector.send() }
//cmd — весь объект быстрой команды: q (русский, для классификатора) отдельно от
//label (переведённая подпись — что реально показываем в СВОЁМ пузыре, см. vector.js::send).
function ask(cmd) { showQuick.value = false; vector.ask(cmd.q, cmd.label) }
</script>

<template>
  <!-- Две колонки на широком экране: слева переписка, справа сводка ПО РОЛИ (3.6).
       Раньше вкладка на всю высоту несла ТОЛЬКО чат — правая половина пустовала, хотя
       это самая просторная страница продукта.
       Высота задана ОДНА на обе колонки (h-full у детей), чтобы кольцо и полосы не
       уезжали за нижний край рядом с более высокой карточкой чата.
       🔥 ПОДЗАГОЛОВОК ЗДЕСЬ БОЛЬШЕ НЕ ВЫЧИТАЕТСЯ (05.10.2026, жалоба Ярослава: «между
       ячейкой ввода и низом экрана зазор, убери, чтобы было от края до края»). Строку
       подзаголовка у этой страницы убрали ещё 25.08.2026 (`meta.subtitle` в роутере нет),
       а формула высоты продолжала отнимать её 26 px — замер на стенде: карточка
       кончалась на 39 px выше низа экрана. Тот же класс, что «свой набор чисел» у
       мессенджера в 3.5.6: число описывало раскладку, которой уже нет, и устарело молча.
       ⚠️ `gb-fullbleed` — как у мессенджера: на телефоне страница съедает отступы
       контейнера и встаёт во всю ширину и до нижней безопасной зоны (см. style.css). -->
  <div class="gb-fullbleed grid grid-cols-1 h-[calc(100dvh-var(--gb-page-offset))] gap-3"
       :class="sidePanel ? 'lg:grid-cols-[1fr_320px]' : ''">
  <!-- Одна карточка на всю высоту: шапка · (маскот ФОНОМ + чат поверх) · ввод.
       На телефоне рамка и скругление сняты: карточка во весь экран, и рамка вокруг неё
       читалась бы как полоска-зазор, от которой как раз и избавляемся. -->
  <div class="relative flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card max-sm:rounded-none max-sm:border-x-0 max-sm:border-b-0 max-sm:shadow-none">
    <!-- Шапка -->
    <div class="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
      <span class="size-2 shrink-0 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
      <span class="font-title text-base font-bold text-text">{{ vectorName() }}</span>
      <span v-if="label" class="min-w-0 truncate text-xs text-text3">· {{ label }}</span>
    </div>

    <!-- Маскот ФОНОМ (крупный, по центру) + чат полупрозрачным слоем поверх.
         На широком экране (xl) — рядом, а не поверх: на 1920 пузырь чата закрывал тигра
         по грудь и сам стоял почти пустым (находка N8, 28.10.2026). Слева Вектор во весь
         рост, справа переписка своей колонкой. -->
    <div class="relative min-h-0 flex-1 overflow-hidden xl:flex">
      <div class="pointer-events-none absolute inset-0 transition-opacity duration-300 xl:static xl:w-2/5 xl:shrink-0"
           :class="{ 'opacity-15 sm:opacity-100': focused }">
        <!-- 🔥 НОЧНАЯ СМЕНА FNAF: Вектора может не быть на месте. Пустое место намеренно
             НЕ подписано — вся игра в том, чтобы человек заметил пропажу сам и позвал
             его вопросом. Величина одна на оба места показа (вкладка и шторка): держи
             её в компоненте, и заметивший пропажу в шторке увидел бы на вкладке живого
             Вектора, то есть игра развалилась бы там, где в неё поверили. -->
        <Mascot v-if="!easter.fnaf.hidden" :anim="anim" class="h-full w-full" />
      </div>
      <!-- Чат: верхний край ~40% высоты (уровень туловища), по центру, ограничен по
           ширине; подложка полупрозрачная + размытие — текст читаем, Вектор просвечивает.
           На телефоне при вводе разворачивается почти на всю высоту (top-3). -->
      <!-- Сообщения прижаты к низу распоркой (flex-1): короткая переписка не висит у верха
           пустого пузыря, длинная прокручивается как обычно. -->
      <div ref="scroller"
           class="absolute inset-x-4 bottom-4 mx-auto flex max-w-3xl flex-col gap-3 overflow-y-auto rounded-xl border border-border/60 bg-card/70 p-4 backdrop-blur-sm transition-[top] duration-300 sm:inset-x-8 xl:static xl:my-4 xl:mr-4 xl:ml-0 xl:flex-1 xl:max-w-none"
           :class="focused ? 'top-3 sm:top-[40%]' : 'top-[40%]'">
        <div class="flex-1" aria-hidden="true" />
        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="flex justify-end">
            <div class="max-w-[80%] rounded-lg bg-accent px-4 py-2 text-sm text-white">{{ m.text }}</div>
          </div>
          <p v-else class="text-[15px] leading-relaxed text-text" @dblclick="onMessageDblClick(i)"
             :title="isTyping(i) ? locale.t('vectorPage.dblClickHint', 'Двойной клик — показать целиком') : ''">
            <span class="font-semibold text-accent">{{ vectorName() }}:</span> {{ displayText(i) }}<span
              v-if="isTyping(i)" class="animate-pulse text-accent">▍</span>
          </p>
        </template>
        <p v-if="state === 'thinking'" class="text-xs text-text2">{{ locale.t('vectorPage.thinking', { name: vectorName() }) }}</p>
        <p v-if="queued" class="text-xs text-text2">{{ locale.t('vectorPage.queued', { q: queued.displayText || queued.text }) }}</p>
      </div>
    </div>

    <!-- Ввод + кнопка «Быстрые команды» (попап, как в десктопе). На xl — под колонкой
         переписки, а не по центру карточки под тигром. -->
    <div class="relative shrink-0 border-t border-border p-3 xl:pl-[calc(40%+0.75rem)] xl:pr-4">
      <transition name="pop">
        <div v-if="showQuick && cmds.length"
             class="absolute bottom-full left-3 right-3 mb-2 rounded-lg border border-border2 bg-card p-2 shadow-card">
          <p class="px-1 pb-1 text-xs font-semibold text-text3">{{ locale.t('vectorPage.quickCommands', 'Быстрые команды') }}</p>
          <div class="flex flex-col gap-0.5">
            <button v-for="c in cmds" :key="c.label" type="button" @click="ask(c)"
                    class="flex items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm text-text transition-colors hover:bg-accent-glow hover:text-accent">
              <component :is="c.icon" class="size-4 shrink-0 text-accent" />{{ c.label }}
            </button>
          </div>
        </div>
      </transition>

      <!-- Подписью, а не одним значком сетки: что за ней, без слова не понять (живой прогон
           23.10.2026), а у поля ввода на телефоне так остаётся больше места. -->
      <div v-if="cmds.length" class="mx-auto mb-2 flex max-w-3xl xl:max-w-none">
        <button type="button" @click="showQuick = !showQuick" :aria-expanded="showQuick"
                class="inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors pointer-coarse:min-h-11"
                :class="showQuick ? 'border-accent bg-accent-glow text-accent' : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
          <LayoutGrid class="size-4" aria-hidden="true" />{{ locale.t('vectorPage.quickCommands', 'Быстрые команды') }}
        </button>
      </div>
      <form class="mx-auto flex max-w-3xl items-center gap-2 xl:max-w-none" @submit.prevent="send">
        <MicButton @text="onVoiceText" @error="onVoiceError" />
        <input v-model="input" :placeholder="locale.t('vectorPage.askPlaceholder', { name: vectorName() })"
               @focus="showQuick = false; focused = true" @blur="focused = false"
               class="h-11 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none focus:border-accent focus:bg-card" />
        <button type="submit" :aria-label="locale.t('vectorPage.send', 'Отправить')"
                class="grid size-11 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                :disabled="!input.trim()">
          <Send class="size-5" />
        </button>
      </form>
    </div>
  </div>

    <!-- Сводка роли — вторая колонка (скрыта на узких экранах: там она была бы не
         «использованием места», а лишней прокруткой перед чатом; на телефоне те же
         цифры человек видит на «Главной»). -->
    <div v-if="sidePanel" class="hidden min-h-0 lg:block">
      <component :is="sidePanel" />
    </div>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }
</style>
