<script setup>
// AdminTeachers — список преподавателей (порт admin_dashboard "teachers").
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'

const rows = ref([])
const loading = ref(true)
onMounted(async () => {
  try { rows.value = (await adminApi.teachers()).data.teachers || [] } catch { rows.value = [] } finally { loading.value = false }
})
const columns = [
  { key: 'name', label: 'ФИО' },
  { key: 'login', label: 'Логин' },
  { key: 'subjects', label: 'Предметы' },
]
</script>

<template>
  <DataTable :columns="columns" :rows="rows" :loading="loading" empty="Преподавателей нет">
    <template #cell-name="{ row }"><span class="font-medium text-text">{{ row.name || '—' }}</span></template>
    <template #cell-subjects="{ row }">
      <div class="flex flex-wrap gap-1.5">
        <Badge v-for="s in row.subjects" :key="s" variant="muted">{{ s }}</Badge>
        <span v-if="!row.subjects?.length" class="text-text3">—</span>
      </div>
    </template>
  </DataTable>
</template>
