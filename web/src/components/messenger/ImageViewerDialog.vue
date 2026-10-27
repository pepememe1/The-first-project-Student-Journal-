<script setup>
/**
 * ImageViewerDialog.vue — просмотр картинки во весь экран, как в Telegram (27.10.2026,
 * требование Влада): нажал на аватарку группы — открылась крупно; сверху карандаш
 * («поменять») и три точки с меню «Удалить · Скачать · Поделиться». «Поделиться» —
 * выбрать чат, и картинка уйдёт туда изображением.
 *
 * Значение бывает трёх видов, и окно понимает все: data:URL (своя картинка), подписанная
 * ссылка боя (`/media/avatar?…` — так приходит аватарка беседы) и гифка Klipy.
 *
 * ⚠️ «Поделиться» отправляет КОПИЮ, а не ссылку на аватарку беседы: в чате-адресате могут
 * быть люди, которые в исходной беседе не состоят, а сменённая потом аватарка не должна
 * переписывать уже отправленное сообщение. Гифка Klipy уходит гифкой (тот же вид, что из
 * пикера), своя картинка — сообщением-изображением (`kind: 'image'`).
 * ⚠️ Права на «поменять» и «удалить» решает СЕРВЕР; кнопки здесь только прячутся.
 */
import { ref, computed, onBeforeUnmount } from 'vue'
import { messengerApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import { useToast } from '@/composables/useToast'
import { gifStillSrc, isKlipyUrl, mediaSrc } from '@/utils/mediaSrc'
import GbIcon from '@/components/ui/GbIcon.vue'
import ForwardPicker from '@/components/messenger/ForwardPicker.vue'

const props = defineProps({
  value: { type: String, required: true },
  title: { type: String, default: '' },
  canEdit: { type: Boolean, default: false },
  canDelete: { type: Boolean, default: false },
  fileName: { type: String, default: 'image' },
})
const emit = defineEmits(['close', 'edit', 'delete'])
const loc = useLocaleStore()
const toast = useToast()

const menuOpen = ref(false)
const sharing = ref(false)
const busy = ref(false)
const failed = ref(false)
const stillFailed = ref(false)

const shown = computed(() => mediaSrc(props.value))
//Гифка не открылась (Klipy недоступен) — первый кадр, как у аватарки (`Avatar.vue`).
const still = computed(() => gifStillSrc(props.value))

function closeMenu(e) {
  if (!e?.target?.closest?.('[data-viewer-menu]')) menuOpen.value = false
}
document.addEventListener('click', closeMenu, true)
onBeforeUnmount(() => document.removeEventListener('click', closeMenu, true))

/** Файл картинки: data:URL — сам по себе, ссылку боя и гифку — скачать. */
async function asBlob() {
  const res = await fetch(shown.value)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.blob()
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result || ''))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(blob)
  })
}

async function download() {
  menuOpen.value = false
  busy.value = true
  try {
    const blob = await asBlob()
    const ext = (blob.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg').split('+')[0]
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.fileName.replace(/[\\/:*?"<>|]+/g, '_') || 'image'}.${ext}`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    toast.error(loc.t('imageViewer.downloadFailed', 'Не удалось скачать картинку'))
  } finally { busy.value = false }
}

/** Что отправить и каким видом. Гифка Klipy — гифкой, остальное — изображением. */
async function shareBody() {
  if (isKlipyUrl(props.value)) return { body: props.value, kind: 'gif' }
  if (props.value.startsWith('data:image/')) return { body: props.value, kind: 'image' }
  return { body: await blobToDataUrl(await asBlob()), kind: 'image' }
}

async function share(convIds) {
  sharing.value = false
  if (!convIds?.length) return
  busy.value = true
  try {
    const { body, kind } = await shareBody()
    let sent = 0
    for (const id of convIds) {
      try {
        const nonce = (crypto.randomUUID?.() || String(Date.now()) + Math.random())
        await messengerApi.send(id, body, 0, nonce, { kind })
        sent += 1
      } catch { /* остальные чаты пробуем дальше — итог скажем числом */ }
    }
    if (sent === convIds.length) toast.success(loc.t('imageViewer.shared', 'Картинка отправлена'))
    else if (sent) toast.success(loc.t('imageViewer.sharedPart', { n: sent, total: convIds.length }))
    else toast.error(loc.t('imageViewer.shareFailed', 'Не удалось отправить картинку'))
  } catch {
    toast.error(loc.t('imageViewer.shareFailed', 'Не удалось отправить картинку'))
  } finally { busy.value = false }
}

function askDelete() {
  menuOpen.value = false
  emit('delete')
}
</script>

<template>
  <div v-dialog class="fixed inset-0 z-[70] flex flex-col bg-black/90" @click.self="emit('close')">
    <!-- Верхняя полоса: закрыть и заголовок слева, действия справа — как в Telegram. -->
    <div class="flex shrink-0 items-center gap-2 px-3 py-2 text-white">
      <button type="button" class="grid size-10 place-items-center rounded-full hover:bg-white/10"
              :aria-label="loc.t('common.close', 'Закрыть')" @click="emit('close')">
        <GbIcon name="close" class="size-5" />
      </button>
      <p class="min-w-0 flex-1 truncate text-sm font-semibold">{{ title }}</p>
      <button v-if="canEdit" type="button" class="grid size-10 place-items-center rounded-full hover:bg-white/10"
              :aria-label="loc.t('imageViewer.edit', 'Поменять')" :title="loc.t('imageViewer.edit', 'Поменять')"
              @click="emit('edit')">
        <GbIcon name="edit" class="size-5" />
      </button>
      <div class="relative" data-viewer-menu>
        <button type="button" class="grid size-10 place-items-center rounded-full hover:bg-white/10"
                :aria-label="loc.t('imageViewer.more', 'Ещё')" :aria-expanded="menuOpen"
                :disabled="busy" @click="menuOpen = !menuOpen">
          <GbIcon name="more" class="size-5" />
        </button>
        <div v-if="menuOpen" role="menu"
             class="absolute right-0 top-11 z-10 w-48 overflow-hidden rounded-lg border border-border2 bg-card py-1 text-sm text-text shadow-card">
          <button v-if="canDelete" type="button" role="menuitem"
                  class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-red hover:bg-bg2" @click="askDelete">
            <GbIcon name="delete" class="size-4" />{{ loc.t('imageViewer.delete', 'Удалить') }}
          </button>
          <button type="button" role="menuitem" class="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-bg2"
                  @click="download">
            <GbIcon name="download" class="size-4" />{{ loc.t('imageViewer.download', 'Скачать') }}
          </button>
          <button type="button" role="menuitem" class="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-bg2"
                  @click="menuOpen = false; sharing = true">
            <GbIcon name="forward" class="size-4" />{{ loc.t('imageViewer.share', 'Поделиться') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Картинка. Своя прокрутка и `overscroll-contain`: колесо и жест не уходят в
         страницу под окном. -->
    <div class="flex min-h-0 flex-1 items-center justify-center overflow-auto overscroll-contain p-4"
         @click.self="emit('close')">
      <div class="relative">
        <img v-if="still && !stillFailed" :src="still" alt="" aria-hidden="true"
             class="absolute inset-0 size-full rounded-lg object-contain" @error="stillFailed = true" />
        <img v-if="!failed" :src="shown" :alt="title"
             class="relative max-h-[80dvh] max-w-[min(92vw,900px)] rounded-lg object-contain"
             @error="failed = true" />
        <img v-else-if="still && !stillFailed" :src="still" :alt="title"
             class="relative max-h-[80dvh] max-w-[min(92vw,900px)] rounded-lg object-contain" />
        <p v-else class="text-sm text-white/70">{{ loc.t('imageViewer.loadFailed', 'Картинка не загрузилась') }}</p>
      </div>
    </div>

    <ForwardPicker v-if="sharing" :title="loc.t('imageViewer.share', 'Поделиться')"
                   @submit="share" @close="sharing = false" />
  </div>
</template>
