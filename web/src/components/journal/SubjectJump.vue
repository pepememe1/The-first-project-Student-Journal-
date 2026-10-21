<script setup>
/**
 * SubjectJump — оглавление журнала: предмет, его средний балл и переход к карточке.
 *
 * 🔥 ЗАЧЕМ (UX-аудит 17.10.2026). «Журналы студента и родителя требуют много прокрутки
 * на телефоне: пять раскрытых блоков — около 4800 px при ширине 390 px, быстрой сводки
 * и перехода к нужному предмету нет.» Оглавление закрывает обе половины жалобы сразу:
 * сверху видно ВСЕ предметы с их средними (это и есть сводка), а нажатие уводит к
 * нужной карточке без пролистывания чужих.
 *
 * ⚠️ СРЕДНИЙ НЕ СЧИТАЕТСЯ ЗДЕСЬ — он берётся из того же ответа сервера, что и карточка
 * (`s.average`). Второй методики среднего в продукте быть не должно (§4.8): посчитай мы
 * его сами, оглавление и карточка показывали бы РАЗНЫЕ числа на одном экране, и человек
 * не смог бы понять, какому верить.
 *
 * ⚠️ КАРТОЧКИ НЕ СВОРАЧИВАЕМ. Соблазн велик — свернув всё, мы бы убрали прокрутку
 * совсем, — но пасхалки журнала ищут клетки оценок в РАЗМЕТКЕ
 * (`JournalEggs`: `document.querySelectorAll('[data-egg-grade]')`), и свёрнутый по
 * умолчанию журнал означал бы, что ни одна из них не находит ни одной клетки. Это наш
 * обычный размен: починка одного экрана ломает соседний механизм молча.
 *
 * ⚠️ Один предмет — оглавления нет: список из одной строки над единственной карточкой
 * не помогает, а занимает экран (тот же довод, что у липкой полосы прокрутки, которая
 * показывается только при реальном переполнении).
 */
import { useLocaleStore } from '@/stores/locale'
import { subjectAnchorId } from '@/utils/journalAnchors'

const props = defineProps({
  //[{ subject, average }] — ровно то, что пришло с сервера, без пересчёта.
  subjects: { type: Array, default: () => [] },
})

const locale = useLocaleStore()

/**
 * Плавность — только если человек её не запретил.
 *
 * ⚠️ `prefers-reduced-motion` у нас уважают анимации ленты чата и появления сообщений;
 * прокрутка через весь журнал — движение покрупнее любого из них.
 */
function scrollBehavior() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  } catch {
    return 'auto'
  }
}

function jump(subject) {
  const el = document.getElementById(subjectAnchorId(subject))
  if (!el) return          //карточки нет — молча ничего не делаем, падать здесь не на чем
  el.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
}
</script>

<template>
  <!-- Лента чипов: на узком экране прокручивается вбок, на широком переносится. -->
  <nav v-if="props.subjects.length > 1"
       class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 sm:flex-wrap sm:overflow-visible"
       :aria-label="locale.t('journalJump.title', 'Перейти к предмету')">
    <button v-for="s in props.subjects" :key="s.subject" type="button"
            class="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full border border-border2 bg-card2 px-3 text-sm text-text2 transition-colors hover:border-accent hover:text-accent"
            @click="jump(s.subject)">
      <!-- `min-w-0` рядом с `truncate` обязателен: у flex-ребёнка минимальный размер
           считается по содержимому, и длинное название не сожмётся, а РАСПИРАЕТ ленту.
           Это уже записанная ловушка, её держит сторож `mobileLayout.test.mjs`. -->
      <span class="min-w-0 max-w-[12rem] truncate">{{ s.subject }}</span>
      <!-- Средний рядом с названием: это и есть обещанная «быстрая сводка». Прочерк —
           когда оценок нет; «0» здесь читался бы как двойка. -->
      <span class="shrink-0 rounded-full bg-bg2 px-2 py-0.5 text-xs font-semibold text-text3">
        {{ s.average || '—' }}
      </span>
    </button>
  </nav>
</template>
