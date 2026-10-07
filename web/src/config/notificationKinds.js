// notificationKinds.js — виды писем во вкладке «Уведомления»: подпись «от кого», значок,
// вкладка списка и то, показывать ли в строке списка начало текста.
//
// Одна таблица на список (`NotificationsInbox.vue`) и на страницу письма
// (`NotificationDetailPage.vue`). Пока подпись вида жила в самом списке, в ней значилось
// шесть видов из тринадцати, которые шлёт сервер: отметка в чате, сводка «пары на
// сегодня», смена пароля, приглашение в беседу шли под общим «Уведомление» — и письмо о
// смене пароля в списке ничем не отличалось от объявления об олимпиаде.
//
// ⚠️ Тексты писем приходят ГОТОВЫМИ с сервера; здесь только то, КАК их показать.
import {
  Bell, BookOpen, CalendarClock, CalendarDays, AtSign, GraduationCap, KeyRound, Megaphone,
  ShieldAlert, SquareKanban, TriangleAlert, UserPlus, AlarmClock,
} from '@lucide/vue'

// tab — в какой вкладке списка лежит письмо; preview — показывать ли в строке списка
// начало текста после темы (у трекера — нет: «в превью — просто надпись „Вам дали
// задание в трекере“», требование Ярослава 05.10.2026; подробности — внутри письма).
export const NOTIFICATION_KINDS = {
  grade: { i18n: 'notifications.kind.grade', icon: GraduationCap, tab: 'grades', preview: true },
  grade_changed: { i18n: 'notifications.kind.gradeChanged', icon: GraduationCap, tab: 'grades', preview: true },
  homework: { i18n: 'notifications.kind.homework', icon: BookOpen, tab: 'homework', preview: true },
  schedule_changed: { i18n: 'notifications.kind.scheduleChanged', icon: CalendarDays, tab: 'system', preview: true },
  lessons_today: { i18n: 'notifications.kind.lessonsToday', icon: CalendarClock, tab: 'system', preview: true },
  event: { i18n: 'notifications.kind.event', icon: Megaphone, tab: 'events', preview: true },
  reminder: { i18n: 'notifications.kind.reminder', icon: AlarmClock, tab: 'system', preview: true },
  mention: { i18n: 'notifications.kind.mention', icon: AtSign, tab: 'system', preview: true },
  chat_invite: { i18n: 'notifications.kind.chatInvite', icon: UserPlus, tab: 'system', preview: true },
  dropout_risk: { i18n: 'notifications.kind.dropoutRisk', icon: TriangleAlert, tab: 'system', preview: true },
  report_expired: { i18n: 'notifications.kind.reportExpired', icon: ShieldAlert, tab: 'system', preview: true },
  password_changed: { i18n: 'notifications.kind.passwordChanged', icon: KeyRound, tab: 'system', preview: true },
  tracker: { i18n: 'notifications.kind.tracker', icon: SquareKanban, tab: 'tracker', preview: false },
}
export const DEFAULT_KIND = { i18n: 'notifications.kind.default', icon: Bell, tab: 'system', preview: true }

export const kindMeta = (kind) => NOTIFICATION_KINDS[kind] || DEFAULT_KIND
