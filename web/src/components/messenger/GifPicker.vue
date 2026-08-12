<script setup>
// GifPicker — выбор GIF из Klipy (как в Discord): домашний экран с плитками категорий
// (карточка-превью + подпись снизу, как в самом Discord/Klipy), при выборе — сетка
// превью с бесконечной подгрузкой, звезда «в избранное» по наведению на карточку, клик
// по GIF — отправка СРАЗУ (не «вставить в поле», а отправить, как в Discord).
//
// Категория — это просто ПОИСКОВЫЙ ЗАПРОС (Klipy отдаёт category.query, см.
// stores/gif.js) — отдельного «режима категории» на сервере нет, здесь это тоже
// просто предзаполненный поиск. У «Избранного»/«Популярных» своих превью с Klipy нет
// (это наши псевдокатегории) — плитка декоративная: цвет + иконка, а не выдуманная
// картинка. Настоящие категории показывают РЕАЛЬНЫЙ preview_url с Klipy.
import { ref, onMounted } from 'vue'
import { X, Search, Star, Flame, ChevronLeft } from '@lucide/vue'
import { useGifStore } from '@/stores/gif'
import { useLocaleStore } from '@/stores/locale'

// Оба пропса читает только шаблон (там они доступны по имени), поэтому результат
// defineProps никуда не присваиваем — иначе линтер справедливо ругается на мёртвую
// переменную.
defineProps({
  // Где показать окно. 'composer' — как было: приклеено к правому нижнему углу, над
  // кнопкой GIF в поле ввода. 'center' — по центру экрана: пикер зовут ещё и со
  // страницы «Профиль» (гифка на аватарку и на баннер), а там никакого поля ввода
  // внизу справа нет, и окно висело бы в пустом углу.
  anchor: { type: String, default: 'composer' },
  // Подпись в шапке. У выбора аватарки и баннера вопрос «что именно выбираем» не
  // праздный: диалог один и тот же, а результат ложится в разные места.
  title: { type: String, default: '' },
})
const emit = defineEmits(['pick', 'close'])
const gif = useGifStore()
const locale = useLocaleStore()

const FAVORITES = '__favorites__'

const view = ref('home')        // 'home' — плитки категорий, 'results' — сетка GIF
const query = ref('')
const activeKey = ref('')       // '' = тренды, FAVORITES = избранное, иначе query категории
const categories = ref([])
const items = ref([])
const loading = ref(false)
const page = ref(1)
const hasNext = ref(false)

onMounted(async () => {
  gif.load()
  try { categories.value = await gif.categories() } catch { categories.value = [] }
})

function goHome() {
  view.value = 'home'
  query.value = ''
  activeKey.value = ''
  items.value = []
}

async function loadTrending() {
  activeKey.value = ''
  query.value = ''
  view.value = 'results'
  loading.value = true
  page.value = 1
  try {
    const r = await gif.trending(1)
    items.value = r.items || []
    hasNext.value = !!r.has_next
  } catch { items.value = []; hasNext.value = false } finally { loading.value = false }
}

function showFavorites() {
  activeKey.value = FAVORITES
  query.value = ''
  view.value = 'results'
  items.value = gif.favorites
  hasNext.value = false
}

async function runSearch(q) {
  const forQuery = q
  loading.value = true
  page.value = 1
  try {
    const r = await gif.search(q, 1)
    //Запрос могли сменить, пока летел этот — устаревший ответ не подменяет текущий
    //(тот же приём, что при гонке категорий расписания).
    if (forQuery !== query.value.trim()) return
    items.value = r.items || []
    hasNext.value = !!r.has_next
  } catch {
    if (forQuery === query.value.trim()) { items.value = []; hasNext.value = false }
  } finally {
    if (forQuery === query.value.trim()) loading.value = false
  }
}

let searchTimer = null
function onSearchInput() {
  activeKey.value = ''
  clearTimeout(searchTimer)
  const q = query.value.trim()
  if (!q) { goHome(); return }
  view.value = 'results'
  searchTimer = setTimeout(() => runSearch(q), 350)
}

function pickCategory(cat) {
  query.value = cat.query
  activeKey.value = cat.query
  view.value = 'results'
  runSearch(cat.query)
}

async function loadMore() {
  if (!hasNext.value || loading.value || activeKey.value === FAVORITES) return
  const nextPage = page.value + 1
  loading.value = true
  try {
    const q = query.value.trim()
    const r = q ? await gif.search(q, nextPage) : await gif.trending(nextPage)
    items.value = [...items.value, ...(r.items || [])]
    hasNext.value = !!r.has_next
    page.value = nextPage
  } catch { /* подгрузка — не критично, просто останавливаемся на уже показанном */ }
  finally { loading.value = false }
}

function onScroll(e) {
  const el = e.target
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) loadMore()
}

function send(item) {
  emit('pick', item)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50" :class="anchor === 'center' ? 'grid place-items-center bg-black/40 p-4' : ''"
       @click="emit('close')">
    <div class="flex h-96 w-80 max-w-[calc(100vw-1rem)] flex-col
                overflow-hidden rounded-xl border border-border2 bg-card shadow-card"
         :class="anchor === 'center' ? 'max-h-[calc(100vh-2rem)]' : 'absolute bottom-16 right-2'" @click.stop>
      <p v-if="title" class="border-b border-border px-3 pt-2.5 pb-2 text-[11px] uppercase tracking-wide text-text3">
        {{ title }}
      </p>
      <div class="flex items-center gap-1 border-b border-border p-2">
        <button v-if="view === 'results'" type="button" @click="goHome" :aria-label="locale.t('gif.toCategories', 'К категориям')"
                class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2">
          <ChevronLeft class="size-4" />
        </button>
        <Search v-else class="size-4 shrink-0 text-text3" />
        <input v-model="query" @input="onSearchInput" :placeholder="locale.t('gif.searchPlaceholder', 'Поиск в Klipy…')"
               class="h-8 min-w-0 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-text3" />
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
                class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2">
          <X class="size-4" />
        </button>
      </div>

      <!-- Домашний экран — плитки, как в Discord: превью + подпись снизу. -->
      <div v-if="view === 'home'" class="min-h-0 flex-1 overflow-y-auto p-2">
        <div class="grid grid-cols-2 gap-2">
          <button type="button" @click="showFavorites"
                  class="group relative flex h-20 items-end overflow-hidden rounded-lg
                         bg-gradient-to-br from-accent/70 to-accent p-2">
            <Star class="absolute right-2 top-2 size-5 text-white/40" />
            <span class="text-sm font-semibold text-white">{{ locale.t('messenger.saved', 'Избранное') }}</span>
          </button>
          <button type="button" @click="loadTrending"
                  class="group relative flex h-20 items-end overflow-hidden rounded-lg bg-bg2 p-2">
            <Flame class="absolute right-2 top-2 size-5 text-text3" />
            <span class="text-sm font-semibold text-text">{{ locale.t('gif.trending', 'В тренде') }}</span>
          </button>
          <button v-for="c in categories" :key="c.query" type="button" @click="pickCategory(c)"
                  class="relative flex h-20 items-end overflow-hidden rounded-lg bg-bg2 p-2">
            <img v-if="c.preview_url" :src="c.preview_url" :alt="c.label" loading="lazy"
                 class="absolute inset-0 size-full object-cover" />
            <span class="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
            <span class="relative text-sm font-semibold capitalize text-white">{{ c.label }}</span>
          </button>
        </div>
        <p v-if="!categories.length" class="py-4 text-center text-xs text-text3">
          {{ locale.t('gif.categoriesUnavailable', 'Категории Klipy сейчас недоступны — попробуйте поиск или «В тренде».') }}
        </p>
      </div>

      <!-- Результаты — сетка превью (тренды/категория/поиск/избранное). -->
      <div v-else class="min-h-0 flex-1 overflow-y-auto p-2" @scroll="onScroll">
        <p v-if="loading && !items.length" class="py-8 text-center text-xs text-text3">{{ locale.t('notifications.loading', 'Загрузка…') }}</p>
        <p v-else-if="!items.length" class="py-8 text-center text-xs text-text3">
          {{ activeKey === FAVORITES ? locale.t('gif.noFavorites', 'Пока нет избранных GIF — наведите на любой и нажмите ⭐')
             : locale.t('gif.nothingFound', 'Ничего не нашлось') }}
        </p>
        <div v-else class="grid grid-cols-2 gap-1.5">
          <button v-for="it in items" :key="it.slug + it.id" type="button" @click="send(it)"
                  class="group relative overflow-hidden rounded-lg bg-bg2"
                  :style="{ aspectRatio: `${it.width || 1} / ${it.height || 1}` }">
            <img :src="it.thumb_url" :alt="it.title" loading="lazy" class="size-full object-cover" />
            <!-- Звезда — как в Discord: видна при наведении, всегда видна для уже избранного. -->
            <span role="button" tabindex="0" @click.stop="gif.toggleFavorite(it)"
                  :aria-label="gif.isFavorite(it.slug) ? locale.t('gif.removeFavorite', 'Убрать из избранного') : locale.t('gif.addFavorite', 'В избранное')"
                  class="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/50
                         opacity-0 transition-opacity group-hover:opacity-100 hover:bg-black/70"
                  :class="{ '!opacity-100': gif.isFavorite(it.slug) }">
              <Star class="size-3.5" :class="gif.isFavorite(it.slug) ? 'fill-yellow-400 text-yellow-400' : 'text-white'" />
            </span>
          </button>
        </div>
        <p v-if="loading && items.length" class="py-2 text-center text-xs text-text3">{{ locale.t('notifications.loading', 'Загрузка…') }}</p>
      </div>
    </div>
  </div>
</template>
