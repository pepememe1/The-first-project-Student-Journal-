/**
 * router/index.js — маршруты и ролевые guard'ы.
 *
 * Три ветки под роли (student/teacher/admin) в оболочке AppShell. Состав страниц —
 * как в десктопных дашбордах (см. config/nav.js). Guard не пускает в чужую ветку и на
 * защищённые страницы без входа.
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { needsServer } from '@/api/server'
import { HOME_BY_ROLE } from '@/config/nav'

import AppShell from '@/layouts/AppShell.vue'
import LoginPage from '@/pages/LoginPage.vue'
import ConnectServer from '@/pages/ConnectServer.vue'
import VectorPage from '@/pages/VectorPage.vue'
import MessengerPage from '@/pages/MessengerPage.vue'
import SchedulePage from '@/pages/SchedulePage.vue'
import Profile from '@/pages/Profile.vue'
import Settings from '@/pages/Settings.vue'
import StudentDashboard from '@/pages/student/StudentDashboard.vue'
import StudentJournal from '@/pages/student/StudentJournal.vue'
import StudentStats from '@/pages/student/StudentStats.vue'
import TeacherJournal from '@/pages/teacher/TeacherJournal.vue'
import TeacherStudents from '@/pages/teacher/TeacherStudents.vue'
import TeacherStats from '@/pages/teacher/TeacherStats.vue'
import CuratorView from '@/pages/teacher/CuratorView.vue'
import AdminDashboard from '@/pages/admin/AdminDashboard.vue'
import AdminTeachers from '@/pages/admin/AdminTeachers.vue'
import AdminStudents from '@/pages/admin/AdminStudents.vue'
import AdminRegistrations from '@/pages/admin/AdminRegistrations.vue'
import AdminGroups from '@/pages/admin/AdminGroups.vue'
import AdminSubjects from '@/pages/admin/AdminSubjects.vue'
import AdminSchedule from '@/pages/admin/AdminSchedule.vue'
import AdminScheduleIssues from '@/pages/admin/AdminScheduleIssues.vue'
import AdminSessions from '@/pages/admin/AdminSessions.vue'
import AdminRequests from '@/pages/admin/AdminRequests.vue'
import MonitorPage from '@/pages/admin/MonitorPage.vue'
import AdminAiSettings from '@/pages/admin/AdminAiSettings.vue'
import AdminData from '@/pages/admin/AdminData.vue'
import AdminServer from '@/pages/admin/AdminServer.vue'
import AdminMessenger from '@/pages/admin/AdminMessenger.vue'
import ParentJournal from '@/pages/parent/ParentJournal.vue'
import AdminParents from '@/pages/admin/AdminParents.vue'

const page = (path, component, title, subtitle) => ({ path, component, meta: { title, subtitle } })

const routes = [
  { path: '/connect', component: ConnectServer, meta: { public: true } },
  { path: '/login', component: LoginPage, meta: { public: true } },
  {
    path: '/',
    redirect: () => {
      const auth = useAuthStore()
      return auth.isAuthenticated ? HOME_BY_ROLE[auth.role] || '/login' : '/login'
    },
  },

  // СТУДЕНТ ───────────────────────────────────────────────
  {
    path: '/student', component: AppShell, meta: { requiresAuth: true, role: 'student' },
    children: [
      // Главная показывает ИМЯ студента как заголовок (title_lbl в десктопе) — рендерит
      // сама StudentDashboard, поэтому статический title из AppShell тут не нужен.
      { path: '', component: StudentDashboard, meta: {} },
      page('journal', StudentJournal, 'Журнал оценок', 'Ваши оценки по предметам'),
      page('schedule', SchedulePage, 'Расписание', 'Пары ВСГУТУ'),
      page('stats', StudentStats, 'Моя статистика', 'Динамика успеваемости'),
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения' } },
      page('profile', Profile, 'Профиль'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка'),
    ],
  },

  // ПРЕПОДАВАТЕЛЬ ─────────────────────────────────────────
  {
    path: '/teacher', component: AppShell, meta: { requiresAuth: true, role: 'teacher' },
    children: [
      { path: '', component: TeacherJournal, meta: { title: 'Журнал преподавателя', subtitle: 'Оценки по группам' } },
      page('students', TeacherStudents, 'Студенты группы'),
      page('curator', CuratorView, 'Курирование', 'Ваши курируемые группы'),
      // Куратор привязывает родителей к студентам СВОИХ групп (скоуп режет сервер).
      page('parents', AdminParents, 'Родители', 'Доступ родителей к журналу'),
      page('schedule', SchedulePage, 'Расписание'),
      page('stats', TeacherStats, 'Статистика группы'),
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения' } },
      page('profile', Profile, 'Профиль'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка'),
    ],
  },

  // АДМИНИСТРАТОР ─────────────────────────────────────────
  {
    path: '/admin', component: AppShell, meta: { requiresAuth: true, role: 'admin' },
    children: [
      { path: '', component: AdminDashboard, meta: { title: 'Панель администратора' } },
      page('teachers', AdminTeachers, 'Преподаватели'),
      page('students', AdminStudents, 'Студенты'),
      page('parents', AdminParents, 'Родители', 'Доступ родителей к журналу'),
      page('registrations', AdminRegistrations, 'Заявки на регистрацию', 'Одобрение самостоятельной регистрации студентов'),
      page('groups', AdminGroups, 'Группы'),
      page('subjects', AdminSubjects, 'Предметы'),
      page('schedule', AdminSchedule, 'Расписание', 'Правки поверх портала ВСГУТУ'),
      page('schedule-issues', AdminScheduleIssues, 'Накладки расписания',
           'Один преподаватель или аудитория заняты дважды'),
      { path: 'api', component: AdminAiSettings, meta: { title: 'Настройки ИИ-помощника «Вектор»', subtitle: 'Провайдер «Вектора» — GigaChat / Ollama / Оффлайн' } },
      page('server', AdminServer, 'Сервер и сайт', 'Адрес, БД, шифрование, статус'),
      page('data', AdminData, 'Данные и резервные копии',
           'Выгрузка всех данных в архив и загрузка обратно'),
      page('requests', AdminRequests, 'Запросы на подключение', 'Одобрение устройств'),
      page('access', AdminSessions, 'Сессии и доступ', 'Выданные токены и отзыв'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка'),
      { path: 'monitor', component: MonitorPage, meta: { title: 'Мониторинг', subtitle: 'Онлайн и события сервера' } },
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения' } },
      page('moderation', AdminMessenger, 'Модерация чатов', 'Жалобы и просмотр переписок'),
    ],
  },

  // РОДИТЕЛЬ ─────────────────────────────────────────────
  // Пять страниц и ни одной больше. Guard по роли ниже не пустит его в чужую ветку, но
  // на защиту это не влияет: каждый серверный эндпоинт проверяет роль сам (инвариант §6).
  {
    path: '/parent', component: AppShell, meta: { requiresAuth: true, role: 'parent' },
    children: [
      { path: '', component: ParentJournal, meta: { title: 'Журнал', subtitle: 'Успеваемость ребёнка' } },
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения' } },
      page('profile', Profile, 'Профиль'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка'),
    ],
  },

  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  // Приложение без заданного адреса сервера (первый запуск) → сперва экран подключения.
  if (needsServer() && to.path !== '/connect') return '/connect'
  const auth = useAuthStore()
  if (to.meta.public) {
    if (to.path === '/login' && auth.isAuthenticated) return HOME_BY_ROLE[auth.role] || '/'
    return true
  }
  if (!auth.isAuthenticated) return { path: '/login' }
  if (to.meta.role && to.meta.role !== auth.role) return HOME_BY_ROLE[auth.role] || '/login'
  return true
})
// Обрыв озвучки при уходе от Вектора живёт НЕ здесь: глушить на каждом переходе неверно
// (на странице с открытой шторкой Вектор ещё виден и должен договорить). Правило «звук
// играет, пока виден хоть один Вектор» — реактивно в AppShell.vue (watch vectorShown).
