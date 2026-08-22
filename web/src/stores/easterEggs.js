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
import { ref } from 'vue'
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

export const useEasterStore = defineStore('easterEggs', () => {
  const active = ref('')          // id пасхалки, которая играет прямо сейчас
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
      if (data.egg) active.value = data.egg
      return data.egg || null
    } catch {
      return null            // нет сети или сервер занят — пасхалка просто не выпала
    } finally {
      busy.value = false
    }
  }

  /** Показать сцену без броска — для отладки и для повторного входа в уже начатую. */
  function show(egg) { active.value = egg }
  function close() { active.value = '' }

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

  return { active, lastUnlocked, roll, show, close, claim, clearToast }
})
