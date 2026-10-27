// Как приложение называет себя серверу: заголовок X-Gb-App «apk/4.1.5+метка» (27.10.2026).
// Сервер показывает его админу в «Сессиях» и по нему просит обновиться приложение,
// отставшее на пять выпусков (server/app/client_app.py). Прав заголовок не даёт.
import { isNativeApp } from '../api/server'
import { isPcProgram } from './platform'

// Выпуск подставляет сборка из desktop_update.APP_VERSION (vite.config.js); в node-тестах
// его нет — тогда заголовок не шлём, и сервер нас не блокирует.
export const RELEASE = typeof __GB_RELEASE__ === 'string' ? __GB_RELEASE__ : ''
const STAMP = typeof __BUILD_STAMP__ === 'string' ? __BUILD_STAMP__ : ''

export function appPlatform() {
  if (isNativeApp()) return 'apk'
  if (isPcProgram()) return 'exe'
  return 'web'
}

export function appTag() {
  if (!RELEASE) return ''
  return `${appPlatform()}/${RELEASE}${STAMP ? '+' + STAMP : ''}`
}
