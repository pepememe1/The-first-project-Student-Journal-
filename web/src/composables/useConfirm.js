// useConfirm — промис-модалки вместо блокирующих confirm()/prompt().
// Синглтон: состояние в модуле, отрисовывает один <ConfirmDialog/> в App.vue.
// Использование:
//   const { confirm, prompt } = useConfirm()
//   if (await confirm({ message: '...', danger: true })) { ... }      // → boolean
//   const v = await prompt({ message: '...', defaultValue: '...' })   // → string | null
import { reactive } from 'vue'

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
})

let resolver = null

function open(mode, opts) {
  return new Promise((resolve) => {
    resolver = resolve
    Object.assign(dialogState, {
      open: true,
      mode,
      title: opts.title || '',
      message: opts.message || '',
      okText: opts.okText || 'OK',
      cancelText: opts.cancelText || 'Отмена',
      danger: !!opts.danger,
      value: opts.defaultValue || '',
      placeholder: opts.placeholder || '',
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
