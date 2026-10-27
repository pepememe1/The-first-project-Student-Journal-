// editorShell.test.mjs — редакторы в одном каркасе (27.10.2026, требование Влада «обновить
// дизайн для редакторов»: расписание, викторины, админские, профиль и беседа).
//
// Было: у каждого редактора своя раскладка — «Сохранить» уезжал за низ длинной формы,
// крестика не было, на телефоне окно висело посередине. Каркас один (`EditorShell.vue`),
// и сторож держит, что редакторы в нём, а не снова в своей копии разметки.
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть редактору студента прежнюю подложку — краснеет
// перечень; убрать закреплённый низ из каркаса — краснеет проверка раскладки.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const SHELL = readSource('components/ui/EditorShell.vue')

//Редактор → сколько окон в нём обязано идти через каркас.
const EDITORS = {
  'pages/admin/AdminStudents.vue': 1,
  'pages/admin/AdminTeachers.vue': 1,
  'pages/admin/AdminGroups.vue': 4,
  'pages/admin/AdminParents.vue': 3,
  'pages/admin/AdminSubjects.vue': 1,
  'pages/admin/AdminSchedule.vue': 1,
  'components/activity/quiz/QuizEditor.vue': 1,
  'components/AvatarCropper.vue': 1,
}

test('каркас: шапка с крестиком, своя прокрутка тела, закреплённый низ, лист на телефоне', () => {
  assert.match(SHELL, /<div v-dialog v-bind="\$attrs"/, 'окно — под директивой окон (Esc, фокус, «назад»)')
  assert.match(SHELL, /:aria-label="loc\.t\('common\.close', 'Закрыть'\)" @click="emit\('close'\)"/)
  assert.match(SHELL, /class="gb-editor-body min-h-0 flex-1 overflow-y-auto overscroll-contain/)
  assert.match(SHELL, /<footer v-if="\$slots\.footer"[\s\S]*?shrink-0/, 'низ с кнопками не прокручивается')
  assert.match(SHELL, /items-end justify-center[^"]*sm:items-center/, 'на телефоне — лист снизу')
  assert.match(SHELL, /rounded-t-2xl/)
})

test('редакторы идут через каркас, а не через свою копию разметки', () => {
  for (const [file, n] of Object.entries(EDITORS)) {
    const src = readSource(file)
    const shells = (src.match(/<EditorShell\b/g) || []).length
    assert.equal(shells, n, `${file}: окон в каркасе ${shells}, ожидалось ${n}`)
    assert.match(src, /import EditorShell from '@\/components\/ui\/EditorShell\.vue'/, file)
    assert.doesNotMatch(src, /rounded-lg border border-border bg-card p-5 shadow-card/,
      `${file}: осталась прежняя панель редактора`)
  }
})

test('редакторы внутри страниц — с тем же видом полей', () => {
  assert.match(readSource('pages/Profile.vue'), /class="gb-editor-body grid/)
  assert.match(readSource('components/messenger/ConversationInfo.vue'), /class="gb-editor-body mb-4/)
  const css = readSource('style.css')
  assert.match(css, /\.gb-editor-body :is\(input, select, textarea\):focus-visible \{[^}]*box-shadow/)
})

test('обратный ход: прежняя панель находится', () => {
  const before = '<div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">'
  assert.match(before, /rounded-lg border border-border bg-card p-5 shadow-card/)
})
