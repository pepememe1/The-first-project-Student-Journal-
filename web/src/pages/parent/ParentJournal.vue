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
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const children = ref([])
const pending = ref(0)
const studentId = ref('')
const data = ref(null)
const loading = ref(true)
const denied = ref(false)
const zet = ref(null)   // docs/PLAN-ZET.md §7.6 — та же строка, что у студента, без порога

const gradeClass = (g) => {
  const v = (g || '').trim().split(' ')[0]
  if (v === '5') return 'text-green font-bold'
  if (v === '4') return 'text-accent font-semibold'
  if (v === '3') return 'text-orange'
  if (v === '2' || v === 'Н') return 'text-red font-semibold'
  return 'text-text3'
}

const child = computed(() => children.value.find((c) => c.id === studentId.value) || null)

async function loadChildren() {
  try {
    const r = (await parentApi.children()).data
    children.value = r.children || []
    pending.value = r.pending || 0
    if (children.value.length && !studentId.value) studentId.value = children.value[0].id
  } catch { children.value = [] }
}

async function loadJournal() {
  if (!studentId.value) { data.value = null; loading.value = false; return }
  loading.value = true
  denied.value = false
  try {
    data.value = (await parentApi.journal(studentId.value)).data
  } catch (e) {
    data.value = null
    denied.value = e?.response?.status === 403
  } finally { loading.value = false }
  try { zet.value = (await parentApi.zet(studentId.value)).data } catch { zet.value = null }
}

onMounted(async () => { await loadChildren(); await loadJournal() })
watch(studentId, loadJournal)
</script>

<template>
  <div class="space-y-4">
    <!-- Переключатель детей нужен, только если их несколько -->
    <div v-if="children.length > 1" class="flex flex-wrap items-center gap-2">
      <span class="text-sm text-text3">{{ locale.t('parentJournal.childLabel', 'Ребёнок:') }}</span>
      <select v-model="studentId"
              class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="c in children" :key="c.id" :value="c.id">{{ c.full_name }} · {{ c.group }}</option>
      </select>
    </div>
    <p v-else-if="child" class="text-sm text-text3">
      {{ locale.t('parentJournal.childGroupLine', { name: child.full_name, group: child.group }) }}
    </p>

    <EmptyState v-if="!children.length && pending"
                :title="locale.t('parentJournal.pendingTitle', 'Ожидается подтверждение')"
                :message="locale.t('parentJournal.pendingMessage', { n: pending })" />
    <EmptyState v-else-if="!children.length"
                :title="locale.t('parentJournal.noChildTitle', 'Ребёнок не привязан')"
                :message="locale.t('parentJournal.noChildMessage', 'Обратитесь к куратору группы или в учебную часть, чтобы вас привязали к студенту.')" />

    <p v-else-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>

    <EmptyState v-else-if="denied" :title="locale.t('parentJournal.deniedTitle', 'Доступ не подтверждён')"
                :message="locale.t('parentJournal.deniedMessage', 'Студент ещё не подтвердил доступ к журналу либо отозвал его.')" />

    <EmptyState v-else-if="!data?.subjects?.length" :title="locale.t('parentJournal.emptyTitle', 'Пока пусто')"
                :message="locale.t('parentJournal.emptyMessage', 'Когда появятся предметы и оценки, они отобразятся здесь.')" />

    <template v-else>
      <Card v-if="zet?.subjects?.length" pad>
        <ZetProgress :earned="zet.earned" :total="zet.total" :subjects="zet.subjects" show-details />
      </Card>
      <Card v-for="s in data.subjects" :key="s.subject" :title="s.subject" pad>
        <template #header>
          <Badge v-if="s.hours?.total" variant="blue">
            {{ locale.t('parentJournal.hoursProgress', { done: s.hours.done, total: s.hours.total }) }}
          </Badge>
          <Badge variant="green">{{ locale.t('parentJournal.averageBadge', { avg: s.average || '—' }) }}</Badge>
        </template>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border2 text-left text-tiny uppercase tracking-wide text-text2">
                <th class="py-2 pr-3 font-semibold">{{ locale.t('parentJournal.colType', 'Тип') }}</th>
                <th class="py-2 pr-3 font-semibold">{{ locale.t('parentJournal.colTopic', 'Тема') }}</th>
                <th class="py-2 pr-3 font-semibold">{{ locale.t('parentJournal.colDate', 'Дата') }}</th>
                <th class="py-2 text-right font-semibold">{{ locale.t('parentJournal.colGrade', 'Оценка') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in s.lessons" :key="l.id" class="border-b border-border last:border-0">
                <td class="py-2 pr-3 text-text2">{{ l.type }} {{ l.number }}</td>
                <td class="py-2 pr-3 text-text">{{ l.topic || '—' }}</td>
                <td class="py-2 pr-3 text-text3">{{ l.date || '—' }}</td>
                <td class="py-2 text-right" :class="gradeClass(l.latest || l.grade)">
                  {{ l.latest || l.grade || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
      <p v-if="data.methodology" class="px-1 text-xs text-text3">{{ data.methodology }}</p>
    </template>
  </div>
</template>
