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
 *     запуска. На сайте и в приложении — С НАШЕГО СЕРВЕРА (`/media/klipy/<путь>`,
 *     27.10.2026): без VPN CDN Klipy открывается не у всех, а наш сервер до него доходит
 *     (`server/app/klipy_media.py`);
 *   • data:URL и всё прочее — как есть.
 *
 * ⚠️ Импорты относительные, а не через `@/`: функцию проверяет `node --test` без сборщика.
 * ⚠️ Подставлять картинку мессенджера в `<img>` мимо этой функции нельзя — в программе
 * она молча обойдёт кэш, а в приложении ссылка на аватарку не откроется вовсе. Держит
 * `web/tests/mediaSrc.test.mjs` (свойство по всем компонентам с картинками людей).
 */
import { getApiBase } from '../api/server.js'
import { isPcProgram } from './platform.js'

export const AVATAR_PATH = '/media/avatar'
export const KLIPY_PATH = '/media/klipy/'
const KLIPY_HOST = 'static.klipy.com'
//Путь на CDN — тот же шаблон, что сверяет сервер (`klipy_media._PATH_RE`): по нему
//сервер решает, скачивать ли файл, и ссылка мимо шаблона получила бы 404.
const KLIPY_FILE_RE = /^[A-Za-z0-9][A-Za-z0-9_\-.]*(?:\/[A-Za-z0-9][A-Za-z0-9_\-.]*){0,8}\.(gif|webp|mp4|jpg|jpeg|png)$/i

/** Гифка с CDN Klipy: только https, без порта и учётных данных — как проверяет программа. */
export function isKlipyUrl(value) {
  try {
    const u = new URL(value)
    return u.protocol === 'https:' && u.hostname === KLIPY_HOST && !u.port && !u.username
  } catch {
    return false
  }
}

/**
 * Тот же файл Klipy, но с нашего сервера: `/media/klipy/<путь на CDN>` (27.10.2026).
 * '' — не ссылка Klipy или путь не по шаблону (такую сервер не возьмёт).
 * Адрес — от сервера, как у аватарки: в приложении страница открыта с https://localhost.
 */
export function klipyMirror(value) {
  if (!isKlipyUrl(value)) return ''
  const u = new URL(value)
  const path = u.pathname.replace(/^\/+/, '')
  if (u.search || path.includes('..') || !KLIPY_FILE_RE.test(path)) return ''
  return (getApiBase() || '') + KLIPY_PATH + path
}

/** Адрес для `<img src>` по значению поля. Пустое — пустая строка. */
export function mediaSrc(value) {
  if (!value || typeof value !== 'string') return ''
  if (value.startsWith(AVATAR_PATH + '?')) return (getApiBase() || '') + value
  if (isKlipyUrl(value)) {
    if (isPcProgram()) return '/desk/media?u=' + encodeURIComponent(value)
    return klipyMirror(value) || value
  }
  return value
}

/**
 * Неподвижный первый кадр гифки Klipy — ЗАПАСНОЙ вид аватарки и баннера (27.10.2026,
 * требование Влада): гифка не открылась (Klipy недоступен) — человек видит кадр, как
 * обычную аватарку, а не пустой круг. Работает и в программе: кадр — картинка, её кэш
 * программы принимает. Сервер держит кадры аватарок и баннеров про запас
 * (`klipy_media.pin`). '' — не гифка Klipy.
 */
export function gifStillSrc(value) {
  const webp = klipyGifAs(value, '.webp')
  if (!webp) return ''
  return isPcProgram() ? '/desk/media?u=' + encodeURIComponent(webp) : klipyMirror(webp)
}

/**
 * Ролик MP4 вместо гифки Klipy (23.10.2026). Тот же адрес с `.mp4` вместо `.gif`: CDN
 * отдаёт оба, а ролик легче в десятки и сотни раз — у одной аватарки 13,7 МБ GIF против
 * 27 КБ MP4, и такую гифку телефон не смог показать вовсе. Так «гифки» показывают
 * Telegram, X и Discord. '' — не гифка Klipy, или окно программы: там гифки идут через
 * кэш `/desk/media`, который принимает только картинки. Ролик не открылся — вызывающий
 * показывает прежнюю картинку (`mediaSrc`).
 */
export function gifVideoSrc(value) {
  return klipyVariant(value, '.mp4')
}

/**
 * Первый кадр той же гифки — неподвижный webp по тому же адресу (у той же аватарки 55 КБ).
 * Показывается сразу, пока ролик ещё едет, — как у аватарок в Discord: вид появляется
 * мгновенно, движение — следом.
 */
export function gifPosterSrc(value) {
  return klipyVariant(value, '.webp')
}

/**
 * Запустить беззвучный ролик, как только он готов (`@canplay`). Одного `autoplay` мало:
 * проверено 26.10.2026 — Chromium грузил ролик до конца и оставлял его на первом кадре,
 * а явный `play()` запускал сразу. Отказ браузера (экономия батареи) не ошибка: остаётся
 * первый кадр.
 */
export function playMuted(e) {
  const v = e?.target
  if (!v) return
  v.muted = true
  v.play?.()?.catch?.(() => {})
}

function klipyVariant(value, ext) {
  if (isPcProgram()) return ''
  const variant = klipyGifAs(value, ext)
  return variant ? klipyMirror(variant) : ''
}

/** Ссылка Klipy на тот же файл в другом виде (`.mp4`, `.webp`); '' — не гифка Klipy. */
function klipyGifAs(value, ext) {
  if (!isKlipyUrl(value)) return ''
  const u = new URL(value)
  if (!/\.gif$/i.test(u.pathname)) return ''
  u.pathname = u.pathname.replace(/\.gif$/i, ext)
  return u.toString()
}

/**
 * Следить, виден ли элемент (с запасом в 200 px): ролик гифки качается, когда до него
 * долистали, и стоит на паузе вне экрана — иначе список чатов тянул бы все ролики разом.
 * Без IntersectionObserver считаем видимым. Возвращает функцию отписки.
 */
export function watchInView(el, onChange) {
  if (!el || typeof IntersectionObserver !== 'function') { onChange(true); return () => {} }
  const io = new IntersectionObserver((entries) => onChange(entries.some((e) => e.isIntersecting)),
    { rootMargin: '200px' })
  io.observe(el)
  return () => io.disconnect()
}

/**
 * Положить картинки в кэш заранее (программа: гифки пикера — «В тренде» и избранное).
 * Только в программе: на сайте и в телефоне это лишний трафик ради кэша браузера, который
 * и так наполнится при показе. Партиями в простое, чтобы не отнять сеть у переписки.
 */
export function prefetchImages(urls, { limit = 48, batch = 6 } = {}) {
  if (!isPcProgram() || typeof Image === 'undefined') return 0
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
