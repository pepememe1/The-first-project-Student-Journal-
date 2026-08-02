<script setup>
// MascotCooldown — §D2: вместо холодного «429 Too Many Requests» показываем Вектора с
// репликой и живым обратным отсчётом. Композер блокируется на cooldown.remaining секунд
// (см. stores/messenger.js::_startCooldown). Спрайт — существующий «warn-warn» из общего
// набора эмоций маскота (см. config/mascot.js), отдельных ассетов под фичу не заводим.
import { computed, ref } from 'vue'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({ cooldown: { type: Object, required: true } })
const locale = useLocaleStore()

// Фразы Вектора по тяжести кулдауна (мягче на первом нарушении, строже на систематике).
// Набор фиксированный — выбор случайный, чтобы одна и та же реплика не приедалась.
// Реплики маскота — не строится под dictionaries.js (там ключ → ОДНА строка, а тут пул на
// выбор), поэтому свой маленький словарь пулов прямо здесь, тем же набором из 3 языков.
const PHRASES_BY_LOCALE = {
  ru: {
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
  },
  en: {
    short: [
      'Whoa, that was fast! Let me catch my breath.',
      'Easy there — I can barely keep up reading.',
      'One second, let the other person get a word in.',
    ],
    medium: [
      'You’re rushing again. Maybe slow down a bit?',
      'I did ask you to take it easy — and here we are again.',
      'Keep this up and you’ll lose your voice. Hang on a moment.',
    ],
    long: [
      'Okay, stop. This isn’t just haste anymore — moderation has been notified.',
      'Seriously? You’ll need to wait longer, and reach out to moderation if something’s wrong.',
    ],
  },
  zh: {
    short: [
      '哇，这么快！让我喘口气。',
      '慢一点——我都来不及看。',
      '稍等一下，让对方也能插句话。',
    ],
    medium: [
      '又发这么快了，要不整理一下思路？',
      '我说过要慢一点——你又来了。',
      '这样下去要被禁言了，稍等一下吧。',
    ],
    long: [
      '好了，停一下。这已经不是着急了，是有规律的行为——管理员已经知道了。',
      '真的假的？你得等更久了，如果有问题请联系管理员。',
    ],
  },
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
  const pool = (PHRASES_BY_LOCALE[locale.active] || PHRASES_BY_LOCALE.ru)[tier(props.cooldown.seconds)]
  phrase.value = pool[Math.floor(Math.random() * pool.length)]
}
const label = computed(() => {
  if (props.cooldown.seconds !== lastSeconds) { lastSeconds = props.cooldown.seconds; pickPhrase() }
  return phrase.value
})
</script>

<template>
  <div class="flex items-end gap-2.5 border-b border-border bg-card2/60 px-3 py-2.5">
    <img src="/mascot/warn-warn.png" alt="Vector" class="size-11 shrink-0 select-none object-contain" draggable="false" />
    <div class="min-w-0 flex-1 rounded-xl rounded-bl-sm border border-border2 bg-card px-3 py-2 text-sm text-text">
      {{ label }}
      <span class="ml-1.5 font-title font-bold text-accent">{{ locale.t('messenger.secondsShort', { n: cooldown.remaining }) }}</span>
    </div>
  </div>
</template>
