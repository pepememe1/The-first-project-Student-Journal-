<script setup>
// SidebarResizer — полоска на правом краю сайдбара, за которую его тянут.
//
// ⚠️ Слушатели на ОКНЕ, а не на самой полоске. Курсор во время перетаскивания легко
// обгоняет узкую (4 px) цель — палец дёрнулся, мышь ушла за её границу, и без оконных
// слушателей перетаскивание обрывается на середине. Ровно так ведут себя все
// самодельные «ресайзеры», которые пробуют делать на mousemove по элементу.
//
// ⚠️ `setPointerCapture` не используем намеренно: он привязывает события к элементу, но
// не спасает от `pointercancel` при выходе за окно. Пара «окно + pointerup» надёжнее и
// понятнее.
//
// ⚠️ Двойной щелчок сворачивает и разворачивает. Это не украшение: дотянуть мышью ровно
// до минимума неудобно, а свернуть «в иконки» хочется одним движением.
import { onBeforeUnmount } from 'vue'
import { useSidebarStore } from '@/stores/sidebar'
import { useLocaleStore } from '@/stores/locale'

const sidebar = useSidebarStore()
const locale = useLocaleStore()

function onMove(e) { sidebar.setWidth(e.clientX) }

function stop() {
  sidebar.dragging = false
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', stop)
  document.body.style.removeProperty('cursor')
  document.body.style.removeProperty('user-select')
}

function start(e) {
  e.preventDefault()
  sidebar.dragging = true
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', stop)
  //Курсор и запрет выделения — на ВСЁ окно: иначе при быстром движении подсвечивается
  //текст страницы, и перетаскивание выглядит как случайное выделение.
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// Клавиатура: стрелками по 16 px, потому что мышью этот край доступен не всем.
function onKey(e) {
  if (e.key === 'ArrowLeft') { e.preventDefault(); sidebar.setWidth(sidebar.width - 16) }
  if (e.key === 'ArrowRight') { e.preventDefault(); sidebar.setWidth(sidebar.width + 16) }
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sidebar.toggle() }
}

onBeforeUnmount(stop)
</script>

<template>
  <div class="gb-resizer group absolute inset-y-0 -right-1 z-20 w-2 cursor-col-resize"
       role="separator" aria-orientation="vertical" tabindex="0"
       :aria-valuenow="sidebar.width" :aria-valuemin="sidebar.MIN_W" :aria-valuemax="sidebar.MAX_W"
       :aria-label="locale.t('sidebar.resize', 'Ширина меню')"
       :title="locale.t('sidebar.resizeHint', 'Потяните, чтобы изменить ширину. Двойной щелчок — свернуть')"
       @pointerdown="start" @dblclick="sidebar.toggle()" @keydown="onKey">
    <!-- Видимая часть тоньше зоны захвата: цель для мыши 8 px, полоска 2 px. Узкую
         цель невозможно поймать, а широкая полоса выглядит как элемент интерфейса. -->
    <span class="pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded
                 bg-accent opacity-0 transition-opacity group-hover:opacity-70
                 group-focus-visible:opacity-100"
          :class="sidebar.dragging ? '!opacity-100' : ''"></span>
  </div>
</template>
