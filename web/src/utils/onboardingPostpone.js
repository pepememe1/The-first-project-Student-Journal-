// onboardingPostpone.js — «Позже» в окне первичной настройки учётки.
//
// Отказ живёт в ПАМЯТИ вкладки, а не в localStorage: перезагрузка страницы или новый
// вход снова покажут просьбу. Просьба, которую можно закрыть одним нажатием и больше
// не увидеть, превращает пароль из листа группы в вечный.
// Ключ — логин: на общем компьютере колледжа «Позже» одного студента не должно гасить
// окно у следующего.
const postponedLogins = new Set()

export function postponed(login) {
  return postponedLogins.has(String(login || ''))
}

export function postpone(login) {
  if (login) postponedLogins.add(String(login))
}
