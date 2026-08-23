<script setup>
// StudentJournal — журнал студента (порт ui/dashboards.py, страница "journal").
// Занятия сгруппированы по предметам, у каждого — своя оценка и средний по предмету.
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { studentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SubjectLessons from '@/components/journal/SubjectLessons.vue'
import DataFreshness from '@/components/ui/DataFreshness.vue'
import JournalEggs from '@/components/easter/JournalEggs.vue'
import { useEasterStore } from '@/stores/easterEggs'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const loading = ref(true)
const data = ref(null)

// Архивный просмотр прошлых семестров убран (не работал корректно) — журнал всегда
// показывает ТЕКУЩИЙ термин, который сервер вычисляет по дате (тот же принцип, что
// уже применён к журналу преподавателя).
async function load() {
  loading.value = true
  try { data.value = (await studentApi.journal()).data } catch { data.value = null } finally { loading.value = false }
}
// Пасхалки журнала (кубик Isaac, счётчик ULTRAKILL, внутренний голос). Спрашиваем
// ПОСЛЕ загрузки данных: обе, что работают с клетками оценок, ищут их в разметке, а до
// ответа сервера строк ещё нет вовсе. Средний по всем предметам берём из ТОГО ЖЕ
// ответа, что и сам счётчик, — второй методики среднего в продукте быть не должно.
const easter = useEasterStore()
const avg = ref(0)

// 🔥 ПОЗДНИЙ ОТВЕТ НЕ САДИТСЯ НА ПОКИНУТУЮ СТРАНИЦУ (найдено 23.08.2026).
// Бросок уходит на сервер ПОСЛЕ загрузки журнала. Если человек за это время ушёл на
// другую вкладку, ответ возвращался в пустоту и всё равно поднимал флаг пасхалки — а
// рисовать её было уже некому: голос и кубик живут только на этой странице. Дальше
// продукт честно спрашивал «останьтесь, тут пасхалка» на дашборде, где её нет и быть
// не может, а «Прислушаться» ничего не показывало. Ровно это Влад и поймал.
let alive = true
onBeforeUnmount(() => { alive = false })

onMounted(async () => {
  await load()
  await nextTick()
  if (!alive) return                 // ушли, пока грузился журнал — не бросаем вовсе
  const r = await easter.rollJournal()
  if (!alive) {
    //Ответ вернулся уже после ухода: снимаем всё, что он успел поднять.
    for (const id of ['disco_elysium_voice', 'binding_of_isaac_d6', 'ultrakill_rank']) {
      easter.closeInPage(id)
    }
    return
  }
  avg.value = Number(r?.average || 0)
})

// Сами занятия рисует общий SubjectLessons — он же стоит в журнале родителя, чтобы две
// страницы, обязанные показывать одно и то же, не разъезжались (раньше вёрстка была
// скопирована в оба файла и уже начала расходиться, см. докстринг компонента).
</script>

<template>
  <!-- relative — якорь для слоя пасхалок: он позиционируется внутри страницы -->
  <div class="relative space-y-5">
    <!-- Без сети журнал показывает сохранённую копию и выглядит как свежий. Подпись
         говорит, на какой момент эти оценки, — иначе человек примет вчерашнее за
         сегодняшнее и не станет перепроверять. -->
    <DataFreshness url="/web/student/journal" />
    <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
    <EmptyState v-else-if="!data?.subjects?.length" :title="locale.t('studentJournal.noLessonsTitle', 'Занятий пока нет')"
                :message="locale.t('studentJournal.noLessonsMessage', 'Когда появятся предметы и оценки, они отобразятся здесь.')" />

    <template v-else>
      <Card v-for="s in data.subjects" :key="s.subject" :title="s.subject" pad>
        <template #header>
          <!-- Часы показываем, только если админ задал план: «24 из 0» выглядело бы поломкой -->
          <Badge v-if="s.hours?.total" variant="blue">
            {{ locale.t('studentJournal.hoursProgress', { done: s.hours.done, total: s.hours.total }) }}
          </Badge>
          <Badge variant="green">{{ locale.t('studentJournal.averageBadge', { avg: s.average || '—' }) }}</Badge>
        </template>
        <SubjectLessons :lessons="s.lessons" />
      </Card>

      <p v-if="data.methodology" class="px-1 text-xs text-text3">{{ data.methodology }}</p>
    </template>

    <JournalEggs :average="avg" />
  </div>
</template>
