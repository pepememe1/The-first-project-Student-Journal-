/**
 * mediaSrc.js — откуда браузеру брать картинку мессенджера (17.10.2026).
 *
 * Значение поля (аватарка, баннер, гифка) бывает трёх видов, и каждое рисуется по-своему:
 *   • `/media/avatar?…` — подписанная ссылка боя на аватарку (`server/app/media_refs.py`).
 *     Она ОТНОСИТЕЛЬНА серверу, который её выдал: на сайте это тот же адрес, в программе
 *     — локальный сервер (он берёт картинку из кэша), а в приложении Android страница
 *     открыта с https://localhost, и без адреса сервера ссылка ушла бы в никуда;
 *   • гифка с CDN Klipy — внутри ПРОГРАММЫ идёт через локальный сервер
 *     (`/desk/media?u=…`), который держит её в зашифрованном кэше %TEMP%: окно программы
 *     в приватном режиме, и без этого каждая гифка качалась бы заново после каждого
 *     запуска. На сайте и в приложении — напрямую, их кэш живёт сам;
 *   • data:URL и всё прочее — как есть.
 *
 * ⚠️ Импорты относительные, а не через `@/`: функцию проверяет `node --test` без сборщика.
 * ⚠️ Подставлять картинку мессенджера в `<img>` мимо этой функции нельзя — в программе
 * она молча обойдёт кэш, а в приложении ссылка на аватарку не откроется вовсе. Держит
 * `web/tests/mediaSrc.test.mjs` (свойство по всем компонентам с картинками людей).
 */
import { getApiBase } from '../api/server.js'
import { isDesktopApp } from './platform.js'

export const AVATAR_PATH = '/media/avatar'
const KLIPY_HOST = 'static.klipy.com'

/** Гифка с CDN Klipy: только https, без порта и учётных данных — как проверяет программа. */
export function isKlipyUrl(value) {
  try {
    const u = new URL(value)
    return u.protocol === 'https:' && u.hostname === KLIPY_HOST && !u.port && !u.username
  } catch {
    return false
  }
}

/** Адрес для `<img src>` по значению поля. Пустое — пустая строка. */
export function mediaSrc(value) {
  if (!value || typeof value !== 'string') return ''
  if (value.startsWith(AVATAR_PATH + '?')) return (getApiBase() || '') + value
  if (isKlipyUrl(value) && isDesktopApp()) return '/desk/media?u=' + encodeURIComponent(value)
  return value
}

/**
 * Положить картинки в кэш заранее (программа: гифки пикера — «В тренде» и избранное).
 * Только в программе: на сайте и в телефоне это лишний трафик ради кэша браузера, который
 * и так наполнится при показе. Партиями в простое, чтобы не отнять сеть у переписки.
 */
export function prefetchImages(urls, { limit = 48, batch = 6 } = {}) {
  if (!isDesktopApp() || typeof Image === 'undefined') return 0
  const list = [...new Set((urls || []).filter(Boolean))].slice(0, limit).map(mediaSrc)
  const idle = (fn) => (typeof requestIdleCallback === 'function'
    ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 200))
  let i = 0
  const next = () => {
    for (const src of list.slice(i, i + batch)) {
      const img = new Image()
      img.decoding = 'async'
      img.src = src
    }
    i += batch
    if (i < list.length) idle(next)
  }
  idle(next)
  return list.length
}
