<script setup>
// AdminSubjectArchive — архив предметов группы по семестрам (живой запрос 3.6.1:
// «текущие [при парсинге с сайта] должны перезаписаться, а старые улететь в архив,
// где будут видны в админке»). Группа → список термина, у ТЕКУЩЕГО термина видно и
// действующий план, и то, что последний реимпорт/правка плана только что вытеснили
// (помечено «Архив» — строка SubjectHours погашена, см. write._archive_dropped_subjects).
import { ref, onMounted, watch } from 'vue'
import { adminApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'
import Badge from '@/components/ui/Badge.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const groups = ref([])
const group = ref('')
const loading = ref(false)
const data = ref(null)

function seasonLabel(semester) {
  return semester === 1 ? locale.t('adminGroups.seasonFall', 'осенний') : locale.t('adminGroups.seasonSpring', 'весенний')
}
function termLabel(t) {
  return locale.t('adminGroups.termLabel', { year: t.year, semester: seasonLabel(t.semester) })
}

async function load() {
  if (!group.value) { data.value = null; return }
  loading.value = true
  try { data.value = (await adminApi.groupSubjectArchive(group.value)).data }
  catch { data.value = null } finally { loading.value = false }
}
watch(group, load)

onMounted(async () => {
  try {
    groups.value = (await adminApi.groups()).data.groups || []
    group.value = groups.value[0]?.name || ''
  } catch { groups.value = [] }
  await load()
})
</script>

<template>
  <div class="space-y-4">
    <EmptyState v-if="!groups.length" :title="locale.t('adminSubjectArchive.noGroupsTitle', 'Групп нет')"
                :message="locale.t('adminSubjectArchive.noGroupsMessage', 'Сначала заведите хотя бы одну группу во вкладке «Группы».')" />
    <template v-else>
      <div class="flex flex-wrap items-center gap-3">
        <select v-model="group" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:w-auto sm:min-w-52">
          <option v-for="g in groups" :key="g.name" :value="g.name">{{ g.name }}</option>
        </select>
        <p class="text-xs text-text3">
          {{ locale.t('adminSubjectArchive.hint', 'Текущий семестр показывает и действующий план, и предметы, которые только что убрал реимпорт/правка плана.') }}
        </p>
      </div>

      <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
      <EmptyState v-else-if="!data?.terms?.length" :title="locale.t('adminSubjectArchive.emptyTitle', 'Нет данных')"
                  :message="locale.t('adminSubjectArchive.emptyMessage', 'У этой группы пока нет ни плана, ни занятий ни за один семестр.')" />

      <div v-else class="space-y-4">
        <div v-for="t in data.terms" :key="`${t.year}-${t.semester}`"
             class="overflow-hidden rounded-lg border border-border bg-card shadow-card">
          <div class="flex items-center gap-2 border-b border-border bg-bg2 px-4 py-2.5">
            <span class="font-title text-sm font-bold text-text">{{ termLabel(t) }}</span>
            <Badge v-if="t.is_current" variant="green">{{ locale.t('adminSubjectArchive.currentBadge', 'текущий') }}</Badge>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-border2 text-left text-tiny uppercase tracking-wide text-text2">
                  <th class="py-2 pl-4 pr-3 font-semibold">{{ locale.t('adminSubjectArchive.colSubject', 'Предмет') }}</th>
                  <th class="py-2 pr-3 font-semibold">{{ locale.t('adminSubjectArchive.colHours', 'Часы') }}</th>
                  <th class="py-2 pr-3 font-semibold">{{ locale.t('adminSubjectArchive.colZet', 'ЗЕТ') }}</th>
                  <th class="py-2 pr-3 font-semibold">{{ locale.t('adminSubjectArchive.colTeacher', 'Преподаватель') }}</th>
                  <th class="py-2 pr-4 text-right font-semibold">{{ locale.t('adminSubjectArchive.colStatus', 'Статус') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in t.subjects" :key="s.subject" class="border-b border-border last:border-0"
                    :class="s.active ? '' : 'opacity-60'">
                  <td class="py-2 pl-4 pr-3 text-text">{{ s.subject }}</td>
                  <td class="py-2 pr-3 text-text2">{{ s.hours_total || '—' }}</td>
                  <td class="py-2 pr-3 text-text2">{{ s.zet ?? '—' }}</td>
                  <td class="py-2 pr-3 text-text2">{{ s.teacher_name || '—' }}</td>
                  <td class="py-2 pr-4 text-right">
                    <Badge v-if="s.active" variant="green">{{ locale.t('adminSubjectArchive.active', 'активен') }}</Badge>
                    <Badge v-else variant="muted">{{ locale.t('adminSubjectArchive.archived', 'архив') }}</Badge>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
