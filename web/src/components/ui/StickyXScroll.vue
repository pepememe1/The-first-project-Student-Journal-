<script setup>
/**
 * StickyXScroll — горизонтальная прокрутка широкой таблицы с ползунком, ПРИЖАТЫМ К НИЗУ
 * ЭКРАНА.
 *
 * 🔥 ЗАЧЕМ (12.09.2026, жалоба Влада). У таблиц, которые физически не влезают в монитор
 * по ширине, полоса прокрутки живёт на НИЖНЕЙ ГРАНИЦЕ САМОЙ ТАБЛИЦЫ. У журнала на
 * тридцать студентов это значит: чтобы сдвинуть таблицу вбок, надо сначала промотать
 * страницу до самого низа, там подвинуть ползунок, а потом вернуться наверх — и так на
 * каждый шаг. Формально прокрутка есть, пользоваться ею нельзя.
 *
 * Решение: рядом с настоящим контейнером живёт ВТОРАЯ полоса, `position: sticky` снизу.
 * Пока таблица на экране, полоса висит у нижнего края окна и едет вместе со страницей;
 * когда таблица уходит вверх — полоса уходит с ней. Обе прокрутки синхронизированы, то
 * есть тянуть можно любую.
 *
 * ⚠️ ПОЧЕМУ НЕ «СДЕЛАТЬ САМ КОНТЕЙНЕР STICKY». Липким можно сделать элемент, а не его
 * полосу прокрутки: она рисуется на нижней границе ПРОКРУЧИВАЕМОГО блока, и пока блок
 * выше экрана, полоса тоже выше. Приклеить сам блок значит приклеить таблицу целиком —
 * страница перестанет прокручиваться вертикально.
 *
 * ⚠️ ПОЛОСА ПОКАЗЫВАЕТСЯ, ТОЛЬКО КОГДА ЕСТЬ ЧТО ПРОКРУЧИВАТЬ. Пустая полоса под каждой
 * узкой таблицей — шум, который быстро перестают замечать (наш урок про сигнал, который
 * всегда горит). Ширина пересчитывается `ResizeObserver`-ом: столбцы меняются от данных,
 * а не только от размера окна.
 *
 * ⚠️ `aria-hidden` у полосы намеренно: она ДУБЛИРУЕТ прокрутку самой таблицы, и для
 * читалки экрана это лишний интерактивный элемент без содержимого.
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { isHandheld } from '@/utils/device'
import { useLocaleStore } from '@/stores/locale'
import GbIcon from '@/components/ui/GbIcon.vue'

const body = ref(null)      //настоящий контейнер с таблицей
const bar = ref(null)       //липкая полоса-дублёр
const width = ref(0)        //ширина содержимого, px
const needed = ref(false)   //есть ли горизонтальное переполнение
const scrolled = ref(false) //человек уже двигал таблицу вбок — подсказка больше не нужна

/**
 * 🔥 ПОДСКАЗКА О БОКОВОЙ ПРОКРУТКЕ (UX-аудит 17.10.2026). «Таблица около 1074 px при
 * ширине контейнера 364 px. Горизонтальная прокрутка работает, но подсказки о свайпе
 * не заметил; оценки и действия в дальних столбцах легко пропустить.»
 *
 * ⚠️ ЖИВЁТ ЗДЕСЬ, А НЕ В ЖУРНАЛЕ. Широких таблиц в продукте несколько (журнал
 * преподавателя, отчёт куратора, трекер), и подсказка, написанная в одной из них, —
 * это наш обычный «первое забытое место»: остальные молча остаются без неё.
 *
 * ⚠️ ТОЛЬКО ДЛЯ ПАЛЬЦА (`isHandheld`, тот же признак, что у вибрации и QR). На
 * компьютере видна сама полоса, есть колесо с Shift и мышь — строка там только шум.
 *
 * ⚠️ И только ДО ПЕРВОЙ прокрутки: подсказка, висящая всегда, перестаёт читаться —
 * тот же урок, что про сигнал, который горит постоянно.
 */
const locale = useLocaleStore()
const handheld = ref(false)
const hintVisible = () => needed.value && handheld.value && !scrolled.value

//Флаг против петли: любое присваивание scrollLeft рождает событие scroll у соседа.
let syncing = false

function fromBody() {
  if (body.value && body.value.scrollLeft > 0) scrolled.value = true
  if (syncing || !bar.value || !body.value) return
  syncing = true
  bar.value.scrollLeft = body.value.scrollLeft
  syncing = false
}

function fromBar() {
  if (bar.value && bar.value.scrollLeft > 0) scrolled.value = true
  if (syncing || !bar.value || !body.value) return
  syncing = true
  body.value.scrollLeft = bar.value.scrollLeft
  syncing = false
}

function measure() {
  const el = body.value
  if (!el) return
  width.value = el.scrollWidth
  //Запас в один пиксель: дробные ширины после масштабирования дают вечное «переполнение»
  //на таблице, которая на самом деле помещается.
  needed.value = el.scrollWidth - el.clientWidth > 1
}

let ro = null
onMounted(() => {
  //Признак устройства спрашиваем ОДИН раз при монтировании: он про железо, а не про
  //ширину окна, и за жизнь страницы не меняется.
  handheld.value = isHandheld()
  measure()
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(measure)
    ro.observe(body.value)
    //Следим и за содержимым: строки добавляются после загрузки, и ширина меняется тогда,
    //а не в момент монтирования.
    if (body.value.firstElementChild) ro.observe(body.value.firstElementChild)
  }
  window.addEventListener('resize', measure)
})
onBeforeUnmount(() => {
  if (ro) ro.disconnect()
  window.removeEventListener('resize', measure)
})

defineExpose({ measure })
</script>

<template>
  <div class="gb-sticky-x">
    <p v-if="hintVisible()" class="mb-1 flex items-center gap-1.5 px-2 text-xs text-text3">
      <GbIcon name="scrollX" class="size-3.5 shrink-0" />
      {{ locale.t('table.swipeHint', 'Таблица шире экрана — листайте вбок') }}
    </p>
    <div ref="body" class="gb-sticky-x__body overflow-x-auto" @scroll="fromBody">
      <slot />
    </div>
    <div v-show="needed" ref="bar" aria-hidden="true"
         class="gb-sticky-x__bar sticky bottom-0 z-20 overflow-x-auto overflow-y-hidden"
         @scroll="fromBar">
      <div :style="{ width: width + 'px' }" class="h-px"></div>
    </div>
  </div>
</template>

<style scoped>
/* Полоса должна быть ВИДНА: в отличие от обычной прокрутки, у неё нет содержимого,
   и на системах со скрывающимися полосами она осталась бы невидимой до наведения. */
.gb-sticky-x__bar {
  height: 14px;
  scrollbar-width: thin;
}
.gb-sticky-x__bar::-webkit-scrollbar { height: 10px; }
.gb-sticky-x__bar::-webkit-scrollbar-thumb {
  background: var(--gb-border2, rgba(128, 128, 128, 0.6));
  border-radius: 999px;
}
.gb-sticky-x__bar::-webkit-scrollbar-track { background: transparent; }
</style>
