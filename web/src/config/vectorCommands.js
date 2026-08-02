/**
 * vectorCommands.js — Быстрые команды Вектора (точный порт vector/faq.py::QUICK_COMMANDS).
 * По ролям: [{ icon, label, q }] — иконка (lucide), подпись кнопки, отправляемый вопрос.
 * Те же подписи и те же вопросы, что в десктопе (сервер их понимает по ключевым словам).
 *
 * ⚠️ `q` — РУССКИЙ ТЕКСТ ВСЕГДА, не переводить: это вопрос, который распознаёт серверный
 * классификатор (`vector_nlu.py`, лексикон только на русском — тот же принцип, что у
 * slash-команд мессенджера типа «/отчет»). Переводится только `label` (подпись кнопки) —
 * ГЕТТЕРОМ (как в `config/status.js`), чтобы оставаться реактивным к переключению языка.
 */
import { useLocaleStore } from '@/stores/locale'
import {
  BookOpen, BarChart3, CalendarDays, CircleAlert, CircleHelp,
  ClipboardList, TriangleAlert, Users, School, Presentation,
} from '@lucide/vue'

function t(key, fallback) { return useLocaleStore().t(key, fallback) }

export const QUICK_COMMANDS = {
  student: [
    { icon: BookOpen, get label() { return t('vectorCommands.myGrades', 'Мои оценки') }, q: 'мои оценки' },
    { icon: BarChart3, get label() { return t('vectorCommands.average', 'Средний балл') }, q: 'какой у меня средний балл' },
    { icon: CalendarDays, get label() { return t('vectorCommands.absences', 'Пропуски') }, q: 'сколько у меня пропусков' },
    { icon: CircleAlert, get label() { return t('vectorCommands.debts', 'Долги') }, q: 'есть ли у меня долги' },
    { icon: CircleHelp, get label() { return t('vectorCommands.whatCanYouDo', 'Что ты умеешь') }, q: 'что ты умеешь' },
  ],
  teacher: [
    { icon: ClipboardList, get label() { return t('vectorCommands.groupSummary', 'Сводка группы') }, q: 'сводка по группе' },
    { icon: CircleAlert, get label() { return t('vectorCommands.debtors', 'Должники') }, q: 'у кого долги' },
    { icon: TriangleAlert, get label() { return t('vectorCommands.riskZone', 'Зона риска') }, q: 'кто в зоне риска' },
    { icon: Users, get label() { return t('nav.students', 'Студенты') }, q: 'список студентов группы' },
    { icon: School, get label() { return t('nav.groups', 'Группы') }, q: 'какие группы есть' },
    { icon: CircleHelp, get label() { return t('vectorCommands.whatCanYouDo', 'Что ты умеешь') }, q: 'что ты умеешь' },
  ],
  admin: [
    { icon: School, get label() { return t('nav.groups', 'Группы') }, q: 'какие группы есть' },
    { icon: Presentation, get label() { return t('nav.teachers', 'Преподаватели') }, q: 'какие преподаватели есть' },
    { icon: ClipboardList, get label() { return t('vectorCommands.groupSummary', 'Сводка группы') }, q: 'сводка по группе' },
    { icon: CircleAlert, get label() { return t('vectorCommands.debtors', 'Должники') }, q: 'у кого долги' },
    { icon: TriangleAlert, get label() { return t('vectorCommands.riskZone', 'Зона риска') }, q: 'кто в зоне риска' },
    { icon: Users, get label() { return t('nav.students', 'Студенты') }, q: 'список студентов группы' },
    { icon: CircleHelp, get label() { return t('vectorCommands.whatCanYouDo', 'Что ты умеешь') }, q: 'что ты умеешь' },
  ],
}
