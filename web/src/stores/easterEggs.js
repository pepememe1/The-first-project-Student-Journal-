// easterEggs.js — единая точка запуска пасхалок (docs/PLAN-EASTER-EGGS.md).
//
// ━━ ПОЧЕМУ ВСЁ ЧЕРЕЗ ОДИН СТОР ━━
// Пасхалки живут на РАЗНЫХ страницах, но правила у них общие: бросок считает сервер,
// одновременно показывается только одна, ачивка закрывается сверкой со следом
// срабатывания. Расписать это по страницам значило бы пятнадцать раз повторить одно
// и то же и однажды где-нибудь забыть — ровно так у нас уже терялись проверки.
//
// ━━ ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО ━━
// Ни одного `Math.random()`. Бросок делает сервер (`POST /web/easter-eggs/roll`):
// иначе редкость правится через инструменты разработчика за секунду, а телефон и ПК
// давали бы человеку два независимых шанса на одно событие.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { easterApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'

// Какая ачивка какой пасхалкой выдаётся. Пара продублирована на сервере и там же
// проверяется — здесь она нужна лишь чтобы не таскать её по компонентам.
export const EGG_ACHIEVEMENT = {
  deltarune_tree:      'deltarune_egg',
  portal_cake:         'portal_cake_lie',
  undertale_save:      'undertale_resolve',
  papers_please_stamp: 'papers_glory',
  binding_of_isaac_d6: 'isaac_reroll',
  dark_souls_logout:   'darksouls_session',
  gman_observer:       'gman_observer',
  cyberpunk_login:     'cyberpunk_samurai',
  detroit_led:         'detroit_led',
  stanley_parable_404: 'stanley_427',
  ultrakill_rank:      'ultrakill_fuel',
  doom_avatar:         'doom_hud_face',
  disco_elysium_voice: 'disco_listen',
  hotline_miami:       'hotline_50',
  fnaf_night_mode:     'fnaf_night',
}

// Пасхалки, которые живут ВНУТРИ страницы, а не накрывают экран: кольцо Detroit вместо
// кружка статуса, состояние DOOM на аватарке, кубик Isaac в журнале, счётчик ULTRAKILL,
// штамп Papers Please на профиле, звезда сохранения Undertale.
//
// ⚠️ У них ОТДЕЛЬНЫЙ канал, и это не косметика. Полноэкранная сцена одна за раз —
// иначе две шутки наложатся и обе перестанут читаться. Но кольцо на аватарке висит
// постоянно: положи его в тот же слот, и оно навсегда заняло бы единственное место,
// то есть ни одна другая пасхалка за сессию больше не выпала бы вовсе.
const IN_PAGE = new Set([
  'detroit_led', 'doom_avatar', 'ultrakill_rank',
  'binding_of_isaac_d6', 'disco_elysium_voice', 'papers_please_stamp', 'undertale_save',
])

// Пасхалки, которые МОЖНО ПРОПУСТИТЬ, если уйти со страницы. Только их сторожит
// подтверждение перехода (см. router/index.js).
//
// ⚠️ Постоянных здесь нет НАМЕРЕННО, и это важнее, чем кажется. Кольцо Detroit,
// состояние DOOM и счётчик ULTRAKILL висят у студента всё время — попади они в этот
// список, продукт спрашивал бы «точно уйти?» на КАЖДОМ переходе между вкладками.
// Защита, которая срабатывает всегда, — это не защита, а поломка навигации.
const MISSABLE_IN_PAGE = new Set([
  'binding_of_isaac_d6', 'papers_please_stamp', 'undertale_save', 'disco_elysium_voice',
])

export const useEasterStore = defineStore('easterEggs', () => {
  const active = ref('')          // полноэкранная сцена, которая играет прямо сейчас
  const inPage = ref({})          // { id: true } — пасхалки внутри страницы, их может быть несколько
  const lastUnlocked = ref(null)  // для тоста «достижение открыто»
  const busy = ref(false)

  /** Бросок. Принимает id или список (тогда сработает не больше ОДНОЙ). */
  async function roll(egg) {
    const auth = useAuthStore()
    // Пасхалки только у студентов. Сервер это тоже проверяет — здесь просто не тратим
    // запрос: преподаватель и админ переключают вкладки не реже, а показывать нечего.
    if (auth.role !== 'student' || active.value || busy.value) return null
    busy.value = true
    try {
      const body = Array.isArray(egg) ? { eggs: egg } : { egg }
      const { data } = await easterApi.roll(body)
      if (data.egg) place(data.egg)
      return data.egg || null
    } catch {
      return null            // нет сети или сервер занят — пасхалка просто не выпала
    } finally {
      busy.value = false
    }
  }

  /** Спросить сервер, что показать сразу после входа. */
  async function afterLogin() {
    const auth = useAuthStore()
    if (auth.role !== 'student') return null
    try {
      const { data } = await easterApi.onLogin()
      // DOOM детерминирован и живёт СВОИМ полем: он не «выпал», он просто включён.
      if (data.hud) place('doom_avatar')
      if (data.egg) place(data.egg)
      return data.egg || null
    } catch {
      return null
    }
  }

  /**
   * Разложить выпавшую пасхалку по нужному каналу (см. IN_PAGE выше).
   *
   * ⚠️ У полноэкранной сцены заводится ПРЕДОХРАНИТЕЛЬ. Каждая сцена закрывает себя сама
   * по таймеру, и это нормально — пока таймер заводится. Но однажды он не завёлся:
   * Stanley и Far Cry раскладывали реплики по длительности mp3 и ждали `loadedmetadata`,
   * а без звука это событие не приходит никогда. Сцена оставалась «играющей» вечно, и
   * цена была не косметическая: занятый слот `active` запрещает выпадать всем остальным
   * пасхалкам до конца сессии, а подтверждение перехода (23.08.2026) спрашивало бы
   * «точно уйти?» на каждой вкладке.
   *
   * Пять минут — заведомо больше любой нашей сцены (самая длинная, ночная смена FNAF,
   * идёт около минуты) и заведомо меньше «навсегда». Предохранитель не заменяет
   * собственный таймер сцены и не должен срабатывать никогда: сработал — это дефект,
   * и он теперь виден в консоли, а не проглочен.
   */
  const STUCK_MS = 5 * 60 * 1000
  let stuckTimer = 0
  function place(egg) {
    if (IN_PAGE.has(egg)) { inPage.value = { ...inPage.value, [egg]: true }; return }
    active.value = egg
    clearTimeout(stuckTimer)
    stuckTimer = setTimeout(() => {
      if (active.value !== egg) return
      console.warn('[пасхалки] сцена не закрыла себя сама и снята предохранителем:', egg)
      active.value = ''
    }, STUCK_MS)
  }

  /** Спросить журнал: счётчик стиля отличнику и/или редкая находка. */
  async function rollJournal() {
    const auth = useAuthStore()
    if (auth.role !== 'student') return
    try {
      const { data } = await easterApi.journal()
      if (data.ultrakill) place('ultrakill_rank')
      if (data.egg) place(data.egg)
      return data
    } catch {
      return null                // нет сети — журнал просто откроется без шуток
    }
  }

  /** Показать сцену без броска — для отладки и для повторного входа в уже начатую. */
  function show(egg) { place(egg) }
  function close() { clearTimeout(stuckTimer); active.value = '' }
  /** Убрать пасхалку страницы: доиграла и больше не нужна. */
  function closeInPage(egg) {
    const next = { ...inPage.value }
    delete next[egg]
    inPage.value = next
  }

  /**
   * Есть ли прямо сейчас на экране пасхалка, которую человек рискует ПРОПУСТИТЬ,
   * уйдя со страницы. Пустая строка — нечего терять.
   */
  const pending = computed(() => {
    if (active.value) return active.value
    return Object.keys(inPage.value).find((k) => MISSABLE_IN_PAGE.has(k)) || ''
  })

  /**
   * Человек подтвердил, что уходит. Снимаем пропускаемую пасхалку — иначе кубик или
   * штамп уехали бы за ним на следующую страницу, где им нечего делать (штамп ищет
   * профиль, кубик — клетки оценок) и где они висели бы мёртвой картинкой.
   * ⚠️ Постоянные (кольцо, HUD, счётчик) НЕ трогаем: их не «пропускают».
   */
  function dismissPending() {
    clearTimeout(stuckTimer)
    active.value = ''
    const next = { ...inPage.value }
    for (const k of Object.keys(next)) if (MISSABLE_IN_PAGE.has(k)) delete next[k]
    inPage.value = next
  }

  /**
   * Находка доиграна: просим сервер закрыть её ачивкой.
   * Сервер сверяет, что пасхалка ДЕЙСТВИТЕЛЬНО срабатывала у этого человека, — то есть
   * накрутить список запросом нельзя. Молча глотать отказ нельзя тоже: человек уже
   * увидел сцену и ждёт награды, поэтому тост показываем только по факту успеха.
   */
  async function claim(egg) {
    const achievement = EGG_ACHIEVEMENT[egg]
    if (!achievement) return false
    try {
      const { data } = await easterApi.claim({ egg, achievement })
      if (data.unlocked) lastUnlocked.value = achievement
      return !!data.unlocked
    } catch {
      return false
    }
  }

  function clearToast() { lastUnlocked.value = null }

  return { active, inPage, lastUnlocked, pending, roll, afterLogin, rollJournal,
           show, close, closeInPage, dismissPending, claim, clearToast }
})
