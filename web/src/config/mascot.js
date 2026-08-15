/**
 * mascot.js — выбор спрайта маскота «Вектор». ЕДИНСТВЕННАЯ живая реализация.
 *
 * ⚠️ Это был «порт vector/emotes.py::pick» — эталон на Python удалён 15.08.2026 вместе с
 * пакетом `vector/` (у него не осталось вызывающих в продукте). Сверяться теперь не с
 * кем, поэтому спецификацией стал сам golden-файл docs/contracts/mascot-cases.json, а
 * сторожем — web/tests/mascot.contract.test.mjs. Меняешь приоритет веток здесь — правь
 * и контракт, осознанно: молча разойтись больше не с чем, но и поймать некому.
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

/** Эмоция маскота на «Главной» студента ПО ФАКТАМ (не по клику!):
 *  • средний < 3 или много пропусков → грустный (но подбадривает);
 *  • 3 ≤ средний < 4 → спокойный «руки в карманах»;
 *  • средний ≥ 4 → радостный. */
export function dashboardEmote({ average = 0, absences = 0 } = {}) {
  if ((average > 0 && average < 3) || absences >= 15) return 'sad-cheer'
  if (average >= 4) return 'happy-congrats'
  return 'neutral-idle'   // 3–4 или нет оценок — спокоен
}

// Предзагрузка спрайтов маскота: без неё при первой смене позы кадр грузится с диска
// и Вектор «зависает» пустым. Грузим один раз распространённые позы (кэш браузера).
const PRELOAD = ['neutral-idle', 'think-think', 'happy-cheer', 'happy-congrats',
                 'sad-cheer', 'warn-warn', 'neutral-cheer', 'surprise-idle']

// ⚠️ Та же версия арта, что в Mascot.vue, и по той же причине: файлы в `public/` не
// получают хеш в имени, поэтому без метки предзагрузка бережно кладёт в кэш СТАРЫЕ файлы.
// Держать значение синхронным с ART_VERSION в Mascot.vue.
export const ART_VERSION = 3
let _preloaded = false
export function preloadMascots() {
  if (_preloaded || typeof Image === 'undefined') return
  _preloaded = true
  for (const s of PRELOAD) { const img = new Image(); img.src = `/mascot/${s}.webp?v=${ART_VERSION}` }
}

// Анимированные состояния чата (WebP с альфой). Состояния store совпадают с именами
// файлов: greeting | idle | thinking | speaking. Предзагружаем thinking/speaking заранее,
// чтобы при первом вопросе не было паузы на загрузку (idle грузится сразу как дефолт).
export const CHAT_ANIMS = ['idle', 'greeting', 'thinking', 'speaking']

// Состояния ЭКРАНА ВХОДА: закрывает глаза лапами, пока набран пароль, и убирает обратно.
// Предзагружать обязательно: анимация должна начаться на ПЕРВОМ введённом символе, а не
// после того, как файл доедет по сети — иначе жест опаздывает и выглядит случайным.
export const LOGIN_ANIMS = ['eyes_close', 'eyes_open']
let _animsPreloaded = false
export function preloadAnims() {
  if (_animsPreloaded || typeof Image === 'undefined') return
  _animsPreloaded = true
  for (const a of [...CHAT_ANIMS, ...LOGIN_ANIMS]) {
    const img = new Image(); img.src = `/mascot/anim/${a}.webp?v=${ART_VERSION}`
  }
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
