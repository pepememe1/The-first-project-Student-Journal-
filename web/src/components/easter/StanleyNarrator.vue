<script setup>
// Stanley Parable на странице 404.
//
// ━━ СЦЕНАРИЙ ПО СЕКУНДАМ (задан Владом 23.08.2026) ━━
//   0.3 с   цифра начинает дёргаться — человек сразу видит, что что-то происходит;
//   ~4 с    дрожь стихает, цифра остаётся прежней (404);
//   13 с    короткий срыв, и на месте 404 оказывается 427 — за две секунды до речи;
//   15 с    рассказчик начинает говорить.
//
// ⚠️ Пауза в пятнадцать секунд — ЧАСТЬ ШУТКИ, а не задержка загрузки: рассказчик
// награждает того, кто остался стоять на пустой странице. Но именно поэтому начало
// обязано быть заметным сразу: раньше первое изменение наступало через восемь секунд,
// и пасхалка была неотличима от невыпавшей — человек уходил, не дождавшись.
//
// ⚠️ Тайминги — ИМЕНОВАННЫЕ КОНСТАНТЫ и отсчитываются ОТ ОТКРЫТИЯ, а не цепочкой
// `await` друг за другом. С цепочкой «за две секунды до речи» приходилось бы каждый раз
// пересчитывать в уме, и любая правка одного шага молча сдвигала все следующие.
//
// Текстов три, озвучек семь: берём случайный текст и случайный файл из ЕГО пула.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { whenAudioReady } from '@/utils/audioReady'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const VARIANTS = [
  { files: 2, key: 'here', lines: ['Здесь никого нет, — подумал пользователь.', 'И всё равно остался.',
      'Возможно, из любопытства.', 'Возможно, просто не нашёл кнопку «Назад».'] },
  { files: 4, key: 'when', lines: ['Когда пользователь открыл эту страницу,', 'он понял, что здесь ничего нет.',
      'Но он всё равно продолжил на неё смотреть —', 'в надежде, что оценки появятся сами.'] },
  { files: 1, key: 'opened', lines: ['Пользователь открыл страницу.', 'Страницу, которой не существовало.',
      'Пользователь ожидал увидеть расписание, оценки.',
      'Но вместо этого перед ним красовалась лишь ошибка 404.',
      'И вот что странно: пользователь всё ещё здесь.',
      'Хотя эта страница совершенно не знает, зачем он пришёл.'] },
]

// Отсечки от момента открытия страницы, миллисекунды.
const SHAKE_AT = 350        // цифра начинает дёргаться
const SHAKE_MS = 3800       // сколько дёргается
const SWITCH_AT = 13000     // 404 -> 427, ровно за две секунды до речи
const SPEECH_AT = 15000     // рассказчик заговорил

const line = ref('')
let audio = null, timers = [], cancelReady = null

onMounted(() => {
  const at = (ms, fn) => { timers.push(setTimeout(fn, ms)) }
  // Цифру на странице 404 подменяем ПО МЕСТУ: сцена не рисует свою, иначе на экране
  // оказались бы две — настоящая под оверлеем и наша поверх.
  const code = document.querySelector('[data-404-code]')

  if (code) {
    at(SHAKE_AT, () => {
      code.dataset.glitch = code.textContent
      code.classList.add('gb-glitch-bw')
    })
    at(SHAKE_AT + SHAKE_MS, () => {
      code.classList.remove('gb-glitch-bw')
    })
    // Короткий срыв ПРИКРЫВАЕТ подмену: цифра, меняющаяся на спокойном экране, читается
    // как опечатка, а меняющаяся в глитче — как то, чем она и является.
    at(SWITCH_AT, () => {
      code.dataset.glitch = '427'
      code.classList.add('gb-glitch-bw')
      code.textContent = '427'
    })
    at(SWITCH_AT + 700, () => {
      code.classList.remove('gb-glitch-bw')
      code.removeAttribute('data-glitch')
    })
  }

  at(SPEECH_AT, () => {
    const v = VARIANTS[Math.floor(Math.random() * VARIANTS.length)]
    const n = 1 + Math.floor(Math.random() * v.files)
    audio = new Audio('/easter/snd/narrator-' + v.key + '-' + n + '.m4a')
    audio.volume = 0.7
    audio.play().catch(() => {})
    // ⚠️ Текст раскладывается по длительности файла, но САМ ФАКТ показа от звука не
    // зависит: `whenAudioReady` вызовет `start` и без метаданных (запасной срок), а
    // автовоспроизведение браузер может запретить вовсе — на свежей странице жеста ещё
    // не было. Пасхалка обязана читаться и полностью беззвучной.
    const start = () => {
      const total = (audio.duration && isFinite(audio.duration)) ? audio.duration : 12
      let acc = 0
      v.lines.forEach((t) => {
        at(acc * 1000, () => { line.value = t })
        acc += total / v.lines.length
      })
      at(acc * 1000 + 600, async () => {
        line.value = ''
        await easter.claim('stanley_parable_404')
        emit('close')
      })
    }
    cancelReady = whenAudioReady(audio, start)
  })
})

onBeforeUnmount(() => {
  timers.forEach(clearTimeout)
  if (cancelReady) cancelReady()
  if (audio) audio.pause()
})
</script>

<template>
  <p v-if="line" class="pointer-events-none fixed inset-x-[8%] bottom-[9%] z-[90] text-center
                        text-sm leading-relaxed text-text"
     style="text-shadow:0 1px 8px var(--gb-bg)">{{ line }}</p>
</template>
