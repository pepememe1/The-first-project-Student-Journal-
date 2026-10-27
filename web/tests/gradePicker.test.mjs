// gradePicker.test.mjs — выбор оценки пальцем своим листом, а не системным списком (23.10.2026).
//
// Android открывал `<select>` ячейки белым системным списком без подсказок (Ярослав: «тупой,
// некрасивый белый, нам нужно своё меню»). Держится:
//   • на телефоне ячейка — кнопка, открывающая лист; на ПК остаётся `<select>` с вводом с
//     клавиатуры (признак один — `keyboardInput`, utils/device.js);
//   • варианты листа — тот же `cellOptions`, запись — тот же `onCell`: второго пути
//     записи оценки и второго списка допустимого нет (§4.14);
//   • лист — `v-dialog`: Esc, фокус и системная «назад» его закрывают (§4.28, §4.49);
//   • «убрать» — только где есть что убирать; сотенная шкала — полем, а не 101 кнопкой.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `v-else-if="false"` вместо `touchPicker` — краснеет первый тест;
// `onCell` в `onPick` заменить прямой записью — краснеет второй.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const journal = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
const picker = readFileSync(new URL('../src/components/teacher/GradePicker.vue', import.meta.url), 'utf8')

test('на телефоне ячейка открывает свой лист, на ПК остаётся список', () => {
  assert.match(journal, /const touchPicker = !keyboardInput/)
  const button = journal.indexOf('<button v-else-if="touchPicker"')
  const select = journal.indexOf('<select v-else :value="rawValue(s.grades[col.key])"')
  assert.ok(button > 0 && select > button, 'ячейка на телефоне снова системный <select>')
  assert.match(journal.slice(button, select), /@click="openPicker\(s, col\)"/)
})

test('варианты и запись — те же, что у списка', () => {
  assert.match(journal, /<GradePicker v-if="picker" :options="cellOptions\(picker\.col\.l\)"/)
  const onPick = journal.slice(journal.indexOf('function onPick('), journal.indexOf('function onPick(') + 200)
  assert.match(onPick, /onCell\(s, col, value\)/, 'лист пишет оценку мимо onCell — второй путь записи')
})

test('лист закрывается «назад», «убрать» — только когда есть что убирать', () => {
  assert.match(picker, /<div v-dialog class="fixed inset-0/)
  assert.match(picker, /const canClear = computed\(\(\) => props\.options\.includes\(''\) && !!props\.current\)/)
  assert.match(picker, /<button v-if="canClear"/)
  assert.match(picker, /const typed = computed\(\(\) => scores\.value\.length > 12\)/)
  for (const key of ['legendPresent', 'legendN', 'legendB', 'legendO']) {
    assert.ok(picker.includes(`'teacherJournal.${key}'`), `у отметки нет подписи смысла: ${key}`)
  }
})
