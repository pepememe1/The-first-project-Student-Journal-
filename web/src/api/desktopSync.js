/**
 * desktopSync.js — состояние синхронизации ПРОГРАММЫ (не сайта).
 *
 * Отвечает на вопрос, который до этого не задавал никто: «уехали ли мои правки на
 * сервер». Синк десктопа умеет различать четыре разные беды (нет сети, не проходит вход,
 * сервер отверг часть правок, неразрешённые конфликты оценок), но до появления этого
 * модуля они попадали ТОЛЬКО в `gradebook.log` — то есть человек узнавал о потерянной
 * оценке никогда.
 *
 * ⚠️ Источник — `GET /desk/sync/status`, который существует ТОЛЬКО в локальном сервере
 * внутри программы. На сайте такого маршрута нет вовсе, и это не проблема, а способ
 * определения: получили не-200 — значит синхронизации здесь не существует, замолкаем
 * навсегда. Отдельный флаг «мы внутри программы» специально НЕ используем: единственный
 * кандидат (`localStorage.gb.embed`) сегодня не выставляется в рабочем режиме, и опираться
 * на него значило бы построить проверку на том, что и так сломано.
 */
import { ref } from 'vue'

import { getAccess } from './tokens'

//Раз в минуту: синк ходит на сервер каждые 30 с, и знать о беде раньше следующего цикла
//всё равно неоткуда. Частить незачем — на боевой машине одно ядро.
const POLL_MS = 60_000

export const syncState = ref(null)   //null — неизвестно/не программа; иначе ответ сервера

let timer = null
let stopped = false

function issuesOf(st) {
  if (!st || !st.available) return []
  const out = []
  if (st.auth_error) out.push({ kind: 'auth', detail: String(st.auth_error) })
  if (st.conflicts > 0) out.push({ kind: 'conflicts', count: st.conflicts })
  const rejected = st.rejected && typeof st.rejected === 'object' ? st.rejected : {}
  const rejectedTotal = Object.values(rejected).reduce((a, b) => a + (Number(b) || 0), 0)
  if (rejectedTotal > 0) out.push({ kind: 'rejected', count: rejectedTotal })
  return out
}

/** Список проблем; пустой — либо всё хорошо, либо мы не в программе. */
export function syncIssues() {
  return issuesOf(syncState.value)
}

async function poll() {
  if (stopped) return
  try {
    //Тот же токен, что и у остальных запросов (`api/tokens`), а не своё чтение
    //localStorage: ключ там уже менялся, и вторая копия правила разъехалась бы молча.
    const token = getAccess()
    const r = await fetch('/desk/sync/status', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!r.ok) {
      //404 — это сайт, маршрута нет и не будет. 403 — чужой вызывающий. В обоих случаях
      //повторять бессмысленно: замолкаем, чтобы не сыпать запросами в браузере.
      stop()
      return
    }
    syncState.value = await r.json()
  } catch {
    //Сеть до СВОЕГО же локального сервера отвалиться не может иначе как при его
    //остановке (закрывают программу) — молча ждём следующего тика, не гасим значок.
  }
}

export function start() {
  if (timer || stopped) return
  poll()
  //⚠️ Окно свёрнуто — не спрашиваем. Здесь запрос идёт к СВОЕМУ же локальному серверу и
  //батарею телефона не тратит (программа живёт на ПК), но правило «опрос не ходит в сеть,
  //пока его никто не видит» держится БЕЗ исключений намеренно: исключения размножаются,
  //и следующий таймер заведут по образцу этого. Цена соблюдения — одна строка.
  timer = setInterval(() => { if (!document.hidden) poll() }, POLL_MS)
  //Вернулись к окну — сразу свежее состояние, а не через минуту.
  document.addEventListener('visibilitychange', onVisible)
}

function onVisible() {
  if (!document.hidden && !stopped) poll()
}

export function stop() {
  stopped = true
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  document.removeEventListener('visibilitychange', onVisible)
  syncState.value = null
}
