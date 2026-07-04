<script setup>
// TeacherStudents — студенты группы со средним по предметам преподавателя.
import { ref, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

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

const columns = [
  { key: 'surname', label: 'Фамилия' },
  { key: 'name', label: 'Имя' },
  { key: 'average', label: 'Средний', align: 'right' },
]
</script>

<template>
  <div class="space-y-4">
    <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
      <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
    </select>
    <EmptyState v-if="!groups.length" title="Нет групп" message="За вами не закреплены группы." />
    <DataTable v-else :columns="columns" :rows="rows" :loading="loading" empty="Студентов нет">
      <template #cell-surname="{ row }"><span class="font-medium text-text">{{ row.surname }}</span></template>
      <template #cell-average="{ row }"><span class="font-title font-bold text-accent">{{ row.average || '—' }}</span></template>
    </DataTable>
  </div>
</template>
