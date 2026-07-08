/**
 * vectorCommands.js — Быстрые команды Вектора (точный порт vector/faq.py::QUICK_COMMANDS).
 * По ролям: [{ icon, label, q }] — иконка (lucide), подпись кнопки, отправляемый вопрос.
 * Те же подписи и те же вопросы, что в десктопе (сервер их понимает по ключевым словам).
 */
import {
  BookOpen, BarChart3, CalendarDays, CircleAlert, CircleHelp,
  ClipboardList, TriangleAlert, Users, School, Presentation,
} from '@lucide/vue'

export const QUICK_COMMANDS = {
  student: [
    { icon: BookOpen, label: 'Мои оценки', q: 'мои оценки' },
    { icon: BarChart3, label: 'Средний балл', q: 'какой у меня средний балл' },
    { icon: CalendarDays, label: 'Пропуски', q: 'сколько у меня пропусков' },
    { icon: CircleAlert, label: 'Долги', q: 'есть ли у меня долги' },
    { icon: CircleHelp, label: 'Что ты умеешь', q: 'что ты умеешь' },
  ],
  teacher: [
    { icon: ClipboardList, label: 'Сводка группы', q: 'сводка по группе' },
    { icon: CircleAlert, label: 'Должники', q: 'у кого долги' },
    { icon: TriangleAlert, label: 'Зона риска', q: 'кто в зоне риска' },
    { icon: Users, label: 'Студенты', q: 'список студентов группы' },
    { icon: School, label: 'Группы', q: 'какие группы есть' },
    { icon: CircleHelp, label: 'Что ты умеешь', q: 'что ты умеешь' },
  ],
  admin: [
    { icon: School, label: 'Группы', q: 'какие группы есть' },
    { icon: Presentation, label: 'Преподаватели', q: 'какие преподаватели есть' },
    { icon: ClipboardList, label: 'Сводка группы', q: 'сводка по группе' },
    { icon: CircleAlert, label: 'Должники', q: 'у кого долги' },
    { icon: TriangleAlert, label: 'Зона риска', q: 'кто в зоне риска' },
    { icon: Users, label: 'Студенты', q: 'список студентов группы' },
    { icon: CircleHelp, label: 'Что ты умеешь', q: 'что ты умеешь' },
  ],
}
