<script setup>
// Stanley Parable на странице 404.
//
// Страница открывается ОБЫЧНОЙ, с цифрой 404. Через пару секунд она подрагивает и
// становится 427 (отсылка к самой игре), и лишь потом начинается речь — пауза здесь
// часть шутки, а не задержка загрузки.
//
// Текстов три, озвучек семь: берём случайный текст и случайный файл из ЕГО пула.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
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

const line = ref('')
let audio = null, timers = []

onMounted(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))
  await wait(2500)
  // Цифру на странице 404 подменяем ПО МЕСТУ: сцена не рисует свою, иначе на экране
  // оказались бы две — настоящая под оверлеем и наша поверх.
  const code = document.querySelector('[data-404-code]')
  if (code) {
    // Отличительный знак рассказчика: у RDR2 своя карточка, а он приходит без картинки,
    // и отличить одну шутку от другой было нечем. Глитч МОНОХРОМНЫЙ — цветной уже занят
    // Cyberpunk, и повторять его палитру значило бы смешать две разные отсылки.
    code.dataset.glitch = code.textContent
    code.classList.add('gb-glitch-bw')
    await wait(1600)
    code.textContent = '427'
    code.dataset.glitch = '427'
    await wait(1400)
    code.classList.remove('gb-glitch-bw')
    code.removeAttribute('data-glitch')
  }
  await wait(2600)

  const v = VARIANTS[Math.floor(Math.random() * VARIANTS.length)]
  const n = 1 + Math.floor(Math.random() * v.files)
  audio = new Audio('/easter/snd/narrator-' + v.key + '-' + n + '.mp3')
  audio.volume = 0.7
  audio.play().catch(() => {})
  const start = () => {
    const total = (audio.duration && isFinite(audio.duration)) ? audio.duration : 12
    let acc = 0
    v.lines.forEach((t) => {
      timers.push(setTimeout(() => { line.value = t }, acc * 1000))
      acc += total / v.lines.length
    })
    timers.push(setTimeout(async () => {
      line.value = ''
      await easter.claim('stanley_parable_404')
      emit('close')
    }, acc * 1000 + 600))
  }
  audio.readyState > 0 ? start() : audio.addEventListener('loadedmetadata', start, { once: true })
})
onBeforeUnmount(() => { timers.forEach(clearTimeout); if (audio) audio.pause() })
</script>

<template>
  <p v-if="line" class="pointer-events-none fixed inset-x-[8%] bottom-[9%] z-[90] text-center
                        text-sm leading-relaxed text-text"
     style="text-shadow:0 1px 8px var(--gb-bg)">{{ line }}</p>
</template>
