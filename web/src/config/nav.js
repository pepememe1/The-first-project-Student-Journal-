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
  MonitorSmartphone, ShieldCheck, Activity, LayoutDashboard, UserPlus,
  AlertTriangle, SlidersHorizontal, MessagesSquare, ShieldAlert, UsersRound, Database,
  Archive } from '@lucide/vue'

export const NAV = {
  student: [
    { section: 'Обучение', i18n: 'nav.sectionStudy' },
    { key: 'dash', label: 'Главная', i18n: 'nav.home', icon: Home, to: '/student' },
    { key: 'journal', label: 'Мой журнал', i18n: 'nav.journal', icon: ClipboardList, to: '/student/journal' },
    { key: 'schedule', label: 'Расписание', i18n: 'nav.schedule', icon: CalendarDays, to: '/student/schedule' },
    { key: 'stats', label: 'Статистика', i18n: 'nav.stats', icon: BarChart3, to: '/student/stats' },
    { key: 'ai', label: 'ИИ Помощник', i18n: 'nav.ai', icon: Bot, to: '/student/vector' },
    { key: 'messages', label: 'Сообщения', i18n: 'nav.messages', icon: MessagesSquare, to: '/student/messages', badge: 'messagesUnread' },
    { section: 'Личное', i18n: 'nav.sectionPersonal' },
    { key: 'profile', label: 'Профиль', i18n: 'nav.profile', icon: User, to: '/student/profile' },
    { key: 'settings', label: 'Настройки', i18n: 'nav.settings', icon: SlidersHorizontal, to: '/student/settings' },
  ],
  teacher: [
    { section: 'Преподавание', i18n: 'nav.sectionTeaching' },
    { key: 'journal', label: 'Журнал', i18n: 'nav.teacherJournal', icon: BookOpen, to: '/teacher' },
    { key: 'students', label: 'Студенты', i18n: 'nav.students', icon: Users, to: '/teacher/students' },
    { key: 'curator', label: 'Курирование', i18n: 'nav.curator', icon: ClipboardCheck, to: '/teacher/curator', curatorOnly: true },
    { key: 'parents', label: 'Родители', i18n: 'nav.parents', icon: UsersRound, to: '/teacher/parents', curatorOnly: true },
    { key: 'schedule', label: 'Расписание', i18n: 'nav.schedule', icon: CalendarDays, to: '/teacher/schedule' },
    { key: 'stats', label: 'Статистика', i18n: 'nav.stats', icon: BarChart3, to: '/teacher/stats' },
    { key: 'ai', label: 'ИИ Помощник', i18n: 'nav.ai', icon: Bot, to: '/teacher/vector' },
    { key: 'messages', label: 'Сообщения', i18n: 'nav.messages', icon: MessagesSquare, to: '/teacher/messages', badge: 'messagesUnread' },
    { section: 'Личное', i18n: 'nav.sectionPersonal' },
    { key: 'profile', label: 'Профиль', i18n: 'nav.profile', icon: User, to: '/teacher/profile' },
    { key: 'settings', label: 'Настройки', i18n: 'nav.settings', icon: SlidersHorizontal, to: '/teacher/settings' },
  ],
  // РОДИТЕЛЬ — ровно пять пунктов и ничего сверх. Ни списка студентов, ни статистики
  // группы, ни расписания преподавателей: это внешний человек, которому открыт доступ
  // к данным своего ребёнка, и всё лишнее здесь — расширение доступа к чужим ПДн.
  parent: [
    { section: 'Ребёнок', i18n: 'nav.section.child' },
    { key: 'journal', label: 'Журнал', i18n: 'nav.teacherJournal', icon: ClipboardList, to: '/parent' },
    { key: 'ai', label: 'ИИ Помощник', i18n: 'nav.ai', icon: Bot, to: '/parent/vector' },
    { key: 'messages', label: 'Сообщения', i18n: 'nav.messages', icon: MessagesSquare, to: '/parent/messages', badge: 'messagesUnread' },
    { section: 'Личное', i18n: 'nav.sectionPersonal' },
    { key: 'profile', label: 'Профиль', i18n: 'nav.profile', icon: User, to: '/parent/profile' },
    { key: 'settings', label: 'Настройки', i18n: 'nav.settings', icon: SlidersHorizontal, to: '/parent/settings' },
  ],
  admin: [
    { section: 'Управление', i18n: 'nav.sectionManage' },
    { key: 'dash', label: 'Дашборд', i18n: 'nav.dashboard', icon: LayoutDashboard, to: '/admin' },
    { key: 'teachers', label: 'Преподаватели', i18n: 'nav.teachers', icon: GraduationCap, to: '/admin/teachers' },
    { key: 'students', label: 'Студенты', i18n: 'nav.students', icon: Users, to: '/admin/students' },
    { key: 'parents', label: 'Родители', i18n: 'nav.parents', icon: UsersRound, to: '/admin/parents' },
    { key: 'registrations', label: 'Заявки на регистрацию', i18n: 'nav.registrations', icon: UserPlus, to: '/admin/registrations' },
    { key: 'groups', label: 'Группы', i18n: 'nav.groups', icon: Boxes, to: '/admin/groups' },
    { key: 'subjectArchive', label: 'Архив предметов', i18n: 'nav.subjectArchive', icon: Archive, to: '/admin/subject-archive' },
    { key: 'subjects', label: 'Предметы', i18n: 'nav.subjects', icon: Library, to: '/admin/subjects' },
    { key: 'schedule', label: 'Расписание', i18n: 'nav.schedule', icon: CalendarDays, to: '/admin/schedule' },
    // badge: 'scheduleIssues' — Sidebar подставит число найденных накладок.
    { key: 'issues', label: 'Накладки расписания', icon: AlertTriangle,
      to: '/admin/schedule-issues', badge: 'scheduleIssues' },
    { section: 'Система', i18n: 'nav.sectionSystem' },
    { key: 'api', label: 'Настройки ИИ', i18n: 'nav.aiSettings', icon: Settings, to: '/admin/api' },
    { key: 'server', label: 'Сервер', i18n: 'nav.server', icon: Server, to: '/admin/server' },
    { key: 'data', label: 'Данные и копии', i18n: 'nav.data', icon: Database, to: '/admin/data' },
    { key: 'requests', label: 'Запросы на подключение', i18n: 'nav.requests', icon: MonitorSmartphone, to: '/admin/requests' },
    { key: 'sessions', label: 'Сессии и доступ', i18n: 'nav.sessions', icon: ShieldCheck, to: '/admin/access' },
    { key: 'settings', label: 'Настройки', i18n: 'nav.settings', icon: SlidersHorizontal, to: '/admin/settings' },
    { key: 'mon', label: 'Мониторинг', i18n: 'nav.monitor', icon: Activity, to: '/admin/monitor' },
    { key: 'ai', label: 'ИИ Помощник', i18n: 'nav.ai', icon: Bot, to: '/admin/vector' },
    { key: 'messages', label: 'Сообщения', i18n: 'nav.messages', icon: MessagesSquare, to: '/admin/messages', badge: 'messagesUnread' },
    { key: 'moderation', label: 'Модерация чатов', i18n: 'nav.moderation', icon: ShieldAlert, to: '/admin/moderation' },
  ],
}

export const HOME_BY_ROLE = { student: '/student', teacher: '/teacher', admin: '/admin',
  parent: '/parent' }
