/**
 * backButton.js — системная кнопка «назад» в приложении для Android.
 *
 * Без своего обработчика плагин @capacitor/app только листает историю WebView. На главном
 * экране листать некуда, и кнопка не делала ничего: приложение нельзя было свернуть жестом
 * (проверено на Android 16, 23.10.2026). Порядок, принятый на Android:
 *   1. открыто окно или панель — закрыть верхнее (`backLayers.js`);
 *   2. главный экран роли или вход — свернуть приложение, как делает система;
 *   3. есть куда вернуться — шаг назад по истории;
 *   4. экран открыт первым (например, из уведомления) — на главный.
 * Главный экран проверяется раньше истории: после входа в истории лежит `/login`, и шаг
 * назад с главного вёл бы на вход, а оттуда маршрутизатор возвращает обратно.
 */
import { closeTopLayer, topLayer } from './backLayers.js'

/** Что сделать по «назад». Чистая функция: её проверяет тест. */
export function decideBack({ hasLayer, path, roots, canGoBack }) {
  if (hasLayer) return 'layer'
  if (roots.includes(path)) return 'minimize'
  if (canGoBack) return 'history'
  return 'home'
}

export async function installBackButton(router, roots) {
  const { App } = await import('@capacitor/app')
  await App.addListener('backButton', ({ canGoBack }) => {
    const action = decideBack({
      hasLayer: topLayer() !== null, path: router.currentRoute.value.path, roots, canGoBack,
    })
    if (action === 'layer') closeTopLayer()
    else if (action === 'history') window.history.back()
    else if (action === 'home') router.replace('/')
    else App.minimizeApp().catch(() => {})
  })
}
