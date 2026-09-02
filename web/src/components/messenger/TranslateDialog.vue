<script setup>
// TranslateDialog — настройки перевода переписки (четыре пары языков + автоперевод).
//
// Раскладка повторяет привычную по расширению-переводчику Discord: отдельно язык
// ВХОДЯЩИХ и отдельно ИСХОДЯЩИХ. Это не избыточность — случай ровно такой: китайский
// студент читает русские сообщения по-китайски, а пишет по-китайски и хочет, чтобы
// преподаватель получал русский. Одной парой языков это не описать.
//
// ⚠️ Про приватность в диалоге написано ПРЯМО, а не спрятано в мелкий шрифт. Но САМ
// ТЕКСТ был устаревшей неправдой до 02.09.2026: он обещал, что перевод делает ИИ-модель
// администратора и что «текст сообщения уходит ей». С 29.08.2026 это неверно —
// `deep-translator` удалён целиком, переводит офлайновый Argos на нашей же машине, LLM в
// переводе не участвует. Пугать человека утечкой, которой нет, так же плохо, как о
// настоящей умолчать: и то и другое лишает его возможности принять верное решение.
//
// ⚠️ И второе, найденное тогда же: диалог НЕ ЗНАЛ, установлен ли переводчик на сервере.
// Человек включал автоперевод, а сообщения уходили непереведёнными — настройка выглядела
// рабочей и не работала. Теперь состояние спрашивается у сервера (translate/status).
import { computed, onMounted } from 'vue'
import { X, Languages, ShieldCheck, ShieldAlert } from '@lucide/vue'
import { useTranslateStore } from '@/stores/translate'
import { useLocaleStore } from '@/stores/locale'
import ToggleRow from '@/components/ui/ToggleRow.vue'

defineEmits(['close'])
const tr = useTranslateStore()
const locale = useLocaleStore()
onMounted(() => tr.load())

// «Определить язык» уместно только для ИСТОЧНИКА: перевести «на автоопределённый»
// нельзя — непонятно, на какой именно.
const FIELDS = computed(() => [
  { key: 'incoming_from', label: locale.t('translate.incomingFrom', 'Язык, с которого переводить входящие'), auto: true },
  { key: 'incoming_to', label: locale.t('translate.incomingTo', 'Язык, на который переводить входящие'), auto: false },
  { key: 'outgoing_from', label: locale.t('translate.outgoingFrom', 'Язык, с которого переводить ваши сообщения'), auto: true },
  { key: 'outgoing_to', label: locale.t('translate.outgoingTo', 'Язык, на который переводить ваши сообщения'), auto: false },
])
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
       @click.self="$emit('close')">
    <div class="w-full max-w-lg rounded-2xl border border-border bg-card p-5 shadow-xl">
      <div class="mb-4 flex items-center justify-between gap-3">
        <h2 class="flex items-center gap-2 font-title text-lg font-extrabold text-text">
          <Languages class="size-5 text-accent" />{{ locale.t('translate.title', 'Перевод') }}
        </h2>
        <button type="button" class="text-text3 transition-colors hover:text-text"
                :aria-label="locale.t('common.close')" @click="$emit('close')">
          <X class="size-5" />
        </button>
      </div>

      <div class="flex max-h-[60vh] flex-col gap-4 overflow-y-auto">
        <label v-for="f in FIELDS" :key="f.key" class="block">
          <span class="mb-1.5 block text-sm font-medium text-text2">{{ f.label }}</span>
          <select :value="tr.prefs[f.key]"
                  class="h-11 w-full rounded-md border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent"
                  @change="tr.save({ [f.key]: $event.target.value })">
            <option v-if="f.auto" value="auto">{{ locale.t('translate.detect', 'Определить язык') }}</option>
            <option v-for="l in tr.languages" :key="l.code" :value="l.code">{{ l.name }}</option>
          </select>
        </label>

        <!-- ⚠️ Плашка стоит ВЫШЕ настроек, а не под ними: человек должен узнать, что
             перевода нет, ДО того как выберет языки и щёлкнет тумблер. Внизу её прочли
             бы уже после. -->
        <div v-if="!tr.status.available"
             class="flex items-start gap-2.5 rounded-lg border border-yellow-500/40 bg-yellow-500/5 p-3 text-xs text-text2">
          <ShieldAlert class="mt-0.5 size-4 shrink-0 text-yellow-500" />
          <p>{{ tr.status.reason || locale.t('translate.unavailable', 'Перевод на этом сервере сейчас недоступен.') }}</p>
        </div>

        <!-- Тумблер выключен, когда переводить нечем. Оставить его рабочим значило бы
             дать человеку включить настройку, которая заведомо ничего не сделает, — и он
             отправит сообщение в уверенности, что собеседник получит его на своём языке. -->
        <ToggleRow :label="locale.t('translate.auto', 'Автоперевод')"
                   :hint="locale.t('translate.autoHint', 'Переводить ваши сообщения перед отправкой. Текст в поле ввода заменится на перевод — вы увидите его до того, как нажмёте «отправить».')"
                   :model-value="tr.prefs.auto"
                   :disabled="!tr.status.available"
                   @update:model-value="(v) => tr.save({ auto: v })" />

        <div class="flex items-start gap-2.5 rounded-lg border border-border bg-card2 p-3 text-xs text-text3">
          <ShieldCheck class="mt-0.5 size-4 shrink-0 text-accent" />
          <p>
            {{ locale.t('translate.privacyNote', 'Перевод выполняется на сервере колледжа, офлайн: текст сообщения не уходит ни в какие сторонние сервисы. Ничего не переводится само — входящие только по кнопке, исходящие пока включён автоперевод. Качество машинного перевода ограничено, учебные термины он передаёт неточно.') }}
          </p>
        </div>

        <p v-if="tr.error" class="text-sm text-red">{{ tr.error }}</p>
      </div>
    </div>
  </div>
</template>
