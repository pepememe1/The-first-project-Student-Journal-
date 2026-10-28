// pageReveal.test.mjs — страница с несколькими ответами появляется одним кадром (28.10.2026).
//
// Замер на стенде: страницы рисовали ответы по мере прихода (журнал родителя сдвигался на
// 0.22, главная студента — на 0.03), а плашки «Нет нагрузки» и «Ребёнок не привязан»
// мелькали у каждого, пока шёл первый ответ.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ref, nextTick } from 'vue'
import { useDelayedFlag } from '../src/composables/useDelayedFlag.js'
import { readSource } from './_readSource.mjs'

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

test('скелет не появляется, если ответ пришёл быстрее порога, и гаснет сразу', async () => {
  const loading = ref(true)
  const flag = useDelayedFlag(loading, 30)
  assert.equal(flag.value, false, 'сразу — пусто, а не мелькающая заглушка')
  await wait(10)
  loading.value = false
  await nextTick()
  await wait(40)
  assert.equal(flag.value, false, 'быстрый ответ: скелета не было вовсе')

  loading.value = true
  await nextTick()
  await wait(45)
  assert.equal(flag.value, true, 'долгий ответ: скелет показан')
  loading.value = false
  await nextTick()
  assert.equal(flag.value, false, 'данные пришли — скелет гаснет сразу')
})

test('ответы страницы — одним пакетом, а не цепочкой', () => {
  for (const page of ['pages/student/StudentDashboard.vue', 'pages/parent/ParentJournal.vue', 'pages/teacher/TeacherStats.vue']) {
    assert.match(readSource(page), /await Promise\.allSettled\(\[/, `${page}: ответы снова идут друг за другом`)
  }
})

test('пустые плашки ждут первого ответа, а не мелькают', () => {
  assert.match(readSource('pages/parent/ParentJournal.vue'), /<EmptyState v-else-if="childrenReady && !children\.length"/)
  assert.match(readSource('pages/teacher/TeacherStats.vue'), /<EmptyState v-if="workloadReady && \(!groups\.length/)
  assert.match(readSource('pages/teacher/TeacherJournal.vue'), /<div v-if="journalPending"[\s\S]{0,400}<EmptyState v-else-if="!groups\.length \|\| !subjects\.length"/)
})

test('PageReveal: контент одним кадром, скелет — по задержке', () => {
  const src = readSource('components/ui/PageReveal.vue')
  assert.match(src, /useDelayedFlag\(/)
  assert.match(src, /<slot v-if="showSkeleton" name="skeleton" \/>/)
  assert.match(src, /class="gb-reveal"/)
})
