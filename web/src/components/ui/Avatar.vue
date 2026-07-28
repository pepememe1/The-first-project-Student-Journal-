<script setup>
// Avatar — круглая аватарка: показывает картинку (prefs.avatar) либо инициалы по ФИО.
// Единый вид во всех местах (список чатов, карточка, каталог людей, модерация).
import { computed } from 'vue'
import { statusColor, statusLabel } from '@/config/status'

const props = defineProps({
  src: { type: String, default: '' },
  name: { type: String, default: '' },
  size: { type: Number, default: 40 },
  online: { type: Boolean, default: false },
  //§D7: выбранный человеком статус (dnd/studying/away). Если он есть — точка у аватарки
  //показывает ЕГО, а не presence: «не беспокоить» при этом остаётся «в сети», и зелёный
  //кружок рядом с красным статусом читался как противоречие (см. скриншот в задаче).
  status: { type: String, default: '' },
  statusText: { type: String, default: '' },
  //Какую часть картинки оставлять при кадрировании в круг. Аватарки людей обрезаны по
  //центру ещё при загрузке, а спрайт маскота — фигура в полный рост: без 'top' в кружок
  //попало бы туловище вместо морды.
  position: { type: String, default: 'center' },
})

const initials = computed(() => {
  const p = (props.name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
})

// Точка у аватарки ОДНА: либо статус (он важнее — человек выбрал его сам), либо presence.
const dot = computed(() => {
  if (props.status) {
    return { color: statusColor(props.status),
             title: statusLabel(props.status, props.statusText) }
  }
  return props.online ? { color: '#2e9e5b', title: 'в сети' } : null
})
</script>

<template>
  <div class="relative shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
    <div class="size-full overflow-hidden rounded-full bg-accent">
      <img v-if="src" :src="src" alt="" class="size-full object-cover"
           :style="{ objectPosition: position }" />
      <span v-else class="grid size-full place-items-center font-bold text-white"
            :style="{ fontSize: Math.round(size * 0.4) + 'px' }">{{ initials }}</span>
    </div>
    <span v-if="dot" :title="dot.title"
          class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card"
          :style="{ background: dot.color }"></span>
  </div>
</template>
