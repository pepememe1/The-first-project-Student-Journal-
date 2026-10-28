// useDelayedFlag — «загрузка» видна, только если она длится дольше порога (28.10.2026).
//
// Ответ сервера часто приходит за 50–100 мс. Скелет, показанный на это время, мелькает и
// читается как подгрузка, которой без него никто бы не заметил. Флаг становится true,
// только если источник держится true дольше `ms`; падает сразу вместе с источником.
import { ref, watch, onBeforeUnmount } from 'vue'

export function useDelayedFlag(source, ms = 150) {
  const flag = ref(false)
  let timer = null
  const stop = watch(source, (on) => {
    clearTimeout(timer)
    if (!on) { flag.value = false; return }
    timer = setTimeout(() => { flag.value = true }, ms)
  }, { immediate: true })
  onBeforeUnmount(() => { clearTimeout(timer); stop() })
  return flag
}
