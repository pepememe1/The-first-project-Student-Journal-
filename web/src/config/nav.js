/**
 * nav.js — разделы боковой навигации по ролям (точные названия и секции десктопа).
 *   • студент       — ui/dashboards.py (ОБУЧЕНИЕ / ЛИЧНОЕ)
 *   • преподаватель — ui/teacher_dashboard.py
 *   • админ         — ui/admin_dashboard.py (УПРАВЛЕНИЕ / СИСТЕМА)
 * Пункт-секция: { section: 'ЗАГОЛОВОК' }. Пункт-ссылка: { key, label, icon, to }.
 */
import {
  Home, ClipboardList, ClipboardCheck, CalendarDays, BarChart3, Bot, User,
  BookOpen, Users, GraduationCap, Boxes, Library, Settings, Server,
  Palette, MonitorSmartphone, ShieldCheck, Activity, LayoutDashboard, UserPlus,
  AlertTriangle,
} from '@lucide/vue'

export const NAV = {
  student: [
    { section: 'Обучение' },
    { key: 'dash', label: 'Главная', icon: Home, to: '/student' },
    { key: 'journal', label: 'Мой журнал', icon: ClipboardList, to: '/student/journal' },
    { key: 'schedule', label: 'Расписание', icon: CalendarDays, to: '/student/schedule' },
    { key: 'stats', label: 'Статистика', icon: BarChart3, to: '/student/stats' },
    { key: 'ai', label: 'ИИ Помощник', icon: Bot, to: '/student/vector' },
    { section: 'Личное' },
    { key: 'profile', label: 'Профиль', icon: User, to: '/student/profile' },
  ],
  teacher: [
    { section: 'Преподавание' },
    { key: 'journal', label: 'Журнал', icon: BookOpen, to: '/teacher' },
    { key: 'students', label: 'Студенты', icon: Users, to: '/teacher/students' },
    { key: 'curator', label: 'Курирование', icon: ClipboardCheck, to: '/teacher/curator', curatorOnly: true },
    { key: 'schedule', label: 'Расписание', icon: CalendarDays, to: '/teacher/schedule' },
    { key: 'stats', label: 'Статистика', icon: BarChart3, to: '/teacher/stats' },
    { key: 'ai', label: 'ИИ Помощник', icon: Bot, to: '/teacher/vector' },
    { section: 'Личное' },
    { key: 'profile', label: 'Профиль', icon: User, to: '/teacher/profile' },
  ],
  admin: [
    { section: 'Управление' },
    { key: 'dash', label: 'Дашборд', icon: LayoutDashboard, to: '/admin' },
    { key: 'teachers', label: 'Преподаватели', icon: GraduationCap, to: '/admin/teachers' },
    { key: 'students', label: 'Студенты', icon: Users, to: '/admin/students' },
    { key: 'registrations', label: 'Заявки на регистрацию', icon: UserPlus, to: '/admin/registrations' },
    { key: 'groups', label: 'Группы', icon: Boxes, to: '/admin/groups' },
    { key: 'subjects', label: 'Предметы', icon: Library, to: '/admin/subjects' },
    { key: 'schedule', label: 'Расписание', icon: CalendarDays, to: '/admin/schedule' },
    // badge: 'scheduleIssues' — Sidebar подставит число найденных накладок.
    { key: 'issues', label: 'Накладки расписания', icon: AlertTriangle,
      to: '/admin/schedule-issues', badge: 'scheduleIssues' },
    { section: 'Система' },
    { key: 'api', label: 'Настройки ИИ', icon: Settings, to: '/admin/api' },
    { key: 'server', label: 'Сервер', icon: Server, to: '/admin/server' },
    { key: 'requests', label: 'Запросы на подключение', icon: MonitorSmartphone, to: '/admin/requests' },
    { key: 'sessions', label: 'Сессии и доступ', icon: ShieldCheck, to: '/admin/access' },
    { key: 'theme', label: 'Оформление', icon: Palette, to: '/admin/theme' },
    { key: 'mon', label: 'Мониторинг', icon: Activity, to: '/admin/monitor' },
    { key: 'ai', label: 'ИИ Помощник', icon: Bot, to: '/admin/vector' },
  ],
}

export const HOME_BY_ROLE = { student: '/student', teacher: '/teacher', admin: '/admin' }
