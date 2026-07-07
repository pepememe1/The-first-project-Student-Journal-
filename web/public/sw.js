/*
 * sw.js — Service worker для PWA-режима (устанавливаемое приложение + офлайн-оболочка).
 *
 * Стратегии:
 *   • API (/auth, /web, /me, /sync, /admin, /connect, /health) — ТОЛЬКО сеть, никогда
 *     не кэшируем: это живые данные и авторизация (кэш тут = утечка/устаревание ПДн).
 *   • Навигация (открытие страниц SPA) — network-first: свежий index.html, а офлайн —
 *     отдаём закэшированную оболочку, чтобы приложение открылось без сети.
 *   • Статика (/assets/* с хэшем в имени) — cache-first: файлы неизменяемы, берём из
 *     кэша мгновенно, чего нет — догружаем и кладём.
 */
const VERSION = 'gb-v1'
const SHELL = `${VERSION}-shell`
const ASSETS = `${VERSION}-assets`
const APP_SHELL = ['/', '/index.html', '/favicon.svg', '/manifest.webmanifest']

// Пути API — их запросы проходят мимо кэша.
const API_PREFIXES = ['/auth', '/me', '/sync', '/admin', '/connect', '/web', '/health', '/docs', '/openapi.json']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(APP_SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  // Чистим старые версии кэша при обновлении приложения.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return // POST/PUT/DELETE (вход, запись) — всегда сеть

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return // сторонние (шрифты) — как есть

  // API — только сеть, без кэша.
  if (API_PREFIXES.some((p) => url.pathname.startsWith(p))) return

  // Навигация — network-first с офлайн-фолбэком на оболочку SPA.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone()
          caches.open(SHELL).then((c) => c.put('/index.html', copy))
          return resp
        })
        .catch(() => caches.match('/index.html').then((r) => r || caches.match('/')))
    )
    return
  }

  // Статика (хэшированные /assets/*) — cache-first.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((resp) => {
          if (resp.ok && resp.type === 'basic') {
            const copy = resp.clone()
            caches.open(ASSETS).then((c) => c.put(request, copy))
          }
          return resp
        })
    )
  )
})
