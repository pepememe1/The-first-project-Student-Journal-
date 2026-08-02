<script setup>
// AdminScheduleIssues — центр проблем расписания: накладки преподавателей и аудиторий.
//
// Накладка = один преподаватель (или одна аудитория) занят в один слот у РАЗНЫХ групп.
// Совместная лекция двум группам — законна, поэтому такой слот помечается кнопкой и
// из списка уходит.
//
// ⚠️ Список ВЫЧИСЛЯЕТСЯ сервером на лету, а не копится письмами. Если бы каждая проверка
// создавала уведомление, одна незакрытая накладка за неделю превратилась бы в сотню
// одинаковых записей, и центр проблем перестали бы открывать.
import { ref, computed, onMounted } from 'vue'
import { AlertTriangle, CheckCircle2, Users, DoorClosed, Loader } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const toast = useToast()
const locale = useLocaleStore()
const items = ref([])
const building = ref(false)
const loading = ref(true)
const openedId = ref('')

const count = computed(() => items.value.length)

// Склонение слова «проблема» зависит от языка: у русского своя трёхформенная
// система (1 проблема / 2 проблемы / 5 проблем), у английского — просто
// единственное/множественное. Выбор формы делаем по активному языку, а САМИ
// слова берём из словаря — конкатенации между языками не будет.
const countText = computed(() => {
  const n = count.value
  let word
  if (locale.active === 'ru') {
    const ten = n % 10
    const hundred = n % 100
    if (ten === 1 && hundred !== 11) word = locale.t('adminScheduleIssues.problemsOne', 'проблема')
    else if (ten >= 2 && ten <= 4 && (hundred < 12 || hundred > 14)) word = locale.t('adminScheduleIssues.problemsFew', 'проблемы')
    else word = locale.t('adminScheduleIssues.problemsMany', 'проблем')
  } else {
    word = n === 1 ? locale.t('adminScheduleIssues.problemsOne', 'проблема') : locale.t('adminScheduleIssues.problemsMany', 'проблем')
  }
  return `${n} ${word}`
})

async function load() {
  loading.value = true
  try {
    const r = (await adminApi.scheduleConflicts()).data
    items.value = r.items || []
    building.value = !!r.building
  } catch {
    toast.error(locale.t('adminScheduleIssues.loadFailed', 'Не удалось проверить расписание'))
    items.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

function slotText(c) {
  return locale.t('adminScheduleIssues.slot', { week: c.week, day: c.day, pair: c.pair_no })
}

// Человеческое описание проблемы — именно оно раскрывается по клику. Два ПОЛНЫХ
// варианта фразы (не склейка кусков) — порядок слов у английского/китайского иной.
function problemText(c) {
  const where = slotText(c)
  const groups = c.groups.join(locale.t('adminScheduleIssues.and', ' и '))
  if (c.kind === 'teacher') {
    return locale.t('adminScheduleIssues.problemTeacher', { teacher: c.value, where, groups })
  }
  return locale.t('adminScheduleIssues.problemRoom', { room: c.value, where, groups })
}

async function markJoint(c) {
  try {
    await adminApi.setScheduleJoint({
      kind: c.kind, value: c.value, week: c.week, day: c.day, pair_no: c.pair_no,
      note: 'Совместная пара', // персистентная заметка на сервере — не UI-текст, не переводим
    })
    toast.success(locale.t('adminScheduleIssues.markedSuccess', 'Помечено как совместная пара'))
    await load()
  } catch {
    toast.error(locale.t('adminScheduleIssues.markFailed', 'Не удалось сохранить отметку'))
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Сводка: то самое «у вас N проблем по расписанию». -->
    <Card>
      <div class="flex items-center gap-3">
        <component :is="count ? AlertTriangle : CheckCircle2"
                   class="size-6 shrink-0" :class="count ? 'text-red' : 'text-accent'" />
        <div class="min-w-0">
          <p class="font-title text-lg font-extrabold" :class="count ? 'text-red' : 'text-text'">
            <template v-if="loading">{{ locale.t('adminScheduleIssues.checking', 'Проверяем расписание…') }}</template>
            <template v-else-if="count">{{ locale.t('adminScheduleIssues.summaryHasIssues', { count: countText }) }}</template>
            <template v-else-if="building">{{ locale.t('adminScheduleIssues.buildingTitle', 'Расписание ещё загружается') }}</template>
            <template v-else>{{ locale.t('adminScheduleIssues.noConflicts', 'Накладок не найдено') }}</template>
          </p>
          <p class="mt-0.5 text-sm text-text3">
            <template v-if="building">
              {{ locale.t('adminScheduleIssues.buildingHint', 'Снимок расписания с портала ещё собирается — проверка неполная. Обновите страницу через пару минут.') }}
            </template>
            <template v-else-if="count">
              {{ locale.t('adminScheduleIssues.hasIssuesHint', 'Один преподаватель или одна аудитория заняты в одно время у разных групп.') }}
            </template>
            <template v-else>{{ locale.t('adminScheduleIssues.noConflictsHint', 'Совпадений преподавателей и аудиторий нет.') }}</template>
          </p>
        </div>
        <AppButton class="ml-auto shrink-0" variant="ghost" @click="load">{{ locale.t('adminScheduleIssues.checkAgain', 'Проверить снова') }}</AppButton>
      </div>
    </Card>

    <Card v-if="count" :title="locale.t('adminScheduleIssues.listTitle', 'Список проблем')" :subtitle="locale.t('adminScheduleIssues.listHint', 'Нажмите на строку — покажем, в чём дело')">
      <ul class="divide-y divide-border">
        <li v-for="c in items" :key="c.id">
          <button type="button"
                  class="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-card2"
                  @click="openedId = openedId === c.id ? '' : c.id">
            <component :is="c.kind === 'teacher' ? Users : DoorClosed"
                       class="mt-0.5 size-4 shrink-0 text-red" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold text-red">
                {{ c.kind === 'teacher' ? locale.t('adminScheduleIssues.teacherDoubleBooked', 'Преподаватель занят дважды') : locale.t('adminScheduleIssues.roomDoubleBooked', 'Аудитория занята дважды') }}:
                {{ c.value }}
              </span>
              <span class="mt-0.5 block truncate text-tiny text-text3">
                {{ slotText(c) }} · {{ c.groups.join(', ') }}
              </span>
            </span>
          </button>

          <!-- Раскрытая проблема: что именно не так и что с этим делать. -->
          <div v-if="openedId === c.id" class="mb-3 ml-7 rounded-lg border border-red/30 bg-red/5 p-3">
            <p class="text-sm leading-relaxed text-text">{{ problemText(c) }}</p>
            <p v-if="c.subjects.length" class="mt-2 text-tiny text-text3">
              {{ locale.t('adminScheduleIssues.subjectsLabel', { subjects: c.subjects.join(', ') }) }}
            </p>
            <div class="mt-3">
              <AppButton variant="ghost" @click="markJoint(c)">
                {{ locale.t('adminScheduleIssues.markJoint', 'Это совместная пара — не считать ошибкой') }}
              </AppButton>
            </div>
          </div>
        </li>
      </ul>
    </Card>

    <Card v-else-if="building">
      <div class="flex items-center gap-3 text-sm text-text3">
        <Loader class="size-4 shrink-0 animate-spin" />
        {{ locale.t('adminScheduleIssues.buildingEmptyHint', 'Пока расписание не собрано, показывать нечего. Это не значит, что накладок нет.') }}
      </div>
    </Card>
  </div>
</template>
