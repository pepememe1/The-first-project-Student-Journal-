<script setup>
// MascotCooldown — §D2: вместо холодного «429 Too Many Requests» показываем Вектора с
// репликой и живым обратным отсчётом. Композер блокируется на cooldown.remaining секунд
// (см. stores/messenger.js::_startCooldown). Спрайт — существующий «warn-warn» из общего
// набора эмоций маскота (см. config/mascot.js), отдельных ассетов под фичу не заводим.
import { computed, ref } from 'vue'

const props = defineProps({ cooldown: { type: Object, required: true } })

// Фразы Вектора по тяжести кулдауна (мягче на первом нарушении, строже на систематике).
// Набор фиксированный — выбор случайный, чтобы одна и та же реплика не приедалась.
const PHRASES = {
  short: [
    'Ого, как быстро! Дай мне перевести дыхание.',
    'Полегче — я даже прочитать не успеваю.',
    'Секундочку, дай собеседнику вставить слово.',
  ],
  medium: [
    'Опять частишь. Может, соберёшься с мыслями?',
    'Я же просил помедленнее — а ты снова.',
    'Так и без голоса остаться недолго. Подожди чуть-чуть.',
  ],
  long: [
    'Так, стоп. Это уже не спешка, а систематика — модерация в курсе.',
    'Серьёзно? Придётся подождать подольше и обратиться к модерации, если что-то не так.',
  ],
}
function tier(seconds) {
  if (seconds >= 60) return 'long'
  if (seconds >= 20) return 'medium'
  return 'short'
}
// Фраза фиксируется на весь кулдаун (не дёргается каждую секунду обратного отсчёта).
const phrase = ref('')
let lastSeconds = 0
function pickPhrase() {
  const pool = PHRASES[tier(props.cooldown.seconds)]
  phrase.value = pool[Math.floor(Math.random() * pool.length)]
}
const label = computed(() => {
  if (props.cooldown.seconds !== lastSeconds) { lastSeconds = props.cooldown.seconds; pickPhrase() }
  return phrase.value
})
</script>

<template>
  <div class="flex items-end gap-2.5 border-b border-border bg-card2/60 px-3 py-2.5">
    <img src="/mascot/warn-warn.png" alt="Вектор" class="size-11 shrink-0 select-none object-contain" draggable="false" />
    <div class="min-w-0 flex-1 rounded-xl rounded-bl-sm border border-border2 bg-card px-3 py-2 text-sm text-text">
      {{ label }}
      <span class="ml-1.5 font-title font-bold text-accent">{{ cooldown.remaining }} c</span>
    </div>
  </div>
</template>
