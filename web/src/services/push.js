// push.js — пуш-уведомления мобильного приложения (RuStore Push).
//
// Работает ТОЛЬКО внутри приложения: в обычном браузере нативного слоя нет, и все
// функции здесь тихо ничего не делают. Проверка идёт по мосту, который выставляет
// нативная часть (MainActivity), а не по user-agent — подделать UA легко, и сайт
// в мобильном браузере начал бы слать несуществующие токены.
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

const PENDING_KEY = 'gb_pending_event'      //переживает перезапуск приложения
const TOKEN_KEY = 'gb_push_token'           //чтобы отписаться при выходе

/** Мост от нативной части. Появляется только в приложении. */
function bridge() {
  return (typeof window !== 'undefined' && window.GradeBookPush) || null
}

export function isAvailable() {
  return !!bridge()
}

/**
 * Подтвердить токен устройства на сервере.
 * Зовётся ПОСЛЕ входа и при каждом запуске: сервер по этому вызову понимает, какому
 * аккаунту принадлежит телефон сейчас (на одном устройстве могли войти разные люди)
 * и что устройство живо.
 */
export async function registerToken() {
  const b = bridge()
  if (!b?.getToken) return false
  try {
    const token = await b.getToken()
    if (!token) return false
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

export function hasPendingEvent() {
  return !!localStorage.getItem(PENDING_KEY)
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
    // Маршруты в проекте БЕЗ имён, поэтому переход по пути, а не по name — иначе
    // router молча никуда не уйдёт.
    if (data?.kind === 'grade') {
      // Журнал сразу на нужном предмете.
      await router.push({ path: '/student/journal', query: { subject: data.subject || '' } })
      return true
    }
    if (data?.kind === 'schedule') {
      // Изменилось расписание группы. В subject лежит день недели — по нему страница
      // может сразу показать нужный день, а не заставлять его искать.
      await router.push({ path: '/student/schedule', query: { day: data.subject || '' } })
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
 * Подписаться на нажатия уведомлений. Нативная часть зовёт колбэк с event_id как при
 * «холодном» старте (приложение было закрыто), так и когда оно уже открыто.
 */
export function onNotificationTap(router) {
  const b = bridge()
  if (!b?.onTap) return
  b.onTap(async (eventId) => {
    rememberPendingEvent(eventId)
    await consumePendingEvent(router)
  })
}
