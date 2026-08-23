/**
 * router/index.js — маршруты и ролевые guard'ы.
 *
 * Три ветки под роли (student/teacher/admin) в оболочке AppShell. Состав страниц —
 * как в десктопных дашбордах (см. config/nav.js). Guard не пускает в чужую ветку и на
 * защищённые страницы без входа.
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useEasterStore, leaveAsk } from '@/stores/easterEggs'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { needsServer } from '@/api/server'
import { HOME_BY_ROLE } from '@/config/nav'

import AppShell from '@/layouts/AppShell.vue'
import LoginPage from '@/pages/LoginPage.vue'
import NotFoundPage from '@/pages/NotFoundPage.vue'
import { decideMiss } from '@/utils/missedRoute'
import ConnectServer from '@/pages/ConnectServer.vue'
import ResetPassword from '@/pages/ResetPassword.vue'
import VectorPage from '@/pages/VectorPage.vue'
import MessengerPage from '@/pages/MessengerPage.vue'
import SchedulePage from '@/pages/SchedulePage.vue'
import CoursesPage from '@/pages/CoursesPage.vue'
import CourseDetailPage from '@/pages/CourseDetailPage.vue'
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
  // Публичная намеренно: человек приходит сюда именно потому, что войти не может.
  { path: '/reset-password', component: ResetPassword, meta: { public: true } },
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
      page('courses', CoursesPage, 'Курсы', 'Учебные курсы вашей группы', 'nav.courses', 'router.coursesSubtitle'),
      { path: 'courses/:id', component: CourseDetailPage, meta: { title: 'Курс', i18nTitle: 'nav.courses' } },
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
      page('courses', CoursesPage, 'Курсы', 'Ваши учебные курсы', 'nav.courses', 'router.coursesSubtitle'),
      { path: 'courses/:id', component: CourseDetailPage, meta: { title: 'Курс', i18nTitle: 'nav.courses' } },
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
      page('courses', CoursesPage, 'Курсы', 'Учебные курсы', 'nav.courses', 'router.coursesSubtitle'),
      { path: 'courses/:id', component: CourseDetailPage, meta: { title: 'Курс', i18nTitle: 'nav.courses' } },
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
      page('courses', CoursesPage, 'Курсы', 'Учебные курсы группы ребёнка', 'nav.courses', 'router.coursesSubtitle'),
      { path: 'courses/:id', component: CourseDetailPage, meta: { title: 'Курс', i18nTitle: 'nav.courses' } },
      { path: 'vector', component: VectorPage, meta: { title: 'ИИ Помощник', subtitle: 'Вектор', i18nTitle: 'nav.ai', i18nSubtitle: 'router.vectorName' } },
      { path: 'messages', component: MessengerPage, meta: { title: 'Сообщения', i18nTitle: 'nav.messages' } },
      page('profile', Profile, 'Профиль', undefined, 'nav.profile'),
      page('settings', Settings, 'Настройки', 'Оформление, безопасность, озвучка', 'nav.settings', 'router.settingsSubtitle'),
    ],
  },

  // ⚠️ «Не найдено» — НЕ универсальный ответ на любой промах. Правило такое:
  //   • чужая роль в адресе (студент набрал /admin/…) → сюда, 404;
  //   • своя роль, но такой страницы нет → молча на главную.
  // Это разные события: первое значит «мне сюда нельзя», второе — «я ошибся буквой»,
  // и раньше оба заканчивались дашбордом, из-за чего первое выглядело как сбой.
  // Решение принимает страж ниже; здесь только сама страница внутри оболочки.
  // ⚠️ БЕЗ AppShell: страница самостоятельная, как экран входа. Сюда попадают, только
  // если в адресе чужая роль, и показывать при этом чужое меню было бы странно вдвойне.
  { path: '/404', component: NotFoundPage, meta: { requiresAuth: true } },
  { path: '/:pathMatch(.*)*', redirect: (to) => ({ path: '/404', query: { from: to.path } }) },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// ━━ ПАСХАЛКА НА ЭКРАНЕ: СПРАШИВАЕМ, ПРЕЖДЕ ЧЕМ УЙТИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Просьба Влада: находка редкая, а заметить её можно не сразу — человек уже потянулся
// к другой вкладке. Уйдёшь — пасхалка пропала, и второй раз она может не выпасть
// месяцами. Тот же приём, что у несохранённой формы, и по той же причине: цена
// случайного перехода несоразмерна цене одного вопроса.
//
// ⚠️ Спрашиваем ТОЛЬКО про то, что можно пропустить (`easter.pending`). Постоянные
// пасхалки — кольцо Detroit, состояние DOOM, счётчик ULTRAKILL — висят у студента
// всё время, и вопрос на каждом переходе сломал бы навигацию всему продукту.
//
// ⚠️ Выход из аккаунта не сторожим: на `/login` уводит logout, и «точно уйти?» поверх
// уже начатого выхода — это ловушка, а не забота. Плюс сама сцена Dark Souls играет
// ИМЕННО при выходе, то есть вопрос задавался бы всегда.
//
// ⚠️ На ДЕСКТОПЕ отдельного механизма не нужно и заводить его не надо: программа
// показывает ЭТОТ ЖЕ Vue-SPA в окне на движке Edge (§11), то есть страж работает там
// сам собой. А вот закрытие ОКНА роутер не видит — на этот случай ниже beforeunload.
async function confirmLeavingEasterEgg(to, from) {
  const easter = useEasterStore()
  if (!easter.pending) return true
  if (to.path === from.path || to.path === '/login') return true
  const { confirm } = useConfirm()
  const ask = leaveAsk(easter.pending)
  const ok = await confirm({
    title: ask.title, message: ask.message, okText: ask.ok, cancelText: ask.cancel,
  })
  if (ok) easter.dismissPending()
  return ok
}

// Закрытие вкладки или окна программы роутер не перехватывает вовсе — только браузер.
// Диалог здесь системный и текст свой поставить нельзя (так устроено во всех браузерах
// с 2019 года); это осознанное ограничение, а не недоделка.
// Мост для ОБОЛОЧКИ ПРОГРАММЫ: закрытие окна — событие рабочего стола, до JS оно не
// доходит, и `beforeunload` там не срабатывает. Десктоп спрашивает эту функцию из
// `desktop/webview2_app.py::_may_close` перед тем, как закрыть окно.
// ⚠️ Возвращает СТРОКУ (id пасхалки) или '' — не объект: значение уезжает через
// evaluate_js, и чем проще тип, тем меньше поводов ему сломаться по дороге.
window.__gbEasterPending = () => {
  try { return useEasterStore().pending || '' } catch { return '' }
}

window.addEventListener('beforeunload', (e) => {
  let easter
  try { easter = useEasterStore() } catch { return }   // Pinia ещё не поднялась
  if (!easter.pending) return
  e.preventDefault()
  e.returnValue = ''
})

router.beforeEach(async (to, from) => {
  // Приложение без заданного адреса сервера (первый запуск) → сперва экран подключения.
  if (needsServer() && to.path !== '/connect') return '/connect'
  const auth = useAuthStore()
  if (to.meta.public) {
    if (to.path === '/login' && auth.isAuthenticated) return HOME_BY_ROLE[auth.role] || '/'
    return true
  }
  if (!auth.isAuthenticated) return { path: '/login' }
  //Страница существует, но принадлежит другой роли — это «нельзя», а не «нет такой».
  if (to.meta.role && to.meta.role !== auth.role) return { path: '/404', query: { from: to.path } }
  //А несуществующий адрес разбираем по первому сегменту: свой раздел — обычная опечатка,
  //возвращаем на главную; чужой — оставляем на 404, куда его уже направил catch-all.
  if (to.path === '/404') {
    if (decideMiss(String(to.query.from || ''), auth.role) === 'home')
      return HOME_BY_ROLE[auth.role] || '/'
  }
  //Вопрос про пасхалку задаём ПОСЛЕДНИМ: сначала пусть отработают все перенаправления
  //(нет сервера, не вошёл, чужая роль). Иначе человека спрашивали бы «точно уйти?»
  //перед переходом, который всё равно не состоится.
  if (!(await confirmLeavingEasterEgg(to, from))) return false
  return true
})
// Обрыв озвучки при уходе от Вектора живёт НЕ здесь: глушить на каждом переходе неверно
// (на странице с открытой шторкой Вектор ещё виден и должен договорить). Правило «звук
// играет, пока виден хоть один Вектор» — реактивно в AppShell.vue (watch vectorShown).
