<script setup>
// TeacherStats — сводка по группе за предмет преподавателя.
import { ref, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { TrendingUp, Users, BookOpen } from '@lucide/vue'

const groups = ref([])
const subjects = ref([])
const group = ref('')
const subject = ref('')
const data = ref(null)

onMounted(async () => {
  try {
    const o = (await teacherApi.overview()).data
    groups.value = o.groups || []; subjects.value = o.subjects || []
    group.value = groups.value[0] || ''; subject.value = subjects.value[0] || ''
  } catch { /* */ }
})
async function load() {
  if (!group.value || !subject.value) return
  try { data.value = (await teacherApi.stats(group.value, subject.value)).data } catch { data.value = null }
}
watch([group, subject], load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <select v-model="subject" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
      </select>
    </div>
    <EmptyState v-if="!groups.length || !subjects.length" title="Нет нагрузки" />
    <div v-else class="grid gap-4 sm:grid-cols-3">
      <StatCard label="Средний по группе" :value="data?.group_average || '—'" :icon="TrendingUp" accent />
      <StatCard label="Студентов" :value="data?.students ?? '—'" :icon="Users" />
      <StatCard label="Занятий" :value="data?.lessons ?? '—'" :icon="BookOpen" />
    </div>
  </div>
</template>
