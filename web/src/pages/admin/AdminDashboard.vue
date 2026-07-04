<script setup>
// AdminDashboard — «Панель администратора» (порт ui/admin_dashboard.py "dash"):
// стат-карточки (Преподавателей/Студентов/Групп/Предметов) + плитки-навигация.
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { GraduationCap, Users, Boxes, Library, Settings, Server } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'

const router = useRouter()
const data = ref(null)
onMounted(async () => { try { data.value = (await adminApi.overview()).data } catch { data.value = null } })

const tiles = [
  { icon: GraduationCap, title: 'Преподаватели', sub: 'Учётные записи', to: '/admin/teachers' },
  { icon: Users, title: 'Студенты', sub: 'Список и группы', to: '/admin/students' },
  { icon: Boxes, title: 'Группы', sub: 'Группы и предметы', to: '/admin/groups' },
  { icon: Library, title: 'Предметы', sub: 'Каталог предметов', to: '/admin/subjects' },
  { icon: Settings, title: 'Настройки ИИ', sub: 'Провайдер «Вектора»', to: '/admin/api' },
  { icon: Server, title: 'Сервер', sub: 'Адрес, БД и сайт', to: '/admin/server' },
]
</script>

<template>
  <div class="space-y-6">
    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Преподавателей" :value="data?.teachers ?? '—'" :icon="GraduationCap" accent />
      <StatCard label="Студентов" :value="data?.students ?? '—'" :icon="Users" />
      <StatCard label="Групп" :value="data?.groups ?? '—'" :icon="Boxes" />
      <StatCard label="Предметов" :value="data?.subjects ?? '—'" :icon="Library" />
    </div>

    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <button v-for="t in tiles" :key="t.to" type="button"
              class="flex items-start gap-4 rounded-lg border border-border bg-card p-5 text-left shadow-card transition-colors hover:border-accent"
              @click="router.push(t.to)">
        <div class="grid size-11 shrink-0 place-items-center rounded-md bg-accent-glow text-accent">
          <component :is="t.icon" class="size-5" />
        </div>
        <div>
          <p class="font-title text-base font-bold text-text">{{ t.title }}</p>
          <p class="text-xs text-text3">{{ t.sub }}</p>
        </div>
      </button>
    </div>
  </div>
</template>
