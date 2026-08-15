<script setup>
// AdminDashboard — «Панель администратора». Изначально порт нативного
// ui/admin_dashboard.py "dash" (тот удалён вместе с Qt — это единственная панель):
// стат-карточки (Преподавателей/Студентов/Групп/Предметов) + плитки-навигация.
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { GraduationCap, Users, Boxes, Library, Settings, Server } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const router = useRouter()
const data = ref(null)
onMounted(async () => { try { data.value = (await adminApi.overview()).data } catch { data.value = null } })

const tiles = computed(() => [
  { icon: GraduationCap, title: locale.t('nav.teachers', 'Преподаватели'), sub: locale.t('adminDashboard.accounts', 'Учётные записи'), to: '/admin/teachers' },
  { icon: Users, title: locale.t('nav.students', 'Студенты'), sub: locale.t('adminDashboard.listAndGroups', 'Список и группы'), to: '/admin/students' },
  { icon: Boxes, title: locale.t('nav.groups', 'Группы'), sub: locale.t('adminDashboard.groupsAndSubjects', 'Группы и предметы'), to: '/admin/groups' },
  { icon: Library, title: locale.t('nav.subjects', 'Предметы'), sub: locale.t('adminDashboard.subjectsCatalog', 'Каталог предметов'), to: '/admin/subjects' },
  { icon: Settings, title: locale.t('adminDashboard.aiSettings', 'Настройки ИИ'), sub: locale.t('adminDashboard.vectorProvider', 'Провайдер «Вектора»'), to: '/admin/api' },
  { icon: Server, title: locale.t('nav.server', 'Сервер'), sub: locale.t('adminDashboard.addressDbSite', 'Адрес, БД и сайт'), to: '/admin/server' },
])
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard :label="locale.t('adminDashboard.teachersLabel', 'Преподавателей')" :value="data?.teachers ?? '—'" :icon="GraduationCap" accent />
      <StatCard :label="locale.t('adminDashboard.studentsLabel', 'Студентов')" :value="data?.students ?? '—'" :icon="Users" />
      <StatCard :label="locale.t('adminDashboard.groupsLabel', 'Групп')" :value="data?.groups ?? '—'" :icon="Boxes" />
      <StatCard :label="locale.t('adminDashboard.subjectsLabel', 'Предметов')" :value="data?.subjects ?? '—'" :icon="Library" />
    </div>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
