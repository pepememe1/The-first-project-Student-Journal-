// useTrackerLabels — подписи и цвета трекера задач в одном месте.
//
// Приоритет, тип задачи и вид колонки показываются на доске, в списке, в окне задачи, в
// сводке и в письме исполнителю. Подпись, собранная в каждом из пяти мест отдельно,
// разошлась бы на первой же правке — «Критичный» на доске и «Высокий» в письме про одну
// и ту же задачу. Здесь одна таблица на всех.
import { computed } from 'vue'
import {
  Bug, CircleCheck, CircleDot, Flag, Layers, Sparkles, SquareCheck,
  ChevronsUp, ChevronUp, Equal, ChevronDown, ChevronsDown,
} from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'

// Цвет — токеном палитры, а не числом: тема у каждого своя (светлая, тёмная, свой акцент).
export const PRIORITY_STYLE = {
  blocker: { icon: ChevronsUp, color: 'var(--gb-red)' },
  critical: { icon: ChevronUp, color: 'var(--gb-orange)' },
  normal: { icon: Equal, color: 'var(--gb-blue)' },
  minor: { icon: ChevronDown, color: 'var(--gb-text3)' },
  trivial: { icon: ChevronsDown, color: 'var(--gb-text3)' },
}
export const KIND_STYLE = {
  task: { icon: SquareCheck, color: 'var(--gb-blue)' },
  bug: { icon: Bug, color: 'var(--gb-red)' },
  improvement: { icon: Sparkles, color: 'var(--gb-accent)' },
  epic: { icon: Layers, color: 'var(--gb-orange)' },
  milestone: { icon: Flag, color: 'var(--gb-yellow)' },
}
export const COLUMN_STYLE = {
  todo: { icon: CircleDot, color: 'var(--gb-text3)' },
  doing: { icon: CircleDot, color: 'var(--gb-blue)' },
  review: { icon: CircleDot, color: 'var(--gb-orange)' },
  done: { icon: CircleCheck, color: 'var(--gb-accent)' },
}
// Цвета меток — id, а не CSS: сервер хранит только идентификатор (как цвет профиля),
// произвольная строка из базы в стили не попадает.
export const LABEL_COLORS = {
  '': 'var(--gb-text3)',
  red: 'var(--gb-red)',
  orange: 'var(--gb-orange)',
  yellow: 'var(--gb-yellow)',
  green: 'var(--gb-accent)',
  blue: 'var(--gb-blue)',
  teal: 'var(--gb-accent2)',
}
export const labelColor = (id) => LABEL_COLORS[id] || LABEL_COLORS['']

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }

export function useTrackerLabels() {
  const locale = useLocaleStore()
  const t = (k, p) => locale.t(k, p)
  const priority = computed(() => ({
    blocker: t('tracker.priority.blocker'), critical: t('tracker.priority.critical'),
    normal: t('tracker.priority.normal'), minor: t('tracker.priority.minor'),
    trivial: t('tracker.priority.trivial'),
  }))
  const kind = computed(() => ({
    task: t('tracker.kind.task'), bug: t('tracker.kind.bug'),
    improvement: t('tracker.kind.improvement'), epic: t('tracker.kind.epic'),
    milestone: t('tracker.kind.milestone'),
  }))
  const columnKind = computed(() => ({
    todo: t('tracker.columnKind.todo'), doing: t('tracker.columnKind.doing'),
    review: t('tracker.columnKind.review'), done: t('tracker.columnKind.done'),
  }))
  const link = computed(() => ({
    relates: t('tracker.link.relates'), blocks: t('tracker.link.blocks'),
    depends: t('tracker.link.depends'),
  }))
  // Обратная сторона связи: задача А «блокирует» Б — у Б это «блокируется задачей А».
  const linkBack = computed(() => ({
    relates: t('tracker.link.relates'), blocks: t('tracker.link.blockedBy'),
    depends: t('tracker.link.requiredFor'),
  }))
  const deadline = computed(() => ({
    overdue: t('tracker.deadline.overdue'), today: t('tracker.deadline.today'),
    soon: t('tracker.deadline.soon'), ok: '', done: '',
  }))

  /** Дата человеку: «20 окт.» или «20 окт., 18:00» — на языке интерфейса. */
  function fmtDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/.exec(String(s || ''))
    if (!m) return ''
    const d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0))
    const tag = BCP47[locale.active] || 'ru-RU'
    const sameYear = d.getFullYear() === new Date().getFullYear()
    const date = d.toLocaleDateString(tag, sameYear ? { day: 'numeric', month: 'short' }
      : { day: 'numeric', month: 'short', year: 'numeric' })
    return m[4] ? `${date}, ${m[4]}:${m[5]}` : date
  }
  /** Метка времени сервера (ISO, UTC) → «5 окт., 14:20» по часам человека. */
  function fmtStamp(iso) {
    const d = new Date(iso || '')
    if (Number.isNaN(d.getTime())) return ''
    const tag = BCP47[locale.active] || 'ru-RU'
    return d.toLocaleString(tag, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  }
  const hoursUnit = computed(() => t('tracker.hoursUnit'))

  return { t, priority, kind, columnKind, link, linkBack, deadline, fmtDate, fmtStamp, hoursUnit }
}
