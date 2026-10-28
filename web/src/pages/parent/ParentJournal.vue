<script setup>
// ParentJournal — журнал ребёнка глазами родителя. ТОЛЬКО ЧТЕНИЕ.
//
// Данные приходят из /web/parent/journal в том же формате, что и студенческий журнал —
// поэтому таблица здесь такая же, и цифры между кабинетами не разъезжаются.
//
// Пока студент не подтвердил доступ, сервер отвечает 403. Это не ошибка и не сбой связи,
// поэтому объясняем прямо: доступ открывает сам студент, а не поддержка.
import { ref, computed, onMounted, watch } from 'vue'
import { parentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import ZetProgress from '@/components/ui/ZetProgress.vue'
import SubjectLessons from '@/components/journal/SubjectLessons.vue'
import SubjectJump from '@/components/journal/SubjectJump.vue'
import MarksLegend from '@/components/journal/MarksLegend.vue'
import StatCard from '@/components/ui/StatCard.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import PageReveal from '@/components/ui/PageReveal.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { TrendingUp } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { subjectAnchorId } from '@/utils/journalAnchors'

const locale = useLocaleStore()

const children = ref([])
const pending = ref(0)
const studentId = ref('')
const data = ref(null)
const loading = ref(true)
const denied = ref(false)
const zet = ref(null)   // docs/done/PLAN-ZET.md §7.6 — та же строка, что у студента, без порога
//Сводка сверху (находка D8, 28.10.2026): родитель заходит раз в месяц и прежде всего хочет
//знать «как дела в целом», а видел только список предметов. Цифры — из /web/parent/stats,
//формат один в один со студенческим, поэтому и карточки те же, что в «Статистике» студента.
const stats = ref(null)

// Оценки рисует общий SubjectLessons — тот же, что в журнале студента: докстринг
// /web/parent/journal обещает «формат один в один», и собственная копия вёрстки здесь
// уже начала расходиться со студенческой (см. докстринг компонента).

const child = computed(() => children.value.find((c) => c.id === studentId.value) || null)

//Пока список детей не пришёл, «Ребёнок не привязан» не показываем: он мелькал у каждого
//родителя перед журналом (замер 28.10.2026).
const childrenReady = ref(false)

async function loadChildren() {
  try {
    const r = (await parentApi.children()).data
    children.value = r.children || []
    pending.value = r.pending || 0
    if (children.value.length && !studentId.value) studentId.value = children.value[0].id
  } catch { children.value = [] }
  childrenReady.value = true
}

//Журнал, ЗЕТ и сводка — одним пакетом и показ одним кадром (PageReveal). Раньше они шли
//друг за другом, и сводка вставала над уже показанными предметами: сдвиг макета 0.22.
async function loadJournal() {
  if (!studentId.value) { data.value = null; loading.value = false; return }
  const id = studentId.value
  loading.value = true
  const [j, z, s] = await Promise.allSettled([parentApi.journal(id), parentApi.zet(id), parentApi.stats(id)])
  //Пока шли ответы, выбрали другого ребёнка — эти данные уже не к месту.
  if (id !== studentId.value) return
  data.value = j.status === 'fulfilled' ? j.value.data : null
  denied.value = j.status === 'rejected' && j.reason?.response?.status === 403
  zet.value = z.status === 'fulfilled' ? z.value.data : null
  stats.value = s.status === 'fulfilled' ? s.value.data : null
  loading.value = false
  firstShown.value = true
}
//Шапка (кто этот ребёнок, переключатель) появляется вместе с первым журналом, а не раньше
//него отдельным кадром; при смене ребёнка остаётся на месте.
const firstShown = ref(false)

//Журнал грузит watch: loadChildren выставляет ребёнка, и watch срабатывает сам. Прямой
//вызов здесь нужен, только когда ребёнка нет — иначе каждый вход качал журнал, ЗЕТ и
//сводку дважды (замер 28.10.2026).
onMounted(async () => { await loadChildren(); if (!studentId.value) await loadJournal() })
watch(studentId, loadJournal)
</script>

<template>
  <div class="space-y-4">
    <!-- Переключатель детей нужен, только если их несколько -->
    <div v-if="firstShown && children.length > 1" class="flex flex-wrap items-center gap-2">
      <span class="text-sm text-text3">{{ locale.t('parentJournal.childLabel', 'Ребёнок:') }}</span>
      <select v-model="studentId"
              class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="c in children" :key="c.id" :value="c.id">{{ c.full_name }} · {{ c.group }}</option>
      </select>
    </div>
    <!-- Первый экран родителя называет, ЧЬИ это оценки (13.10.2026). Здесь стояла серая
         строка «Фамилия Имя · группа» мелким шрифтом: человек, зашедший раз в месяц, не
         понимал, на что смотрит и можно ли здесь что-то испортить. -->
    <div v-else-if="firstShown && child" class="gb-reveal rounded-lg border border-border bg-card px-4 py-3 shadow-card">
      <h2 class="font-title text-lg font-bold text-text">{{ locale.t('parentJournal.headline', { name: child.full_name }) }}</h2>
      <p class="mt-0.5 text-sm text-text2">{{ locale.t('parentJournal.groupLine', { group: child.group }) }}</p>
    </div>
    <p v-if="firstShown && children.length" class="gb-reveal px-1 text-xs text-text3">
      {{ locale.t('parentJournal.howToRead', 'Это оценки и пропуски вашего ребёнка по каждому предмету. Вы их только видите — изменить оценки может только преподаватель.') }}
    </p>

    <EmptyState v-if="childrenReady && !children.length && pending"
                :title="locale.t('parentJournal.pendingTitle', 'Ожидается подтверждение')"
                :message="locale.t('parentJournal.pendingMessage', { n: pending })" />
    <EmptyState v-else-if="childrenReady && !children.length"
                :title="locale.t('parentJournal.noChildTitle', 'Ребёнок не привязан')"
                :message="locale.t('parentJournal.noChildMessage', 'Обратитесь к куратору группы или в учебную часть, чтобы вас привязали к студенту.')" />

    <PageReveal v-else :loading="loading || !childrenReady">
      <template #skeleton>
        <div class="space-y-4">
          <Skeleton kind="stats" :count="3" />
          <Skeleton kind="card" :count="3" />
          <Skeleton kind="list" :count="5" />
        </div>
      </template>

    <EmptyState v-if="denied" :title="locale.t('parentJournal.deniedTitle', 'Доступ не подтверждён')"
                :message="locale.t('parentJournal.deniedMessage', 'Студент ещё не подтвердил доступ к журналу либо отозвал его.')" />

    <EmptyState v-else-if="!data?.subjects?.length" :title="locale.t('parentJournal.emptyTitle', 'Пока пусто')"
                :message="locale.t('parentJournal.emptyMessage', 'Когда появятся предметы и оценки, они отобразятся здесь.')" />

    <div v-else class="space-y-4">
      <template v-if="stats">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard :label="locale.t('studentStats.average', 'Средний балл')" :value="stats.average ?? '—'" :icon="TrendingUp" accent />
          <StatCard :label="locale.t('studentStats.absencesHours', 'Пропусков (часов)')" :value="stats.absences?.всего ?? 0" />
          <StatCard :label="locale.t('studentStats.debts', 'Задолженности')" :value="stats.debts?.length ?? 0" />
        </div>
        <RiskBadge v-if="stats.risk" :risk="stats.risk" />
      </template>
      <Card v-if="zet?.subjects?.length" pad>
        <ZetProgress :earned="zet.earned" :total="zet.total" :pending="zet.pending"
                     :subjects="zet.subjects" show-details />
      </Card>
      <!-- Оглавление: предметы со средним и переход к карточке. Сверху, потому что это
           ответ на вопрос «что у меня вообще есть» — его задают до чтения занятий. -->
      <SubjectJump :subjects="data.subjects" />

      <Card v-for="s in data.subjects" :key="s.subject" :id="subjectAnchorId(s.subject)"
            class="scroll-mt-20" :title="s.subject" pad>
        <template #header>
          <Badge v-if="s.hours?.total" variant="blue">
            {{ locale.t('parentJournal.hoursProgress', { done: s.hours.done, total: s.hours.total }) }}
          </Badge>
          <Badge variant="green">{{ locale.t('parentJournal.averageBadge', { avg: s.average || '—' }) }}</Badge>
        </template>
        <SubjectLessons :lessons="s.lessons" />
      </Card>
      <MarksLegend />
      <p v-if="data.methodology" class="px-1 text-xs text-text3">{{ data.methodology }}</p>
    </div>
    </PageReveal>
  </div>
</template>
