/**
 * mascot.js — выбор спрайта маскота «Вектор» (порт vector/emotes.py::pick).
 *
 * Используем ТОЛЬКО 30 спрайтов эмоций (6 морд × 5 жестов) «<face>-<gesture>.png» —
 * старые кадры «речи» не задействуем. pickEmote() выбирает пару по состоянию/
 * настроению/намерению (в игре все 30 картинок).
 *
 * Файлы лежат в /public/mascot (сжаты из арта Арины emotions/эмоции).
 */

// Морды: sad(груст) neutral(деф) think(думает) warn(предупреж) happy(рад) surprise(удив)
// Жесты: idle(деф) think(думает) cheer(подбадрив) congrats(поздрав) warn(предупреж)
const WARN_INTENTS = new Set(['debtors', 'absences', 'at_risk'])
const INFO_INTENTS = new Set(['help', 'about_vsgutu', 'about_college', 'groups', 'teachers', 'roster', 'group_stats'])

/** (face-gesture) под поведение маскота — точный порт emotes.pick(state, mood, intent). */
export function pickEmote(state, mood = 'neutral', intent = 'help') {
  if (state === 'thinking') return 'think-think'
  if (state === 'away') return 'neutral-idle'
  if (state === 'idle') return 'surprise-idle'
  // speaking — намерение и настроение ведут морду/жест
  if (WARN_INTENTS.has(intent)) return 'warn-warn'
  if (intent === 'hello') return 'happy-congrats'
  if (intent === 'thanks') return 'happy-cheer'
  if (mood === 'happy') return 'happy-congrats'
  if (mood === 'sad') return 'sad-cheer'
  if (INFO_INTENTS.has(intent)) return 'neutral-cheer'
  return 'neutral-idle'
}

/** Эмоция маскота на «Главной» студента по фактам журнала (порт mascot.resolveMascotState). */
export function dashboardEmote({ average = 0, debts = 0 } = {}) {
  if (debts > 0) return 'warn-warn'          // долги → предупреждает
  if (average >= 4.5) return 'happy-congrats' // отлично → поздравляет
  if (average >= 3.5) return 'happy-cheer'    // хорошо → подбадривает
  if (average > 0 && average < 3) return 'sad-cheer' // плохо, но подбадривает
  return 'neutral-idle'                        // нейтрально «руки в карманах»
}

/** Спрайт для чата «Вектора» по состоянию/настроению/НАМЕРЕНИЮ — из 30 эмоций.
 * Для «speaking» делегируем pickEmote(intent) — так задействуется весь диапазон, как
 * в десктопе: долги/пропуски → предупреж, привет → радость+поздрав, плохой балл →
 * грусть+подбадрив, инфо → деф+подбадрив и т.д. */
export function chatEmote(state, mood = 'neutral', intent = 'help') {
  if (state === 'greeting') return 'happy-cheer'          // приветливо машет при открытии
  if (state === 'thinking') return 'think-think'          // обдумывает вопрос
  if (state === 'speaking') return pickEmote('speaking', mood, intent)
  // покой/ждёт — СПОКОЙНАЯ поза «руки в карманах», рот закрыт (не удивление с открытым ртом)
  return 'neutral-idle'
}
