<script setup>
// TabBar — вкладки разделов, одни на весь продукт (28.10.2026).
//
// Раньше рядом жили три вида: подчёркнутые (куратор, «Сервер», уведомления), залитые
// таблетки (мессенджер админа) и сегменты (сведения о беседе). Человек не узнавал в них
// одно и то же действие, а залитая таблетка читалась как кнопка, которая что-то сделает.
// Оставлен один вид — подчёркивание активной, как у Gmail и Telegram Desktop.
//
// Фильтры-фишки (разделы листа логинов, «Все/Личные/Группы» в списке бесед) — не вкладки:
// они сужают список, а не переключают раздел, и остаются фишками.
//
// Клавиатура — как велит ARIA для tablist: стрелки ходят по вкладкам, Home/End — к краям.
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, required: true },
  // [{ id, label, icon?, count?, alert?, title? }]; alert — красный счётчик («есть кто-то»)
  tabs: { type: Array, required: true },
  // Равные доли ширины — для узких панелей (сведения о беседе, боковая колонка).
  stretch: { type: Boolean, default: false },
  // На телефоне остаются только значки: подписи бы не влезли в узкую панель.
  iconsOnMobile: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const buttons = ref([])

function pick(id) {
  if (id !== props.modelValue) emit('update:modelValue', id)
}

function onKey(e, i) {
  const n = props.tabs.length
  const to = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key]
  if (to === undefined) return
  e.preventDefault()
  pick(props.tabs[to].id)
  buttons.value[to]?.focus()
}
</script>

<template>
  <!-- Линия под вкладками — внутренней тенью, а не рамкой с -mb-px у кнопок: ряд умеет
       прокручиваться вбок, и заступ кнопки за рамку давал вертикальную полосу прокрутки. -->
  <div role="tablist" class="flex items-center gap-1 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_var(--gb-border)]">
    <button v-for="(t, i) in tabs" :key="t.id" :ref="(el) => { buttons[i] = el }" type="button"
            role="tab" :aria-selected="t.id === modelValue" :tabindex="t.id === modelValue ? 0 : -1"
            :title="t.title || (iconsOnMobile ? t.label : undefined)"
            class="flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors pointer-coarse:min-h-11"
            :class="[t.id === modelValue ? 'border-accent font-semibold text-accent' : 'border-transparent text-text3 hover:text-text',
                     stretch ? 'flex-1 justify-center' : '']"
            @click="pick(t.id)" @keydown="onKey($event, i)">
      <component :is="t.icon" v-if="t.icon" class="size-4 shrink-0" aria-hidden="true" />
      <span :class="iconsOnMobile && t.icon ? 'max-sm:sr-only' : ''">{{ t.label }}</span>
      <span v-if="t.count" class="rounded-full px-1.5 text-[11px] font-bold tabular-nums"
            :class="t.alert ? 'bg-red text-white' : 'bg-accent-glow text-accent'">{{ t.count }}</span>
    </button>
    <slot name="end" />
  </div>
</template>
