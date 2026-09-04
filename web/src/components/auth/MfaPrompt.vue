<script setup>
/**
 * MfaPrompt.vue — второй шаг входа: код из приложения-аутентификатора.
 *
 * ⚠️ Отдельный экран, а не поле рядом с паролем. Причина не в красоте: код живёт
 * тридцать секунд, и человек должен видеть его ввод как самостоятельное действие,
 * а не как ещё одну строку формы, которую он заполнит заранее и не успеет отправить.
 *
 * ⚠️ Здесь НЕТ ни логина, ни пароля — они уже проверены. Пропуском служит короткий
 * challenge, который лежит в сторе и живёт пять минут.
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits(['done', 'cancel'])
const auth = useAuthStore()

const code = ref('')
const field = ref(null)
//Код восстановления длиннее и с буквами — переключатель меняет только подсказку и
//маску ввода, ручка на сервере ОДНА и та же (она сама различает по формату).
const useRecovery = ref(false)

onMounted(async () => {
  await nextTick()
  field.value?.focus()
})

/*
 * ━━ ОБРАТНЫЙ ОТСЧЁТ ━━
 * 🔥 Заведён по жалобе Ярослава (03.09.2026), воспроизведённой на бою. Окно
 * подтверждения живёт ограниченное время; пока человек ищет нужную запись в
 * аутентификаторе (а их там десяток, и наша называется как чужая), срок выходит.
 * Сервер отвечает 401, окно кода ПРОПАДАЕТ, и на экране снова форма входа —
 * со стороны это читается как «журнал меня выкинул», а не «время вышло».
 *
 * ⚠️ Отсчёт не «украшение прогресса»: он превращает необъяснимое исчезновение в
 * ожидаемое событие. Ту же роль играет счётчик блокировки на форме входа — без
 * него «подождите» ничего не сообщает.
 */
const left = ref(0)
let timer = 0
function tick() {
  const ms = (auth.mfaExpiresAt || 0) - Date.now()
  left.value = Math.max(0, Math.ceil(ms / 1000))
}
onMounted(() => { tick(); timer = setInterval(tick, 1000) })
onBeforeUnmount(() => clearInterval(timer))
const leftLabel = computed(() => {
  const s = left.value
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})
//Последняя минута — предупреждаем цветом: до неё отсчёт не должен нервировать.
const running_out = computed(() => left.value > 0 && left.value <= 60)

async function submit() {
  try {
    const user = await auth.verifyMfa(code.value)
    emit('done', user)
  } catch {
    //Текст ошибки уже в auth.error. Поле очищаем: следующий код будет ДРУГИМ,
    //и оставлять неверный на экране значит провоцировать повторную отправку того же.
    code.value = ''
    await nextTick()
    field.value?.focus()
  }
}

function onInput(e) {
  if (useRecovery.value) return
  //Только цифры: аутентификаторы показывают код группами, и люди вставляют его
  //с пробелом. Молча чистим, вместо того чтобы ругаться на «неверный формат».
  code.value = String(e.target.value || '').replace(/\D/g, '').slice(0, 6)
}
</script>

<template>
  <form class="gb-mfa" @submit.prevent="submit">
    <h2 class="gb-mfa__title">Подтверждение входа</h2>
    <p class="gb-mfa__hint">
      <template v-if="!useRecovery">
        Откройте приложение-аутентификатор и введите шестизначный код для GradeBookAI.
      </template>
      <template v-else>
        Введите один из кодов восстановления, выданных при настройке.
        Каждый код срабатывает только один раз.
      </template>
    </p>

    <input
      ref="field"
      :value="code"
      class="gb-mfa__input"
      :class="{ 'gb-mfa__input--recovery': useRecovery }"
      :inputmode="useRecovery ? 'text' : 'numeric'"
      :autocomplete="useRecovery ? 'off' : 'one-time-code'"
      :placeholder="useRecovery ? 'xxxxx-xxxxx' : '000000'"
      :maxlength="useRecovery ? 11 : 6"
      spellcheck="false"
      @input="useRecovery ? (code = $event.target.value) : onInput($event)"
    />

    <p v-if="auth.error" class="gb-mfa__error">{{ auth.error }}</p>

    <!-- Сколько осталось. Показываем ТОЛЬКО когда срок известен: у старого сервера,
         который ещё не присылает `expires_in`, отсчёта не будет — и это лучше, чем
         придуманное число, по которому человек построит неверные ожидания. -->
    <p v-if="left > 0" class="gb-mfa__timer" :class="{ 'gb-mfa__timer--warn': running_out }">
      Код можно ввести ещё <b>{{ leftLabel }}</b>. Потом придётся войти паролем заново.
    </p>

    <button
      type="submit"
      class="gb-mfa__submit"
      :disabled="auth.loading || (!useRecovery && code.length < 6) || !code"
    >
      {{ auth.loading ? 'Проверяем…' : 'Войти' }}
    </button>

    <div class="gb-mfa__links">
      <button type="button" class="gb-mfa__link" @click="useRecovery = !useRecovery; code = ''">
        {{ useRecovery ? 'Ввести код из приложения' : 'Потерян телефон — код восстановления' }}
      </button>
      <button type="button" class="gb-mfa__link" @click="auth.cancelMfa(); emit('cancel')">
        Отмена
      </button>
    </div>
  </form>
</template>

<style scoped>
/* Цвета — только токены темы (--gb-*), как везде: хардкод разъедется с палитрой. */
.gb-mfa { display: flex; flex-direction: column; gap: 14px; }
.gb-mfa__title { font-size: 20px; font-weight: 600; color: var(--gb-text); margin: 0; }
.gb-mfa__hint { font-size: 14px; line-height: 1.5; color: var(--gb-text-muted); margin: 0; }
.gb-mfa__input {
  width: 100%;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--gb-border);
  background: var(--gb-surface);
  color: var(--gb-text);
  /* Крупно и вразрядку: шесть цифр набирают глядя в телефон, а не в экран. */
  font-size: 26px;
  letter-spacing: 8px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.gb-mfa__input--recovery { font-size: 18px; letter-spacing: 2px; }
.gb-mfa__input:focus { outline: none; border-color: var(--gb-accent); }
.gb-mfa__error { color: var(--gb-danger, #e5484d); font-size: 14px; margin: 0; }
.gb-mfa__timer { color: var(--gb-text-muted); font-size: 13px; margin: 0; }
.gb-mfa__timer--warn { color: var(--gb-danger, #e5484d); }
.gb-mfa__submit {
  padding: 12px 16px;
  border-radius: 12px;
  border: none;
  background: var(--gb-accent);
  color: var(--gb-on-accent, #fff);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}
.gb-mfa__submit:disabled { opacity: 0.5; cursor: default; }
.gb-mfa__links { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.gb-mfa__link {
  background: none; border: none; padding: 0;
  color: var(--gb-text-muted); font-size: 13px; cursor: pointer; text-decoration: underline;
}
.gb-mfa__link:hover { color: var(--gb-text); }
</style>
