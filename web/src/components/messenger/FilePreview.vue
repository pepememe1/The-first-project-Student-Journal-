<script setup>
// FilePreview — предпросмотр документа: до отправки (свой файл) и после (из беседы).
//
// ⚠️ Ни один документ не уходит на сторону: PDF показывает сам браузер, DOCX
// распаковывается прямо во вкладке (см. utils/docPreview.js), текст читается как текст.
// Для журнала с ПДн это не мелочь — у нас уже есть один болезненный пункт с внешним
// обработчиком (перевод), второй заводить незачем.
//
// ⚠️ Это ПРЕДПРОСМОТР, а не вёрстка документа: таблицы, картинки и оформление теряются.
// Так и задумано — задача «убедиться, что это тот файл», а не «открыть вместо Word».
import { ref, watch, onBeforeUnmount, computed } from 'vue'
import { X, FileText, Download, Loader2 } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { previewKind, docxText, plainText, humanSize } from '@/utils/docPreview'
import { useLocaleStore } from '@/stores/locale'
import { embedMode } from '@/utils/videoEmbed'
import { isNativeApp } from '@/api/server'

const props = defineProps({
  // Либо локальный File (до отправки), либо вложение из беседы.
  file: { type: Object, default: null },
  attachment: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const name = computed(() => props.file?.name || props.attachment?.name || '')
const size = computed(() => props.file?.size ?? props.attachment?.size ?? 0)
const mime = computed(() => props.file?.type || props.attachment?.mime || '')
const kind = computed(() => previewKind(mime.value, name.value))

// ⚠️ ТОТ ЖЕ ГЕЙТ, ЧТО У ВИДЕО-ПЛЕЕРА, и имя переменной унаследовано от него намеренно.
// Правило общее и не про видео: встроенный фрейм годится только в браузере — в мобильном
// приложении страницу отдаёт локальный сервер Capacitor, и заголовки Caddy до неё не
// доходят (см. §CSP в CLAUDE.md). Заводить второй признак «мы в приложении» нельзя:
// такие копии расходятся молча и именно в сторону «дверь снова открыта».
// Нет фрейма — предлагаем открыть файл системным просмотрщиком, это на телефоне и
// удобнее.
const videoIframeAllowed = computed(() => embedMode(isNativeApp()) === 'iframe')

const loading = ref(false)
const error = ref('')
const paragraphs = ref([])
const text = ref('')
const pdfUrl = ref('')
let objectUrl = ''

function revoke() {
  if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = '' }
}
onBeforeUnmount(revoke)

/** Байты документа: из локального файла или из хранилища по подписанной ссылке. */
async function bytes() {
  if (props.file) return await props.file.arrayBuffer()
  const { data } = await messengerApi.attachmentUrl(props.attachment.id)
  const resp = await fetch(data.url)          //подпись уже в ссылке, заголовков не шлём
  if (!resp.ok) throw new Error(`хранилище: ${resp.status}`)
  return await resp.arrayBuffer()
}

async function build() {
  revoke()
  paragraphs.value = []; text.value = ''; pdfUrl.value = ''; error.value = ''
  if (!kind.value) return                      //нечего показывать — только скачать
  loading.value = true
  try {
    const buf = await bytes()
    if (kind.value === 'pdf') {
      objectUrl = URL.createObjectURL(new Blob([buf], { type: 'application/pdf' }))
      pdfUrl.value = objectUrl
    } else if (kind.value === 'docx') {
      paragraphs.value = await docxText(buf)
      if (!paragraphs.value.length) error.value = locale.t('preview.empty', 'В документе нет текста')
    } else {
      text.value = plainText(buf)
    }
  } catch (e) {
    // ⚠️ Показываем ПРИЧИНУ, а не «не удалось»: «браузер не умеет распаковывать» и
    // «хранилище не отдало файл» требуют от человека разных действий.
    error.value = e?.message || locale.t('preview.failed', 'Не удалось открыть')
  } finally { loading.value = false }
}
watch(() => [props.file, props.attachment], build, { immediate: true })

async function download() {
  if (props.file) {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(props.file); a.download = name.value; a.click()
    URL.revokeObjectURL(a.href)
    return
  }
  try {
    const { data } = await messengerApi.attachmentUrl(props.attachment.id)
    window.open(data.url, '_blank', 'noopener')
  } catch { error.value = locale.t('preview.failed', 'Не удалось открыть') }
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xl">

      <div class="flex items-center gap-3 border-b border-border px-4 py-3">
        <FileText :size="18" class="shrink-0 text-text3" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold">{{ name }}</p>
          <p class="text-[11px] text-text3">{{ humanSize(size) }}</p>
        </div>
        <button type="button" class="text-text3 hover:text-text" @click="download"
                :aria-label="locale.t('preview.download', 'Скачать')">
          <Download :size="17" />
        </button>
        <button type="button" class="text-text3 hover:text-text" @click="emit('close')"
                :aria-label="locale.t('common.close', 'Закрыть')">
          <X :size="18" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-auto bg-bg2">
        <p v-if="loading" class="flex items-center justify-center gap-2 py-16 text-sm text-text3">
          <Loader2 :size="15" class="animate-spin" />
          {{ locale.t('preview.loading', 'Открываем…') }}
        </p>

        <p v-else-if="error" class="px-4 py-16 text-center text-sm text-text3">{{ error }}</p>

        <!-- PDF рисует сам браузер: свой просмотрщик тут был бы сотней килобайт в бандле
             ради того, что уже встроено. -->
        <template v-else-if="kind === 'pdf'">
          <iframe v-if="videoIframeAllowed" :src="pdfUrl" class="h-[70vh] w-full border-0"
                  :title="name"></iframe>
          <div v-else class="px-4 py-16 text-center text-sm text-text3">
            {{ locale.t('preview.openOutside', 'В приложении PDF открывается системным просмотрщиком') }}
            <button type="button" @click="download"
                    class="mt-3 block w-full rounded-lg bg-accent py-2 text-sm font-semibold text-white">
              {{ locale.t('preview.download', 'Скачать') }}
            </button>
          </div>
        </template>

        <div v-else-if="kind === 'docx'" class="mx-auto max-w-2xl px-6 py-6">
          <p v-for="(p, i) in paragraphs" :key="i" class="mb-3 text-sm leading-relaxed text-text">{{ p }}</p>
        </div>

        <pre v-else-if="kind === 'text'"
             class="whitespace-pre-wrap px-6 py-6 font-mono text-xs leading-relaxed text-text">{{ text }}</pre>

        <!-- Тип, который мы не умеем показать. Честно говорим об этом, а не делаем вид,
             что файл пустой. -->
        <div v-else class="px-4 py-16 text-center text-sm text-text3">
          {{ locale.t('preview.noPreview', 'Предпросмотр для этого типа недоступен — файл можно скачать') }}
        </div>
      </div>
    </div>
  </div>
</template>
