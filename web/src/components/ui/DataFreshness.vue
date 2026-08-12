<script setup>
// DataFreshness — подпись «Обновлено вчера в 18:20» под данными, которые могли приехать
// из сохранённой копии.
//
// Зачем. Без сети экран показывает последний удачный ответ и выглядит РОВНО ТАК ЖЕ, как
// свежий. Студент смотрит на оценки и не знает, что они позавчерашние; преподаватель
// сверяется с расписанием, которое успели поменять. Это худший вид неправды: она
// правдоподобна, и потому её не перепроверяют.
//
// Показываем ТОЛЬКО когда есть что сказать: данные из кэша и им больше минуты. Подпись
// под каждым свежим экраном была бы шумом и перестала бы читаться ровно тогда, когда
// действительно понадобится.
import { computed } from 'vue'

import { cacheVersion, cachedAt, findCached } from '@/api/offlineCache'
import { online } from '@/api/offlineSession'
import { useLocaleStore } from '@/stores/locale'
import { freshness } from '@/utils/freshness'

const props = defineProps({
  // Путь запроса и его параметры — ровно те, с которыми экран ходил на сервер:
  // ключ кэша складывается из них, и разойдись они, подпись молча показывала бы
  // время ЧУЖОГО запроса, что хуже её отсутствия.
  url: { type: String, required: true },
  params: { type: Object, default: () => ({}) },
})

const locale = useLocaleStore()

const at = computed(() => {
  // cacheVersion упомянут НАМЕРЕННО: он двигается на каждой записи в кэш и заставляет
  // подпись пересчитаться. Время лежит в localStorage, за которым Vue не следит.
  void cacheVersion.value
  const exact = cachedAt({ url: props.url, params: props.params })
  if (exact) return exact
  // Точного совпадения нет — берём самый свежий сохранённый ответ с этим путём. Так
  // сделано ради расписания: оно запрашивается то с группой, то с категорией портала,
  // и требовать от страницы повторить набор параметров один в один значило бы завести
  // второе место, где они собираются, — оно однажды разошлось бы с первым, и подпись
  // молча исчезла бы именно там, где нужнее всего.
  return findCached(props.url)?.t || 0
})

const info = computed(() => freshness(at.value))

// Свежие данные не подписываем: «обновлено только что» на онлайн-экране — шум.
const visible = computed(() => at.value > 0 && (!online.value || info.value.kind !== 'now'))

const text = computed(() => {
  const f = info.value
  const when = f.kind === 'now' ? locale.t('freshness.now', 'только что')
    : f.kind === 'minutes' ? locale.t('freshness.minutes', '{n} мин назад', { n: f.n })
      : f.kind === 'today' ? locale.t('freshness.today', 'в {time}', { time: f.time })
        : f.kind === 'yesterday' ? locale.t('freshness.yesterday', 'вчера в {time}', { time: f.time })
          : locale.t('freshness.date', '{date} в {time}', { date: f.date, time: f.time })
  return locale.t('offline.updated', 'Обновлено {when}', { when })
})
</script>

<template>
  <p v-if="visible" class="text-[11px] leading-none" :class="online ? 'text-text3' : 'text-yellow'">
    {{ text }}
  </p>
</template>
