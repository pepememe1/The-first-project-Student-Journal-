<script setup>
// TeacherStudents — студенты группы со средним по предметам преподавателя.
import { ref, computed, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const groups = ref([])
const group = ref('')
const rows = ref([])
const loading = ref(false)

onMounted(async () => {
  try {
    const o = (await teacherApi.overview()).data
    groups.value = o.groups || []
    group.value = groups.value[0] || ''
  } catch { /* */ }
})

async function load() {
  if (!group.value) return
  loading.value = true
  try { rows.value = (await teacherApi.students(group.value)).data.students || [] } catch { rows.value = [] } finally { loading.value = false }
}
watch(group, load)

const columns = computed(() => [
  { key: 'surname', label: locale.t('teacherStudents.colSurname', 'Фамилия') },
  { key: 'name', label: locale.t('teacherStudents.colName', 'Имя') },
  //Риск отчисления (3.6) — здесь он и нужен: преподаватель смотрит на список своей
  //группы и обязан видеть, к кому подойти. Считается ТОЛЬКО по ЕГО предметам (см.
  //teacher_students на сервере); целостную картину по всем предметам даёт «Курирование».
  { key: 'risk', label: locale.t('teacherStudents.colRisk', 'Риск') },
  { key: 'average', label: locale.t('teacherStudents.colAverage', 'Средний'), align: 'right' },
])
//Сколько человек в зоне риска — числом над таблицей: строку в списке легко пролистать,
//а «в зоне риска 3» заставляет посмотреть.
const atRisk = computed(() => rows.value.filter((r) => r.risk).length)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <span v-if="atRisk" class="rounded-md border border-red/30 bg-red/10 px-2.5 py-1 text-xs font-semibold text-red">
        🎓 {{ locale.t('teacherStudents.atRisk', { n: atRisk }) }}
      </span>
    </div>
    <EmptyState v-if="!groups.length" :title="locale.t('teacherStudents.noGroupsTitle', 'Нет групп')" :message="locale.t('teacherStudents.noGroupsMessage', 'За вами не закреплены группы.')" />
    <DataTable v-else :columns="columns" :rows="rows" :loading="loading" :empty="locale.t('teacherStudents.noStudents', 'Студентов нет')">
      <template #cell-surname="{ row }"><span class="font-medium text-text">{{ row.surname }}</span></template>
      <template #cell-risk="{ row }"><RiskBadge :risk="row.risk" /></template>
      <template #cell-average="{ row }"><span class="font-title font-bold text-accent">{{ row.average || '—' }}</span></template>
    </DataTable>
  </div>
</template>
