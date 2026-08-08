// push.js — пуш-уведомления мобильного приложения (RuStore Push).
//
// Работает ТОЛЬКО внутри приложения: в обычном браузере нативного слоя нет, и все
// функции здесь тихо ничего не делают. Проверка идёт по мосту, который выставляет
// нативная часть (MainActivity), а не по user-agent — подделать UA легко, и сайт
// в мобильном браузере начал бы слать несуществующие токены.
//
// ⚠️ ПОЧЕМУ МОСТ ИМЕННО `window.GradeBookPushNative`. Прежняя версия ждала объект
// `window.GradeBookPush`, который натив создавал скриптом при старте окна. Его стирала
// любая загрузка документа, поэтому к моменту запуска Vue моста уже не существовало —
// и пуши не работали НИ У КОГО (в боевой базе не было ни одного токена устройства).
// `GradeBookPushNative` регистрируется через addJavascriptInterface, и Android
// подставляет его в каждый новый документ сам. Старое имя оставлено запасным путём:
// на телефонах с ещё не обновлённым APK другого моста нет.
//
// ⚠️ ТОКЕН ПОЯВЛЯЕТСЯ НЕ СРАЗУ. RuStore отдаёт его асинхронно, обычно через секунду
// после запуска, а на холодном старте дольше. Один вопрос «есть токен?» в момент
// загрузки страницы почти всегда получал бы «нет» — поэтому спрашиваем несколько раз.
//
// Что здесь важно понимать про ПЕРЕХОД по уведомлению. В самом пуше НЕТ ни предмета,
// ни балла — только event_id (тело уведомления идёт через серверы RuStore, а
// успеваемость студента отдавать посреднику нельзя). Поэтому приложение по event_id
// спрашивает у НАШЕГО сервера, куда открыть экран.
//
// Отсюда же решается «сгоревший токен входа»: event_id кладётся в localStorage и
// живёт там, пока переход не совершён. Не залогинен — покажется вход, а после него
// переход всё равно произойдёт. Событие не теряется.

import { meApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'

const PENDING_KEY = 'gb_pending_event'      //переживает перезапуск приложения
const TOKEN_KEY = 'gb_push_token'           //чтобы отписаться при выходе

//Сколько ждём токен от RuStore. 15 попыток по 2 с — это 30 секунд: дольше держать
//таймер бессмысленно, человек к этому времени уже работает, а следующая попытка
//случится при очередном запуске приложения.
const TOKEN_TRIES = 15
const TOKEN_DELAY_MS = 2000

/** Нативный мост. Появляется только в приложении. */
function native() {
  return (typeof window !== 'undefined' && window.GradeBookPushNative) || null
}

/** Мост старого APK (до 1.0.5). Ненадёжен, но лучше, чем ничего. */
function legacy() {
  return (typeof window !== 'undefined' && window.GradeBookPush) || null
}

export function isAvailable() {
  return !!(native() || legacy())
}

/** Токен устройства ('' — ещё не выдан). Синхронный у нового моста, promise у старого. */
async function readToken() {
  const n = native()
  if (n?.getToken) {
    try { return String(n.getToken() || '') } catch { return '' }
  }
  const l = legacy()
  if (l?.getToken) {
    try { return String((await l.getToken()) || '') } catch { return '' }
  }
  return ''
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * Состояние пушей для раздела «Настройки» — почему уведомления не приходят.
 * Молчаливый отказ здесь самый вредный: и человек, и мы узнаём о нём только по
 * отсутствию уведомлений, то есть никогда.
 */
export function diagnostics() {
  const n = native()
  if (!n?.diagnostics) return null
  try { return JSON.parse(n.diagnostics() || '{}') } catch { return null }
}

/**
 * Подтвердить токен устройства на сервере.
 * Зовётся ПОСЛЕ входа и при каждом запуске: сервер по этому вызову понимает, какому
 * аккаунту принадлежит телефон сейчас (на одном устройстве могли войти разные люди)
 * и что устройство живо.
 *
 * Ждёт появления токена в фоне — см. пояснение про асинхронность RuStore выше.
 */
export async function registerToken() {
  if (!isAvailable()) return false
  for (let i = 0; i < TOKEN_TRIES; i += 1) {
    const token = await readToken()
    if (token) {
      try {
        await meApi.registerPushToken(token, 'android')
        localStorage.setItem(TOKEN_KEY, token)
        return true
      } catch (e) {
        // Пуши — дополнение, а не условие работы. Молчим, чтобы не пугать студента
        // ошибкой на пустом месте: журнал работает и без уведомлений.
        console.debug('[push] регистрация токена не удалась:', e)
        return false
      }
    }
    await sleep(TOKEN_DELAY_MS)
  }
  console.debug('[push] токен устройства так и не появился')
  return false
}

/**
 * Отписать устройство при выходе из аккаунта.
 * Без этого следующий вошедший (или бывший владелец телефона) продолжал бы получать
 * чужие уведомления — сервер тоже перезапишет владельца, но только при следующем
 * запуске, а до него уведомления улетали бы не тому человеку.
 */
export async function unregisterToken() {
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) return
  try {
    await meApi.deletePushToken(token)
  } catch (e) {
    console.debug('[push] отписка не удалась:', e)
  } finally {
    localStorage.removeItem(TOKEN_KEY)
  }
}

/** Запомнить нажатое уведомление — переход выполнится, когда появится сессия. */
export function rememberPendingEvent(eventId) {
  if (eventId) localStorage.setItem(PENDING_KEY, String(eventId))
}

/**
 * Куда открыть экран по событию.
 *
 * Вынесено отдельно и покрывает ВСЕ виды событий: раньше здесь были только оценка и
 * расписание, а домашнее задание, отметка в чате, напоминание и мероприятие открывали
 * приложение «в никуда» — человек нажимал уведомление и оказывался на своей обычной
 * первой странице, будто нажатие ничего не значило.
 *
 * Маршруты в проекте разложены по ролям (`/student/...`, `/teacher/...`), общего
 * `/messages` не существует — поэтому путь собирается от роли вошедшего.
 */
export function routeForEvent(data, role) {
  const kind = data?.kind || ''
  const conv = data?.payload?.conversation_id || ''
  const base = role ? `/${role}` : '/'
  //У родителя журнал — это его корневая страница, отдельного /parent/journal нет.
  const journal = role === 'student' ? '/student/journal' : base
  switch (kind) {
    case 'grade':
    case 'grade_changed':
      return { path: journal, query: { subject: data.subject || '' } }
    case 'homework':
      return { path: journal, query: { subject: data.subject || '' } }
    case 'schedule':
    case 'schedule_changed':
      return role === 'parent' ? { path: base } : { path: `${base}/schedule` }
    case 'mention':
    case 'reminder':
      return { path: `${base}/messages`, query: conv ? { chat: conv } : {} }
    case 'event':
      return { path: base }
    default:
      return null
  }
}

/**
 * Выполнить отложенный переход, если он есть.
 * router передаётся снаружи, чтобы модуль не зависел от конкретного роутера и
 * оставался тестируемым.
 *
 * Событие снимаем ВСЕГДА, даже когда сервер ответил ошибкой: иначе «битый» id
 * заставлял бы приложение дёргать сервер при каждом запуске до бесконечности.
 */
export async function consumePendingEvent(router) {
  const id = localStorage.getItem(PENDING_KEY)
  if (!id) return false
  localStorage.removeItem(PENDING_KEY)
  try {
    const { data } = await meApi.getEvent(id)
    let role = ''
    try { role = useAuthStore().role || '' } catch { role = '' }
    const to = routeForEvent(data, role)
    if (to) {
      await router.push(to)
      return true
    }
  } catch (e) {
    // 404 — событие чужое или уже неактуально (например, вошёл другой аккаунт).
    // Это штатная ситуация, а не сбой: просто не переходим.
    console.debug('[push] событие недоступно:', e)
  }
  return false
}

/**
 * Начать слежение за нажатиями уведомлений.
 *
 * ЗАБИРАЕМ у натива, а не ждём его звонка. Нажатие может случиться, когда приложение
 * закрыто, и веб-слой поднимется через несколько секунд после — колбэк «натив зовёт
 * JS» в таких условиях гонка, которая тихо теряет событие. Натив кладёт нажатие в своё
 * хранилище, а мы забираем его при старте и при каждом возврате в приложение.
 */
export function onNotificationTap(router) {
  const drain = async () => {
    const n = native()
    if (!n?.consumeTap) return
    let id = ''
    try { id = String(n.consumeTap() || '') } catch { id = '' }
    if (!id) return
    rememberPendingEvent(id)
    await consumePendingEvent(router)
  }

  //Старый мост умел только звонить сам — на не обновлённых APK оставляем как было.
  const l = legacy()
  if (!native() && l?.onTap) {
    l.onTap(async (eventId) => {
      rememberPendingEvent(eventId)
      await consumePendingEvent(router)
    })
    return
  }

  drain()
  //Возврат в приложение из шторки — это смена ВИДИМОСТИ, а не перезапуск: без этой
  //подписки нажатие на уведомление при уже открытом приложении не сработало бы.
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) drain()
    })
  }
}
