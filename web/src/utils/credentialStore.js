// credentialStore.js — предложить браузеру/менеджеру паролей сохранить вход.
//
// Для SPA/AJAX-входа одних autocomplete-атрибутов мало — надёжно срабатывает Credential
// Management API (navigator.credentials.store). Побочный бонус: когда пароль сохранён в
// системном менеджере, iOS предлагает автозаполнение по Face ID, Android — по отпечатку.
// Где API нет (Safari/Firefox) — молча полагаемся на autocomplete-эвристику браузера.
//
// ⚠️ Одна функция на три места (вход, восстановление кодом, первичная настройка):
// раньше она жила внутри страницы входа, и новый пароль после смены браузер не
// предлагал сохранить вовсе — человек оставался с прежним, уже недействующим.
export async function saveCredential(id, pass) {
  try {
    if (id && pass && window.PasswordCredential) {
      const cred = new window.PasswordCredential({ id, password: pass, name: id })
      await navigator.credentials.store(cred)
    }
  } catch { /* сохранение необязательно — не мешаем входу */ }
}
