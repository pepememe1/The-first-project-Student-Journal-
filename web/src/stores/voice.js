/**
 * voice.js — настройки ГОЛОСОВОГО ВВОДА (микрофон → текст) на всех платформах.
 *
 * ПОЧЕМУ НАСТРОЙКА УСТРОЙСТВА, А НЕ АККАУНТА (localStorage, как у озвучки `tts.js`).
 * Микрофон — свойство КОМПЬЮТЕРА, а не человека: у преподавателя в кабинете гарнитура, в
 * лаборатории — камера со встроенным микрофоном, дома — что-то третье. Если хранить выбор
 * на сервере, он поедет за аккаунтом и на каждой второй машине будет указывать на
 * несуществующее устройство. Тумблер «выключить голосовой ввод» тоже локальный: причина
 * выключить его — обычно шумный кабинет, то есть опять место, а не человек.
 *
 * ⚠️ id устройств браузер выдаёт ТОЛЬКО после разрешения на микрофон, а после смены
 * разрешений/перезагрузки они могут поменяться. Поэтому сохранённый id — «пожелание», а
 * не гарантия: если устройство исчезло, откатываемся на системное по умолчанию, а не
 * падаем с ошибкой. Пустая строка = «как в системе».
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { listMicrophones, recordingSupported } from '@/utils/voiceInput'

const LS_ENABLED = 'gb.voice.enabled'
const LS_DEVICE = 'gb.voice.device'

function readEnabled() {
  //По умолчанию ВКЛЮЧЕНО: способность есть — значит должна быть под рукой. Выключают её
  //осознанно (шумно, чужой микрофон), и вот это решение мы запоминаем.
  try { return localStorage.getItem(LS_ENABLED) !== 'off' } catch { return true }
}
function readDevice() {
  try { return localStorage.getItem(LS_DEVICE) || '' } catch { return '' }
}

export const useVoiceStore = defineStore('voice', () => {
  const enabled = ref(readEnabled())
  const deviceId = ref(readDevice())
  const devices = ref([])            // [{ deviceId, label }]
  const loading = ref(false)
  const denied = ref(false)          // человек отказал в доступе к микрофону

  //Умеет ли устройство записывать вообще. Без этого весь раздел настроек бессмысленен —
  //лучше показать причину, чем тумблер, который ничего не меняет.
  const supported = computed(() => recordingSupported())

  //Название выбранного — для подписи в интерфейсе.
  const currentLabel = computed(() => {
    if (!deviceId.value) return 'Как в системе'
    const d = devices.value.find((x) => x.deviceId === deviceId.value)
    return d ? d.label : 'Устройство не найдено'
  })

  //Выбранный id, пригодный для записи: исчезнувшее устройство молча заменяем системным.
  const effectiveDeviceId = computed(() => {
    if (!deviceId.value) return ''
    const known = devices.value.some((x) => x.deviceId === deviceId.value)
    //Список ещё не загружен — доверяем сохранённому (иначе первая запись всегда шла бы
    //в системный микрофон, хотя человек выбрал другой).
    return (!devices.value.length || known) ? deviceId.value : ''
  })

  function setEnabled(on) {
    enabled.value = !!on
    try { localStorage.setItem(LS_ENABLED, on ? 'on' : 'off') } catch { /* приватный режим */ }
  }
  function toggle() { setEnabled(!enabled.value) }

  function setDevice(id) {
    deviceId.value = id || ''
    try {
      if (id) localStorage.setItem(LS_DEVICE, id)
      else localStorage.removeItem(LS_DEVICE)
    } catch { /* приватный режим */ }
  }

  /** Обновить список микрофонов. `ask` — можно ли спросить разрешение (только из жеста). */
  async function refresh(ask = false) {
    if (!supported.value) { devices.value = []; return }
    loading.value = true
    try {
      devices.value = await listMicrophones(ask)
      //Названия приходят пустыми, пока нет разрешения — это не отказ, просто «пока
      //неизвестно». Отказ фиксируем отдельно, у него другая подпись в интерфейсе.
      denied.value = false
    } catch (e) {
      devices.value = []
      denied.value = e?.name === 'NotAllowedError'
    } finally { loading.value = false }
  }

  return {
    enabled, deviceId, devices, loading, denied,
    supported, currentLabel, effectiveDeviceId,
    setEnabled, toggle, setDevice, refresh,
  }
})
