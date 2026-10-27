<script setup>
/**
 * GifImage.vue — гифка в ленте с ЗАРЕЗЕРВИРОВАННЫМ местом.
 *
 * Зачем. У `<img>` без указанных размеров высота до загрузки равна нулю: на месте гифки
 * пустота, а когда файл доезжает — лента дёргается, и строчка, которую человек в этот
 * момент читал, уезжает вниз. Гифки с CDN весят сотни килобайт, то есть пауза заметная
 * и на быстрой сети.
 *
 * Почему квадрат, а не точный размер. В сообщении лежит ТОЛЬКО ссылка на CDN Klipy
 * (`Message.body`), ширины и высоты там нет и не было никогда — значит, для уже
 * отправленных гифок настоящую пропорцию взять неоткуда. Квадрат — самая частая форма
 * стикера-реакции, и он ближе к правде, чем ноль. Резерв снимается в момент загрузки,
 * когда браузер уже знает настоящие размеры: дальше картинка стоит в потоке как обычно.
 *
 * Ошибка загрузки показывается явно. Иначе неудачная гифка навсегда остаётся чёрным
 * прямоугольником, неотличимым от «ещё грузится», и человек ждёт того, что не придёт.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useLocaleStore } from '@/stores/locale'
import { gifPosterSrc, gifVideoSrc, mediaSrc, playMuted, watchInView } from '@/utils/mediaSrc'

const props = defineProps({
  src: { type: String, required: true },
  alt: { type: String, default: 'GIF' },
})

const locale = useLocaleStore()
const state = ref('loading') // loading | ok | error
//Роликом MP4, а не GIF: тот же ролик в десятки раз легче (utils/mediaSrc.js::gifVideoSrc).
//Ролик не открылся — показываем прежнюю картинку, а не ошибку.
//Сначала первый кадр, ролик — когда до гифки долистали; вне экрана он на паузе.
const video = computed(() => gifVideoSrc(props.src))
const poster = computed(() => gifPosterSrc(props.src))
const videoFailed = ref(false)
const box = ref(null)
const videoEl = ref(null)
const seen = ref(false)
let unwatch = () => {}
onMounted(() => {
  unwatch = watchInView(box.value, (visible) => {
    if (visible) seen.value = true
    const v = videoEl.value
    if (!v) return
    if (visible) v.play?.()?.catch?.(() => {})
    else v.pause?.()
  })
})
onBeforeUnmount(() => unwatch())
</script>

<template>
  <span ref="box" class="gb-gif" :class="'gb-gif--' + state">
    <img
      v-if="video && !videoFailed && !seen"
      :src="poster"
      :alt="alt"
      decoding="async"
      class="gb-gif__img max-h-64 max-w-full rounded-lg"
      @load="state = 'ok'"
    />
    <video
      v-else-if="video && !videoFailed"
      ref="videoEl"
      :src="video"
      :poster="poster"
      :aria-label="alt"
      autoplay muted loop playsinline disablepictureinpicture
      preload="auto"
      class="gb-gif__img max-h-64 max-w-full rounded-lg"
      @loadeddata="state = 'ok'"
      @canplay="playMuted"
      @error="videoFailed = true"
    />
    <img
      v-else
      :src="mediaSrc(src)"
      :alt="alt"
      decoding="async"
      loading="lazy"
      class="gb-gif__img max-h-64 max-w-full rounded-lg"
      @load="state = 'ok'"
      @error="state = 'error'"
    />
    <span v-if="state === 'error'" class="gb-gif__err">
      {{ locale.t('gif.failed', 'GIF не загрузилась') }}
    </span>
  </span>
</template>

<style scoped>
.gb-gif {
  position: relative;
  display: block;
  width: fit-content;
}

/* Резерв места: тёмный квадрат вместо пустоты. Пока не загрузилось — сама картинка
   растянута по этому квадрату и прозрачна, поэтому геометрию задаёт только резерв. */
.gb-gif--loading,
.gb-gif--error {
  width: 200px;
  height: 200px;
  overflow: hidden;
  border-radius: 0.5rem;
  background: #0b0b10;
}

.gb-gif--loading .gb-gif__img,
.gb-gif--error .gb-gif__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  max-height: none;
  opacity: 0;
}

/* Дыхание подсказывает, что процесс идёт, — статичный чёрный квадрат неотличим от
   сломанной картинки. */
.gb-gif--loading::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 20%, rgba(255, 255, 255, 0.07) 50%, transparent 80%);
  animation: gb-gif-pulse 1.4s ease-in-out infinite;
}

@keyframes gb-gif-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

.gb-gif__err {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 0 0.5rem;
  font-size: 11px;
  line-height: 1.3;
  color: rgba(255, 255, 255, 0.65);
  text-align: center;
}

@media (prefers-reduced-motion: reduce) {
  .gb-gif--loading::after {
    animation: none;
  }
}
</style>
