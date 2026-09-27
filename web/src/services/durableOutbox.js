/**
 * durableOutbox.js — надёжное зеркало очереди неотправленных правок в приложении
 * (исследование синка W-13в, 26.09.2026).
 *
 * По документации Capacitor localStorage в приложении «временный»: ОС вправе освободить
 * его при нехватке места. Для кэша это неприятно, для очереди неотправленных оценок — это
 * потеря работы преподавателя. `@capacitor/preferences` пишет в SharedPreferences
 * Android, которые система сама не чистит.
 *
 * ⚠️ Плагин нативный: он есть только в APK с 4.1 (сборка 14). В старом APK вызовы честно
 * отказывают — зеркало просто не работает, очередь живёт как раньше. На сайте и в
 * программе зеркала нет вовсе: там localStorage не «временный».
 */
import { Capacitor } from '@capacitor/core'

import { restoreFromDurable, setDurableStore } from '../api/outbox.js'

export async function initDurableOutbox() {
  if (!Capacitor.isNativePlatform()) return false
  const { Preferences } = await import('@capacitor/preferences')
  setDurableStore({
    get: async (key) => (await Preferences.get({ key })).value,
    set: (key, value) => Preferences.set({ key, value }),
  })
  return restoreFromDurable()
}
