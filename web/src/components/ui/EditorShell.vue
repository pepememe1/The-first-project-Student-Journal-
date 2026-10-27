<script setup>
/**
 * EditorShell.vue — общий каркас окон-редакторов (27.10.2026, требование Влада «обновить
 * дизайн для редакторов»: расписание, викторины, админские, профиль и беседа).
 *
 * Было: у каждого редактора своя раскладка — заголовок прокручивался вместе с полями,
 * кнопки «Сохранить» уезжали за низ длинной формы, крестика не было (закрыть — только
 * щелчком мимо или Esc), на телефоне окно висело посередине с полями шириной в палец.
 * Каждая копия разметки расходилась с соседней на первой правке.
 *
 * Теперь одна раскладка:
 *   • шапка — значок, заголовок, подпись и крестик; не прокручивается;
 *   • тело — своя прокрутка (`overscroll-contain`: жест не уходит на страницу);
 *   • низ — кнопки, закреплены: «Сохранить» видно всегда;
 *   • телефон — лист снизу во всю ширину, как системные листы Android и iOS.
 * Поля внутри тела получают единый вид классом `gb-editor-body` (style.css): скругление,
 * кольцо фокуса, подписи — без правки каждого поля по отдельности.
 *
 * ⚠️ Закрытие — только через `close`: решение (спросить «закрыть без сохранения?», не
 * закрывать во время сохранения) остаётся за редактором. Атрибуты корня (например
 * `data-dialog-guard="self"`) передаются на подложку — их читает директива окон.
 */
import { useLocaleStore } from '@/stores/locale'
import GbIcon from '@/components/ui/GbIcon.vue'

defineOptions({ inheritAttrs: false })
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  icon: { type: String, default: 'edit' },
  //sm/md — обычная форма, lg — форма с таблицей или списком, xl/2xl — большой редактор.
  size: { type: String, default: 'md' },
})
const emit = defineEmits(['close'])
const loc = useLocaleStore()
const WIDTH = { sm: 'sm:max-w-sm', md: 'sm:max-w-md', lg: 'sm:max-w-lg', xl: 'sm:max-w-2xl',
  '2xl': 'sm:max-w-4xl' }
</script>

<template>
  <div v-dialog v-bind="$attrs"
       class="fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
       @click.self="emit('close')">
    <div class="gb-editor flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border2 bg-card shadow-card sm:max-h-[calc(100dvh-2rem)] sm:rounded-2xl"
         :class="WIDTH[size] || WIDTH.md">
      <header class="flex shrink-0 items-start gap-3 border-b border-border px-5 py-4">
        <span class="grid size-9 shrink-0 place-items-center rounded-full bg-accent-glow text-accent">
          <GbIcon :name="icon" class="size-[18px]" />
        </span>
        <div class="min-w-0 flex-1">
          <h3 class="truncate font-title text-lg font-bold leading-tight text-text">{{ title }}</h3>
          <p v-if="subtitle" class="mt-0.5 text-xs text-text3">{{ subtitle }}</p>
          <slot name="header" />
        </div>
        <button type="button" class="-mr-1.5 grid size-9 shrink-0 place-items-center rounded-full text-text3 transition-colors hover:bg-bg2 hover:text-text"
                :aria-label="loc.t('common.close', 'Закрыть')" @click="emit('close')">
          <GbIcon name="close" class="size-5" />
        </button>
      </header>
      <div class="gb-editor-body min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
        <slot />
      </div>
      <footer v-if="$slots.footer"
              class="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-border bg-card2/60 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <slot name="footer" />
      </footer>
    </div>
  </div>
</template>
