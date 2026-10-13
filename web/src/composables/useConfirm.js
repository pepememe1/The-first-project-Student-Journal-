// useConfirm — промис-модалки вместо блокирующих confirm()/prompt().
// Синглтон: состояние в модуле, отрисовывает один <ConfirmDialog/> в App.vue.
// Использование:
//   const { confirm, prompt } = useConfirm()
//   if (await confirm({ message: '...', danger: true })) { ... }      // → boolean
//   const v = await prompt({ message: '...', defaultValue: '...' })   // → string | null
import { reactive } from 'vue'
import { useLocaleStore } from '../stores/locale.js'

export const dialogState = reactive({
  open: false,
  mode: 'confirm', // 'confirm' | 'prompt'
  title: '',
  message: '',
  okText: 'OK',
  cancelText: 'Отмена',
  danger: false,
  value: '',
  placeholder: '',
  //Подтверждение набором (13.10.2026): пока человек не набрал `requireText`, кнопка
  //согласия выключена. Для удалений, которые одним нажатием затрагивают многих
  //(группа со студентами): привычное «Да» на всплывающее окно тут не проходит.
  requireText: '',
  requireLabel: '',
  typed: '',
})

let resolver = null

function open(mode, opts) {
  const locale = useLocaleStore()
  return new Promise((resolve) => {
    resolver = resolve
    Object.assign(dialogState, {
      open: true,
      mode,
      title: opts.title || '',
      message: opts.message || '',
      okText: opts.okText || locale.t('common.ok', 'OK'),
      cancelText: opts.cancelText || locale.t('common.cancel'),
      danger: !!opts.danger,
      value: opts.defaultValue || '',
      placeholder: opts.placeholder || '',
      requireText: mode === 'confirm' ? String(opts.requireText || '') : '',
      requireLabel: opts.requireLabel || '',
      typed: '',
    })
  })
}

// settle: confirm → true/false; prompt → строка (OK) или null (отмена).
export function settleDialog(result) {
  dialogState.open = false
  const r = resolver
  resolver = null
  if (r) r(result)
}

export function useConfirm() {
  return {
    confirm: (opts) => open('confirm', opts || {}),
    prompt: (opts) => open('prompt', opts || {}),
  }
}
