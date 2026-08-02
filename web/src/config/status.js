/**
 * status.js — §D7: статусы пользователя, ЕДИНЫЙ источник названий и цветов.
 *
 * До этого набор жил пятью копиями (MyStatusPicker, HeaderBar, ChatThread, ProfilePanel,
 * ConversationInfo) и уже начал расходиться: где-то «Отошёл(а)», где-то «Готовится/учится»
 * против «Готовлюсь/учусь», цвет «обычного» — то зелёный из палитры, то другой. Один смысл
 * должен иметь одно имя и один цвет во всех местах, где он показан.
 *
 * Значения kind совпадают с _STATUS_KINDS на сервере (routers/messenger.py) — менять их
 * можно только вместе.
 *
 * `label`/`self` — ГЕТТЕРЫ, а не литералы: читают текущий язык через `useLocaleStore().t()`
 * в момент обращения (не при импорте модуля), поэтому `{{ k.self }}` в шаблоне остаётся
 * реактивным к переключению языка ровно так же, как обычный вызов `t()` — Vue отслеживает
 * зависимость по МОМЕНТУ чтения реактивного значения внутри `t()`, а не по тому, где
 * лежит сам геттер.
 */
import { useLocaleStore } from '@/stores/locale'

// Цвета намеренно ЖЁСТКИЕ, а не токены темы: статус — это светофор, его смысл считывается
// цветом (красный «не беспокоить», жёлтый «занят», серый «отошёл»), и подмена акцентом
// приложения сломала бы узнавание. Значения одинаково читаются в светлой и тёмной теме.
export const STATUS_KINDS = [
  { kind: '', get label() { return useLocaleStore().t('status.normal.label', 'Обычный') },
    color: '#2e9e5b', get self() { return useLocaleStore().t('status.normal.self', 'Обычный') } },
  { kind: 'dnd', get label() { return useLocaleStore().t('status.dnd.label', 'Не беспокоить') },
    color: '#ef4444', get self() { return useLocaleStore().t('status.dnd.self', 'Не беспокоить') } },
  { kind: 'studying', get label() { return useLocaleStore().t('status.studying.label', 'Готовится/учится') },
    color: '#f59e0b', get self() { return useLocaleStore().t('status.studying.self', 'Готовлюсь/учусь') } },
  { kind: 'away', get label() { return useLocaleStore().t('status.away.label', 'Отошёл(а)') },
    color: '#94a3b8', get self() { return useLocaleStore().t('status.away.self', 'Отошёл(а)') } },
]

const BY_KIND = Object.fromEntries(STATUS_KINDS.map((s) => [s.kind, s]))

/** Цвет статуса. Неизвестный kind → серый: лучше нейтральная точка, чем пустое место. */
export function statusColor(kind) {
  return BY_KIND[kind || '']?.color || '#94a3b8'
}

/**
 * Подпись статуса ЧУЖОГО человека. Пустая строка = статуса нет, и вызывающий показывает
 * обычное «в сети / не в сети».
 * customText — свой текст преподавателя («принимаю до 15:00»): он информативнее ярлыка,
 * поэтому если задан — показываем его.
 */
export function statusLabel(kind, customText = '') {
  if (!kind) return ''
  return (customText || '').trim() || BY_KIND[kind]?.label || kind
}

/** Подпись СВОЕГО статуса (первое лицо: «Готовлюсь/учусь», а не «Готовится/учится»). */
export function myStatusLabel(kind, customText = '') {
  return (customText || '').trim() || BY_KIND[kind || '']?.self
    || useLocaleStore().t('status.normal.self', 'Обычный')
}
