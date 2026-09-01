<script setup>
/**
 * PublicSchedule.vue — расписание БЕЗ ВХОДА В АККАУНТ.
 *
 * 🔥 ЗАЧЕМ (01.09.2026, прямая просьба Ярослава): «из акка вылетело, надо быстро чекнуть
 * расписание, а его нет — бесит». Так и было: истёк токен → клиент чистит сессию и
 * выбрасывает на экран входа, а вместе с кабинетом исчезает и расписание. При этом
 * расписание — ОБЩЕДОСТУПНАЯ информация: оно берётся с публичного портала ВСГУТУ, где
 * его видит кто угодно без всякого входа. Требовать токен там, где он ничего не
 * защищает, — значит забирать у человека то, что и так открыто.
 *
 * ⚠️ ЗДЕСЬ НЕТ И НЕ ДОЛЖНО БЫТЬ НИ ОДНОЙ СТРОКИ ИЗ ЖУРНАЛА: ни оценок, ни посещаемости,
 * ни списков студентов. Ровно та же граница, что на сервере (`routers/publicschedule.py`,
 * см. предупреждение в его шапке). Появится соблазн «показать тут же средний балл» —
 * это будет утечка, а не удобство.
 *
 * ⚠️ Выбранная группа запоминается локально: человек, вылетевший из аккаунта, открывает
 * эту страницу ради одного конкретного расписания — своего, — и заставлять его каждый раз
 * искать группу в списке значит сделать страницу бесполезной ровно в тот момент, когда
 * она нужна быстро.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { publicScheduleApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import HexBackground from '@/components/HexBackground.vue'
import { ArrowLeft, CalendarDays, Search } from '@lucide/vue'

const locale = useLocaleStore()
const router = useRouter()

const LS_GROUP = 'gb.public.group'

const group = ref('')
const query = ref('')
const data = ref(null)
const week = ref(null)
const loading = ref(false)
const error = ref('')

try {
  group.value = localStorage.getItem(LS_GROUP) || ''
} catch {
  //Приватный режим — просто попросим ввести группу.
}

const days = computed(() => {
  const src = data.value?.days
  if (!src) return []
  //Сервер отдаёт дни объектом «день → пары». Порядок задаём сами: у объекта его нет,
  //а «суббота перед вторником» в расписании выглядит поломкой.
  const order = ['Пнд', 'Втр', 'Срд', 'Чтв', 'Птн', 'Сбт']
  return order
    .filter((d) => Array.isArray(src[d]) && src[d].length)
    .map((d) => ({ day: d, pairs: src[d] }))
})

async function load() {
  const g = query.value.trim() || group.value.trim()
  if (!g) return
  loading.value = true
  error.value = ''
  try {
    const { data: resp } = await publicScheduleApi.group(g)
    if (!resp?.available) {
      //«Группы не нашли» и «сервер недоступен» — разные события, и человеку важно
      //различать: в первом случае он поправит название, во втором подождёт.
      error.value = locale.t('publicSchedule.notFound', 'Группа не найдена. Проверьте название.')
      data.value = null
      return
    }
    data.value = resp
    group.value = g
    try {
      localStorage.setItem(LS_GROUP, g)
    } catch {
      //Не сохранилось — не беда, введёт снова.
    }
  } catch {
    error.value = locale.t('publicSchedule.offline',
      'Не удалось получить расписание. Проверьте связь.')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  //Номер недели — тем же публичным маршрутом. Без него расписание читается неверно:
  //у чётной и нечётной недели пары разные.
  try {
    week.value = (await publicScheduleApi.week()).data
  } catch {
    //Не показываем номер недели — это подпись, а не содержимое.
  }
  if (group.value) load()
})

watch(group, (g) => { if (g) query.value = g }, { immediate: true })
</script>

<template>
  <div class="relative min-h-dvh bg-bg text-text">
    <HexBackground />

    <div class="relative mx-auto w-full max-w-3xl px-4 py-6">
      <!-- Выход отсюда обязателен: страницу открывают с экрана входа, и без кнопки
           «назад» человек в мобильном приложении оказывается в тупике — тот же дефект,
           что был у политики ПДн и соглашения. -->
      <button type="button" @click="router.push('/login')"
              class="mb-4 inline-flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm font-semibold text-accent hover:underline">
        <ArrowLeft class="size-4" />
        {{ locale.t('publicSchedule.back', 'К входу в журнал') }}
      </button>

      <h1 class="flex items-center gap-2 font-title text-2xl font-bold">
        <CalendarDays class="size-6 text-accent" />
        {{ locale.t('publicSchedule.title', 'Расписание') }}
      </h1>
      <p class="mt-1 text-sm text-text3">
        {{ locale.t('publicSchedule.subtitle', 'Открыто без входа в журнал — как и на портале ВСГУТУ.') }}
        <span v-if="week?.parity"> · {{ week.parity === 1
          ? locale.t('publicSchedule.weekOdd', 'неделя I')
          : locale.t('publicSchedule.weekEven', 'неделя II') }}</span>
      </p>

      <form class="mt-4 flex gap-2" @submit.prevent="load">
        <input v-model="query" type="text" inputmode="text" autocomplete="off"
               :placeholder="locale.t('publicSchedule.groupPlaceholder', 'Группа, например К74/1')"
               class="h-11 min-w-0 flex-1 rounded-lg border border-border2 bg-card px-3 text-base text-text outline-none focus:border-accent" />
        <button type="submit" :disabled="loading || !query.trim()"
                class="inline-flex h-11 items-center gap-2 rounded-lg bg-accent px-4 font-semibold text-white disabled:opacity-50">
          <Search class="size-4" />
          {{ loading ? locale.t('publicSchedule.loading', 'Ищем…') : locale.t('publicSchedule.show', 'Показать') }}
        </button>
      </form>

      <p v-if="error" class="mt-3 rounded-lg border border-red/40 bg-red/10 px-3 py-2 text-sm text-red">
        {{ error }}
      </p>

      <div v-if="data && !error" class="mt-5 space-y-4">
        <p class="text-sm font-semibold text-text2">{{ data.group }}</p>

        <section v-for="d in days" :key="d.day"
                 class="overflow-hidden rounded-xl border border-border bg-card">
          <h2 class="border-b border-border bg-card2 px-3 py-2 text-sm font-bold text-text">
            {{ d.day }}
          </h2>
          <ul>
            <li v-for="(p, i) in d.pairs" :key="i"
                class="flex items-start gap-3 border-b border-border/50 px-3 py-2.5 last:border-0">
              <span class="w-14 shrink-0 text-sm font-bold text-accent">{{ p.time || '—' }}</span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-semibold text-text">{{ p.subject || '—' }}</span>
                <span v-if="p.kind || p.teacher" class="block text-xs text-text3">
                  {{ [p.kind, p.teacher].filter(Boolean).join(' · ') }}
                </span>
              </span>
              <span v-if="p.room" class="shrink-0 text-xs font-semibold text-text3">{{ p.room }}</span>
            </li>
          </ul>
        </section>

        <p v-if="!days.length" class="rounded-xl border border-border bg-card px-3 py-6 text-center text-sm text-text3">
          {{ locale.t('publicSchedule.empty', 'На этой неделе пар нет.') }}
        </p>
      </div>
    </div>
  </div>
</template>
