<script setup>
// RDR2 на странице 404. Своих ассетов нет — собрано вёрсткой: бумага, силуэт, тон.
// Уходит само: читать тут нечего, кроме одной шутки.
import { onMounted, ref } from 'vue'
const emit = defineEmits(['close'])
const shown = ref(false)
onMounted(() => { shown.value = true; setTimeout(() => emit('close'), 9000) })
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[90] grid place-items-center p-6">
    <div class="max-w-md rounded-sm border p-5 shadow-2xl transition-all duration-500"
         :class="shown ? 'opacity-100' : 'translate-y-3 opacity-0'"
         style="background:linear-gradient(#efe3c8,#e2d2b0);border-color:#b9a681;transform:rotate(-1.2deg)">
      <p class="font-mono text-[10px] font-bold tracking-[.22em]" style="color:#8a7550">WANTED</p>
      <p class="mt-2 font-title text-lg leading-tight" style="color:#2e2416">Этой страницы нет.</p>
      <p class="mt-1.5 text-sm leading-relaxed" style="color:#4a3c26">
        Но у меня есть ПЛАН — нам просто нужно немного времени, чуток терпения и
        <b>ЕЩЁ ОДНА СЕССИЯ!</b>
      </p>
    </div>
  </div>
</template>
