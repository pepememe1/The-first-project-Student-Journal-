<script setup>
// ReportProblemButton — глобальная кнопка «Сообщить о проблеме» → чат модерации.
//
// Идея из разбора рынка (ClassDojo, docs/MARKET-ANALOGUES-2026.md §9 №3): встроенный
// канал обратной связи прямо в продукте. Инфраструктура уже была — личный чат с
// модерацией (kind='moderation', эндпоинт /web/messenger/moderation) и кнопка ⚙ ВНУТРИ
// переписки. Не хватало ОДНОГО: заметной точки входа, чтобы человек мог пожаловаться на
// проблему из любого места, не зная про мессенджер. Здесь — быстрая форма: написал →
// ушло в твой чат с модерацией → при желании открыл переписку.
//
// ⚠️ Админу кнопка НЕ показывается: администратор и есть модерация, писать ему некуда —
// сервер на /moderation ответит 403 (см. messenger.py::moderation_chat). Прячем на
// клиенте, чтобы не предлагать заведомо неработающее действие.
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { MessageSquareWarning, X, Check, Loader2 } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { messengerApi } from '@/api/endpoints'

const auth = useAuthStore()
const messenger = useMessengerStore()
const loc = useLocaleStore()
const router = useRouter()
const t = (k, f) => loc.t(k, f)

const open = ref(false)
const text = ref('')
const busy = ref(false)
const sent = ref(false)
const error = ref('')

function show() {
  open.value = true; text.value = ''; sent.value = false; error.value = ''
}
function close() { open.value = false }

async function submit() {
  const body = text.value.trim()
  if (!body || busy.value) return
  busy.value = true; error.value = ''
  try {
    // 1) гарантируем, что чат с модерацией существует (создаётся при первом обращении);
    // 2) отправляем в него текст. Оба шага — существующие эндпоинты, без нового пути записи.
    const { data } = await messengerApi.moderation()
    await messengerApi.send(data.conversation_id, body)
    sent.value = true
  } catch (e) {
    error.value = e?.response?.data?.detail || t('report.error', 'Не удалось отправить. Попробуйте позже.')
  } finally {
    busy.value = false
  }
}

// «Открыть переписку» — переходим в мессенджер и открываем чат модерации (best-effort:
// сообщение уже доставлено, это лишь удобство «посмотреть/продолжить»).
async function openChat() {
  close()
  await router.push(`/${auth.role}/messages`)
  try { await messenger.openModeration() } catch { /* страница сама покажет чат из стора */ }
}
</script>

<template>
  <div v-if="auth.role !== 'admin'">
    <!-- Кнопка в стиле пункта сайдбара (неакцентная, спокойная — это не частое действие). -->
    <button type="button" @click="show()"
            class="flex w-full items-center gap-2.5 rounded-sm px-3.5 py-2 text-sm font-medium text-text3 transition-colors hover:bg-accent-glow hover:text-accent">
      <MessageSquareWarning class="size-[18px] shrink-0" />
      <span class="min-w-0 flex-1 truncate">{{ t('report.button', 'Сообщить о проблеме') }}</span>
    </button>

    <!-- Модалка -->
    <transition name="fade">
      <div v-if="open" class="fixed inset-0 z-[70] grid place-items-center p-4"
           style="background: var(--gb-overlay)" @click.self="close()">
        <div class="w-full max-w-md rounded-xl border border-border2 bg-card p-4 shadow-card">
          <div class="mb-2 flex items-center gap-2">
            <MessageSquareWarning class="size-5 shrink-0 text-accent" />
            <p class="min-w-0 flex-1 truncate font-title text-base font-bold text-text">
              {{ t('report.problemTitle', 'Сообщить о проблеме') }}
            </p>
            <button type="button" @click="close()" :aria-label="t('common.close', 'Закрыть')"
                    class="grid size-7 shrink-0 place-items-center rounded text-text3 hover:bg-bg2 hover:text-text">
              <X class="size-4" />
            </button>
          </div>

          <!-- Успех -->
          <div v-if="sent" class="py-2">
            <div class="mb-3 flex items-center gap-2 text-sm text-accent">
              <Check class="size-5 shrink-0" />
              <span>{{ t('report.sent', 'Отправлено модерации. Вам ответят в чате.') }}</span>
            </div>
            <div class="flex gap-2">
              <button type="button" @click="openChat()"
                      class="flex-1 rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent2">
                {{ t('report.open', 'Открыть переписку') }}
              </button>
              <button type="button" @click="close()"
                      class="rounded-md border border-border2 px-3 py-2 text-sm text-text2 hover:border-accent">
                {{ t('common.close', 'Закрыть') }}
              </button>
            </div>
          </div>

          <!-- Форма -->
          <div v-else>
            <p class="mb-2 text-xs text-text3">
              {{ t('report.hint', 'Опишите проблему: что не работает, где, что вы делали. Сообщение уйдёт команде поддержки в личный чат с модерацией.') }}
            </p>
            <textarea v-model="text" rows="5" maxlength="2000"
                      :placeholder="t('report.placeholder', 'Например: не открывается расписание на телефоне…')"
                      class="w-full resize-none rounded-md border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent"
                      @keydown.ctrl.enter="submit()" />
            <p v-if="error" class="mt-1 text-xs text-red">{{ error }}</p>
            <div class="mt-3 flex justify-end gap-2">
              <button type="button" @click="close()"
                      class="rounded-md border border-border2 px-3 py-2 text-sm text-text2 hover:border-accent">
                {{ t('common.cancel', 'Отмена') }}
              </button>
              <button type="button" @click="submit()" :disabled="!text.trim() || busy"
                      class="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
                <Loader2 v-if="busy" class="size-4 animate-spin" />
                {{ t('report.send', 'Отправить') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }
</style>
