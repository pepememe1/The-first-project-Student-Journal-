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
import AdminSubjectArchive from '@/pages/admin/AdminSubjectArchive.vue'
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

// i18nTitle/i18nSubtitle — необязательные ключи словаря (см. AppShell.vue); без них
// заголовок остаётся русским литералом title/subtitle (обратная совместимость).
const page = (path, component, title, subtitle, i18nTitle, i18nSubtitle) =>
  ({ path, component, meta: { title, subtitle, i18nTitle, i18nSubtitle } })

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
      page('journal', StudentJournal, 'Журнал оценок', 'Ваши оценки по предметам', 'nav.journal', 'router.journalSubtitle'),
      page('schedule', SchedulePage, 'Расписание', 'Пары ВСГУТУ', 'nav.schedule', 'router.scheduleSubtitle'),
      page('stats', StudentStats, 'Моя статистика', 'Динамика успеваемости', 'router.myStats', 'router.statsSubtitle'),
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор', i18nTitle: 'nav.ai', i18nSubtitle: 'router.vectorName' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения', i18nTitle: 'nav.messages' } },
      page('profile', Profile, 'Профиль', undefined, 'nav.profile'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка', 'nav.settings', 'router.settingsSubtitle'),
    ],
  },

  // ПРЕПОДАВАТЕЛЬ ─────────────────────────────────────────
  {
    path: '/teacher', component: AppShell, meta: { requiresAuth: true, role: 'teacher' },
    children: [
      { path: '', component: TeacherJournal, meta: { title: 'Журнал преподавателя', subtitle: 'Оценки по группам', i18nTitle: 'router.teacherJournalTitle', i18nSubtitle: 'router.teacherJournalSubtitle' } },
      page('students', TeacherStudents, 'Студенты группы', undefined, 'router.groupStudents'),
      page('curator', CuratorView, 'Курирование', 'Ваши курируемые группы', 'nav.curator', 'router.curatorSubtitle'),
      // Куратор привязывает родителей к студентам СВОИХ групп (скоуп режет сервер).
      page('parents', AdminParents, 'Родители', 'Доступ родителей к журналу', 'nav.parents', 'router.parentsSubtitle'),
      page('schedule', SchedulePage, 'Расписание', undefined, 'nav.schedule'),
      page('stats', TeacherStats, 'Статистика группы', undefined, 'router.groupStats'),
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор', i18nTitle: 'nav.ai', i18nSubtitle: 'router.vectorName' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения', i18nTitle: 'nav.messages' } },
      page('profile', Profile, 'Профиль', undefined, 'nav.profile'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка', 'nav.settings', 'router.settingsSubtitle'),
    ],
  },

  // АДМИНИСТРАТОР ─────────────────────────────────────────
  {
    path: '/admin', component: AppShell, meta: { requiresAuth: true, role: 'admin' },
    children: [
      { path: '', component: AdminDashboard, meta: { title: 'Панель администратора', i18nTitle: 'router.adminDashboardTitle' } },
      page('teachers', AdminTeachers, 'Преподаватели', undefined, 'nav.teachers'),
      page('students', AdminStudents, 'Студенты', undefined, 'nav.students'),
      page('parents', AdminParents, 'Родители', 'Доступ родителей к журналу', 'nav.parents', 'router.parentsSubtitle'),
      page('registrations', AdminRegistrations, 'Заявки на регистрацию', 'Одобрение самостоятельной регистрации студентов', 'nav.registrations', 'router.registrationsSubtitle'),
      page('groups', AdminGroups, 'Группы', undefined, 'nav.groups'),
      page('subject-archive', AdminSubjectArchive, 'Архив предметов',
           'Что изучалось раньше и что убрал последний реимпорт плана', 'nav.subjectArchive', 'router.subjectArchiveSubtitle'),
      page('subjects', AdminSubjects, 'Предметы', undefined, 'nav.subjects'),
      page('schedule', AdminSchedule, 'Расписание', 'Правки поверх портала ВСГУТУ', 'nav.schedule', 'router.adminScheduleSubtitle'),
      page('schedule-issues', AdminScheduleIssues, 'Накладки расписания',
           'Один преподаватель или аудитория заняты дважды', 'router.scheduleIssuesTitle', 'router.scheduleIssuesSubtitle'),
      { path: 'api', component: AdminAiSettings, meta: { title: 'Настройки ИИ-помощника «Вектор»', subtitle: 'Провайдер «Вектора» — GigaChat / Ollama / Оффлайн', i18nTitle: 'router.aiSettingsTitle', i18nSubtitle: 'router.aiSettingsSubtitle' } },
      // В программе на этой же странице появляется управление по SSH (список серверов,
      // команды, перенос). На сайте его нет: маршруты /desk/* подключает только
      // локальный сервер программы — см. шапку AdminServer.vue.
      page('server', AdminServer, 'Сервер', 'Состояние машины, база, диск, копии', 'nav.server', 'router.serverSubtitle'),
      page('data', AdminData, 'Данные и резервные копии',
           'Выгрузка всех данных в архив и загрузка обратно', 'router.dataTitle', 'router.dataSubtitle'),
      page('requests', AdminRequests, 'Запросы на подключение', 'Одобрение устройств', 'nav.requests', 'router.requestsSubtitle'),
      page('access', AdminSessions, 'Сессии и доступ', 'Выданные токены и отзыв', 'nav.sessions', 'router.accessSubtitle'),
      // Раньше отсутствовал: SidebarUserOverlay/HeaderBar ссылаются на `/${role}/profile`
      // безусловно для ВСЕХ ролей — у админа маршрута не было, и переход падал в
      // catch-all редирект на "/". Найдено при разведке под Discord-style профиль (3.6).
      page('profile', Profile, 'Профиль', undefined, 'nav.profile'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка', 'nav.settings', 'router.settingsSubtitle'),
      { path: 'monitor', component: MonitorPage, meta: { title: 'Мониторинг', subtitle: 'Онлайн и события сервера', i18nTitle: 'nav.monitor', i18nSubtitle: 'router.monitorSubtitle' } },
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор', i18nTitle: 'nav.ai', i18nSubtitle: 'router.vectorName' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения', i18nTitle: 'nav.messages' } },
      page('moderation', AdminMessenger, 'Модерация чатов', 'Жалобы и просмотр переписок', 'nav.moderation', 'router.moderationSubtitle'),
    ],
  },

  // РОДИТЕЛЬ ─────────────────────────────────────────────
  // Пять страниц и ни одной больше. Guard по роли ниже не пустит его в чужую ветку, но
  // на защиту это не влияет: каждый серверный эндпоинт проверяет роль сам (инвариант §6).
  {
    path: '/parent', component: AppShell, meta: { requiresAuth: true, role: 'parent' },
    children: [
      { path: '', component: ParentJournal, meta: { title: 'Журнал', subtitle: 'Успеваемость ребёнка', i18nTitle: 'nav.teacherJournal', i18nSubtitle: 'router.childPerformance' } },
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор', i18nTitle: 'nav.ai', i18nSubtitle: 'router.vectorName' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения', i18nTitle: 'nav.messages' } },
      page('profile', Profile, 'Профиль', undefined, 'nav.profile'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка', 'nav.settings', 'router.settingsSubtitle'),
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
