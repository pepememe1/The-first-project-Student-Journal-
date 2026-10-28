<script setup>
// StudentDashboard — «Главная» студента (порт ui/dashboards.py _build_dash):
// заголовок, «Умный совет» (много советов, ротация), маскот-эмоция ПО ФАКТАМ
// (грустный при среднем <3 / многих пропусках; спокойный 3–4; радостный ≥4),
// карточки статистики, проактивные инсайты и список предметов.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { RotateCw } from '@lucide/vue'
import { studentApi, consentApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import ZetProgress from '@/components/ui/ZetProgress.vue'
import Mascot from '@/components/Mascot.vue'
import InsightCards from '@/components/InsightCards.vue'
import ParentConsent from '@/components/ParentConsent.vue'
import { dashboardEmote, preloadMascots } from '@/config/mascot'
import { useLocaleStore } from '@/stores/locale'
import { useDelayedFlag } from '@/composables/useDelayedFlag'
import GbIcon from '@/components/ui/GbIcon.vue'

const locale = useLocaleStore()

const loading = ref(true)
const data = ref(null)
const insights = ref([])
const zet = ref(null)   // docs/done/PLAN-ZET.md — null/subjects:[] → строка ЗЕТ не рендерится
const consentLinks = ref(null)

//Три ответа — разом и показ одним кадром (28.10.2026). Раньше они шли друг за другом и
//рисовались по мере прихода: советы вставали над уже показанными карточками, ЗЕТ — между
//ними, и страница прыгала (замер на стенде: сдвиг макета 0.03, список на 200 мс позже).
//Сбой второстепенного ответа не держит страницу: его блок просто не появится.
async function load() {
  loading.value = true
  const [o, i, z, c] = await Promise.allSettled([
    studentApi.overview(), studentApi.insights(), studentApi.zet(), consentApi.links(),
  ])
  data.value = o.status === 'fulfilled' ? o.value.data : null
  insights.value = i.status === 'fulfilled' ? (i.value.data.cards || []) : []
  zet.value = z.status === 'fulfilled' ? z.value.data : null
  //Сбой заявок — null: тогда ParentConsent попробует загрузить их сам, как раньше.
  consentLinks.value = c.status === 'fulfilled' ? (c.value.data.links || []) : null
  loading.value = false
}
//Скелет — только если ответ задержался: быстрый ответ показывает страницу сразу готовой.
const showSkeleton = useDelayedFlag(loading)
onMounted(() => {
  //Позы маскота — параллельно с данными: к показу нужная уже в кэше, без подмены картинки.
  preloadMascots()
  load()
})

const avg = computed(() => Number(data.value?.average ?? 0))
const debts = computed(() => Number(data.value?.debts ?? 0))
const attendance = computed(() => Number(data.value?.attendance ?? 100))
// Мало занятий — процент ненадёжен: сервер считает интервал Уилсона и говорит, широк ли
// он (исследование 20.10.2026). Подпись вместо скрытия: факт показываем всегда.
const attendanceHint = computed(() =>
  data.value?.attendance_uncertain
    ? locale.t('studentDashboard.attendanceFewData', { n: data.value.attendance_pairs })
    : '')

// Поза Вектора — строго по фактам (не по клику). Низкая посещаемость трактуется как
// «много пропусков» для эмоции.
const sprite = computed(() =>
  dashboardEmote({ average: avg.value, absences: attendance.value < 80 ? 20 : 0 }))

// «Умный совет» — КОНКРЕТНО про ситуацию студента (что делать), а не про приложение.
// Плохо → «посещай пары, отвечай, делай домашку, закрой долги»; хорошо → короткая
// похвала. Советы ротируются, если их несколько.
const TIPS = computed(() => {
  if (!data.value) return [locale.t('studentDashboard.tipLoading', 'Загрузка…')]
  const t = []
  const low = attendance.value < 85
  const weak = avg.value > 0 && avg.value < 3
  const mid = avg.value >= 3 && avg.value < 4
  if (debts.value) t.push(locale.t('studentDashboard.tipDebts', { n: debts.value }))
  if (low) t.push(locale.t('studentDashboard.tipLowAttendance', { pct: attendance.value }))
  if (weak) {
    t.push(locale.t('studentDashboard.tipWeak1', 'Средний ниже 3 — активнее отвечай на парах и разбирай сложные темы, не копи пробелы.'))
    t.push(locale.t('studentDashboard.tipWeak2', 'Делай домашние задания регулярно — это самый быстрый способ поднять оценки.'))
  } else if (mid) {
    t.push(locale.t('studentDashboard.tipMid', 'Средний в норме, но до отличного немного не хватает — чуть активнее на парах и с домашкой.'))
  }
  if (!t.length) t.push(avg.value >= 4
    ? locale.t('studentDashboard.tipGoodDefault', 'У тебя всё хорошо — так держать! 👍')
    : locale.t('studentDashboard.tipNeutralDefault', 'Начни набирать оценки на практиках — и средний пойдёт вверх.'))
  return t
})
const tipI = ref(0)
const tip = computed(() => TIPS.value[tipI.value % TIPS.value.length])
function nextTip() { tipI.value++ }

/**
 * 🔥 СОВЕТ БОЛЬШЕ НЕ УБЕГАЕТ ИЗ-ПОД ЧИТАЮЩЕГО (UX-аудит 17.10.2026). Было: смена раз в
 * девять секунд, безусловно. Совет — связный текст в две строки; девяти секунд мало
 * тому, кто читает медленно, а догнать пропавший текст нечем: кнопка листает ВПЕРЁД, и
 * вернуться к предыдущему нельзя. Теперь три вещи:
 *
 * ⚠️ 1. Пауза, пока на карточке курсор или фокус с клавиатуры. Человек, который читает,
 * обычно держит на тексте указатель — и это единственный доступный признак «читают
 * прямо сейчас». Чтение с телефона прокруткой пауза не ловит, и честно: там спасает
 * увеличенный срок.
 * ⚠️ 2. Срок 9 → 20 секунд. Совет — не бегущая строка, он не обязан мелькать.
 * ⚠️ 3. При `prefers-reduced-motion: reduce` самосмены НЕТ вовсе: человек, попросивший
 * систему не двигать ничего само, получил бы ровно обратное. Кнопка остаётся.
 */
const TIP_ROTATE_MS = 20000
const tipsPaused = ref(false)
let tipTimer = null

function motionReduced() {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

onMounted(() => {
  if (motionReduced()) return
  tipTimer = setInterval(() => {
    if (data.value && !tipsPaused.value) tipI.value++
  }, TIP_ROTATE_MS)
})
onBeforeUnmount(() => clearInterval(tipTimer))
</script>

<template>
  <!-- Один корень: переход страниц в AppShell работает только с ним (pageSingleRoot.test). -->
  <div>
  <!-- Скелет той же раскладки — только если ответ задержался дольше 150 мс; иначе пусто
       эти доли секунды, и страница проявляется сразу готовой (см. load()). -->
  <div v-if="loading && showSkeleton" class="space-y-3 sm:space-y-5" aria-busy="true">
    <div class="flex items-center gap-3">
      <div class="gb-skeleton aspect-[3/4] w-14 shrink-0 rounded-lg lg:hidden" />
      <div class="min-w-0 flex-1 space-y-2">
        <div class="gb-skeleton h-6 w-56 max-w-full rounded" />
        <div class="gb-skeleton h-4 w-40 max-w-full rounded" />
      </div>
    </div>
    <div class="h-px bg-border" />
    <div class="gb-skeleton h-24 rounded-lg" />
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(190px,240px)_1fr] xl:grid-cols-[minmax(300px,380px)_1fr]">
      <div class="hidden justify-center lg:flex">
        <div class="gb-skeleton aspect-[3/4] w-full max-w-[190px] rounded-2xl lg:max-w-[320px] xl:max-w-[380px]" />
      </div>
      <div class="flex min-w-0 flex-col gap-4 sm:gap-5">
        <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <div v-for="i in 4" :key="i" class="gb-skeleton h-[84px] rounded-lg sm:h-[104px]" />
        </div>
        <div class="space-y-1.5 sm:space-y-2">
          <div class="gb-skeleton mb-3 h-6 w-40 rounded" />
          <div v-for="i in 5" :key="i" class="gb-skeleton h-11 rounded-md sm:h-12" />
        </div>
      </div>
    </div>
  </div>
  <div v-else-if="!loading" class="gb-reveal space-y-3 sm:space-y-5">
    <!-- ⚠️ На ТЕЛЕФОНЕ маскот стоит МЕЛКИМ в одной строке с именем, а не отдельным
         блоком: в прежней раскладке (общая сетка, где на узком экране колонки просто
         становятся строками) тигр занимал 250 px прямо под шапкой, и до собственно
         данных — оценок, пропусков, долгов — приходилось прокручивать полэкрана
         (живой отзыв 3.6: «всё как на десктопе, ничего не влазит»). На lg+ он
         возвращается на своё место крупным планом — там место есть. -->
    <div class="flex items-center gap-3">
      <Mascot :sprite="sprite" class="aspect-[3/4] w-14 shrink-0 lg:hidden" />
      <div class="min-w-0">
        <h2 class="truncate font-title text-xl font-extrabold text-text sm:text-2xl">{{ data?.name || '—' }}</h2>
        <!-- Курс рядом с группой. Показываем, ТОЛЬКО когда сервер его знает (год
             поступления группы задан): «1 курс» наугад хуже, чем его отсутствие. -->
        <p class="mt-0.5 truncate text-sm text-text3">
          {{ locale.t('studentDashboard.groupLabel', { group: data?.group || '—' }) }}<span
            v-if="data?.course"> · {{ locale.t('adminGroups.courseN', { n: data.course }) }}</span>
        </p>
      </div>
    </div>
    <div class="h-px bg-border" />

    <!-- Умный совет: много советов, ротация; кнопка — следующий -->
    <!-- Пауза самосмены — на всей карточке, а не на самом тексте: курсор человека чаще
         стоит рядом со строкой, чем точно на ней. -->
    <div class="rounded-lg border p-3 sm:p-4" style="background: var(--gb-accent-glow); border-color: color-mix(in srgb, var(--gb-accent) 20%, transparent);"
         @mouseenter="tipsPaused = true" @mouseleave="tipsPaused = false"
         @focusin="tipsPaused = true" @focusout="tipsPaused = false">
      <div class="mb-1 flex items-center justify-between">
        <p class="flex items-center gap-1.5 text-sm font-bold text-accent"><GbIcon name="tip" class="size-4 shrink-0" />{{ locale.t('studentDashboard.smartTip', 'Умный совет') }}</p>
        <!-- 44 px — общепринятая цель для пальца; было 28×28 (UX-аудит 17.10.2026).
             Сама иконка прежнего размера, растёт только область нажатия. -->
        <button class="grid min-h-11 min-w-11 shrink-0 place-items-center rounded-md border border-accent/25 text-accent hover:bg-accent-glow"
                :title="locale.t('studentDashboard.nextTip', 'Следующий совет')" @click="nextTip">
          <RotateCw class="size-3.5" />
        </button>
      </div>
      <p class="text-sm text-text">{{ tip }}</p>
    </div>

    <!-- Маскот слева крупным планом; справа — инсайты, статы и предметы ОДНОЙ колонкой,
         поэтому плашки рисков/долгов встают вровень со статами. -->
    <!-- ⚠️ `grid-cols-1` НА ТЕЛЕФОНЕ ОБЯЗАТЕЛЕН — это не «на всякий случай», а починка
         бага «на телефоне всё вылезает за экран». Без него на узком экране у сетки нет
         НИ ОДНОЙ явной колонки, и браузер заводит НЕЯВНУЮ дорожку размера `auto`. Такая
         дорожка обязана вместить минимальный размер содержимого — и если внутри найдётся
         хоть один неразрывный кусок шире экрана (длинная ссылка, слитный перечень
         предметов в карточке риска), дорожка РАСТЯГИВАЕТСЯ под него. Растягивается при
         этом вся колонка целиком: карточки статистики, ЗЕТ и список предметов становятся
         шириной с самый широкий кусок и уезжают за правый край — ровно то, что на
         скриншотах. `grid-cols-1` разворачивается в `minmax(0, 1fr)`, где нижняя граница
         НОЛЬ: колонка больше не может стать шире контейнера ни при каком содержимом, а
         виноватый кусок переполняет только свою карточку. -->
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(190px,240px)_1fr] xl:grid-cols-[minmax(300px,380px)_1fr]">
      <!-- items-start, НЕ items-center: правая колонка высокая (заявки родителей +
           инсайты + статы + предметы), и центрирование по всей её высоте утаскивало
           тигра вниз, вровень со статами, а не сразу под «Умным советом» (живой баг). -->
      <div class="hidden items-start justify-center lg:flex">
        <!-- Тигр во всю ширину колонки; пропорции спрайта 3:4 (460×613) — без пустот. -->
        <Mascot :sprite="sprite" class="aspect-[3/4] w-full max-w-[190px] lg:max-w-[320px] xl:max-w-[380px]" />
      </div>

      <!-- min-w-0: у элемента сетки минимальный размер по умолчанию равен размеру его
           содержимого, и без этого он не даёт колонке сжаться даже при `minmax(0,1fr)` -->
      <div class="flex min-w-0 flex-col gap-4 sm:gap-5">
        <!-- Заявки родителей на доступ к журналу. Стоит ВЫШЕ статистики намеренно: это
             решение о собственных персональных данных, и его нельзя прятать в подвал.
             Заявки грузит load() вместе с остальным — блок появляется в том же кадре. -->
        <ParentConsent :initial="consentLinks" />
        <InsightCards :cards="insights" />
        <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <StatCard :label="locale.t('studentDashboard.subjectsCount', 'Предметов')" :value="data?.subjects_count ?? '—'" accent />
          <StatCard :label="locale.t('studentDashboard.averageLabel', 'Средний балл')" :value="data?.average || '—'" />
          <StatCard :label="locale.t('studentDashboard.attendanceLabel', 'Посещаемость')" :value="data ? data.attendance + '%' : '—'" :hint="attendanceHint" />
          <StatCard :label="locale.t('studentDashboard.gradesLabel', 'Оценок')" :value="data?.grades_total ?? '—'" />
        </div>

        <!-- ЗЕТ (docs/done/PLAN-ZET.md) — только если хотя бы один предмет его имеет. -->
        <div v-if="zet?.subjects?.length" class="rounded-lg border border-border bg-card p-4 shadow-card">
          <!-- min-zet передаётся ОБЯЗАТЕЛЬНО: без него полоса всегда красится «хорошо»
               (см. ZetProgress: «без порога — всегда accent»), и студент видит свой
               баланс без единого ограничения рядом. Сервер отдавал это поле с самого
               появления ЗЕТ и прямо обещал в докстринге «для „до перевода: X ЗЕТ“ в
               дашборде», но страница его не читала — обещание не выполнялось ни разу. -->
          <ZetProgress :earned="zet.earned" :total="zet.total" :min-zet="zet.min_zet"
                       :pending="zet.pending" :subjects="zet.subjects" show-details />
        </div>

        <div>
          <h3 class="mb-2 font-title text-base font-bold text-text sm:mb-3 sm:text-lg">{{ locale.t('studentDashboard.mySubjectsTitle', 'Мои предметы') }}</h3>
          <p v-if="!data?.subjects?.length" class="text-sm text-text3">{{ locale.t('studentDashboard.noSubjects', 'Предметов пока нет.') }}</p>
          <ul v-else class="space-y-1.5 sm:space-y-2">
            <li v-for="s in data.subjects" :key="s.subject"
                class="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2.5 shadow-card sm:px-4 sm:py-3">
              <span class="min-w-0 truncate text-sm font-semibold text-text">{{ s.subject }}</span>
              <span class="shrink-0 text-xs text-text3">{{ locale.t('studentDashboard.gradesCount', { n: s.grades }) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
  </div>
</template>
