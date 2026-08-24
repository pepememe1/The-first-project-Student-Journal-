// Ночная смена FNAF — правила игры, каждое из которых ломается молча.
//
// Пасхалка единственная в своём роде: она живёт ПОВЕРХ всего сайта и требует от
// человека ходить по вкладкам. Всё остальное в системе пасхалок устроено ровно
// наоборот — уход со страницы означает «находка потеряна». Поэтому здесь легко
// сломать что-нибудь правкой, которая для любой другой сцены была бы верной.
//
// Проверяем ПРАВИЛА, а не отрисовку: у сцены нет ни одного видимого признака, по
// которому поломку заметили бы тесты вёрстки, а поймать её вручную можно только ночью
// и с шансом 1/87.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (f) => readFileSync(join(ROOT, f), 'utf8')

// ⚠️ Комментарии срезаем: на этом проекте сторожа уже трижды находили искомую строку
// в объяснении рядом, а не в коде.
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/<!--[\s\S]*?-->/g, '')

const store = code(read('src/stores/easterEggs.js'))
const scene = code(read('src/components/easter/FnafOffice.vue'))
const vector = code(read('src/stores/vector.js'))
const page = code(read('src/pages/VectorPage.vue'))
const dock = code(read('src/components/VectorDock.vue'))

test('пока ноутбук открыт, уход со страницы не переспрашивают', () => {
  // 🔥 Влад поймал живьём: открыл ноутбук, пошёл к Вектору, получил «точно уйти?»,
  // подтвердил — и пасхалка закрылась. Продукт запрещал единственное действие,
  // которого игра от человека ждёт.
  const pendingBody = store.split('const pending = computed(')[1].split('})')[0]
  assert.match(pendingBody, /fnaf_night_mode/,
    'исключение для ночной смены исчезло — переход снова закроет пасхалку')
  assert.match(pendingBody, /fnaf\.value\.roaming/,
    'исключение не смотрит на то, открыт ли ноутбук')
})

test('пропажа Вектора — ОДНА величина на оба места показа', () => {
  // Держи её в компоненте — и заметивший пропажу в шторке увидел бы на вкладке живого
  // Вектора. Игра развалилась бы ровно там, где в неё поверили.
  assert.match(store, /const fnaf = ref\(/, 'состояния ночной смены нет в сторе')
  for (const [name, src] of [['вкладка «ИИ Помощник»', page], ['боковая шторка', dock]]) {
    assert.match(src, /v-if="!easter\.fnaf\.hidden"/,
      `${name}: маскот не прячется — пропажу там не увидят`)
  }
})

test('вернуть Вектора можно вопросом, и хук ровно один', () => {
  // ⚠️ Спросить можно из ДВУХ мест. Хук обязан жить в общем `send()`, иначе одно из
  // двух однажды забудут — это наш самый частый класс дефекта.
  const sendBody = vector.split('async function send(')[1].split('\n  }')[0]
  assert.match(sendBody, /fnafLure\(\)/, 'вопрос больше не возвращает Вектора')
  for (const [name, src] of [['VectorPage', page], ['VectorDock', dock]]) {
    assert.ok(!/fnafLure/.test(src),
      `${name}: завёлся ВТОРОЙ хук возврата — одно из мест разъедется с другим`)
  }
})

test('приманить можно ровно три раза, четвёртый — гарантированный скример', () => {
  // ⚠️ Ограничитель по существу, а не для строгости: без него достаточно держать
  // вкладку Вектора открытой и отвечать на каждую пропажу, чтобы ачивку не получить
  // НИКОГДА — а выдаёт её именно скример.
  assert.match(store, /const FNAF_LURES = 3/, 'предел возвратов изменился или пропал')
  const lure = store.split('function fnafLure(')[1].split('\n  }')[0]
  assert.match(lure, /lures >= FNAF_LURES/, 'предел не проверяется — Вектора можно звать вечно')
  assert.match(lure, /doomed: true/, 'исчерпав возвраты, игра не переходит к скримеру')
  assert.match(lure, /lures: fnaf\.value\.lures \+ 1/, 'счётчик возвратов не растёт')
  assert.match(scene, /easter\.fnaf\.doomed/, 'сцена не реагирует на «приманить нельзя»')
})

test('хитбокс ноутбука без видимой рамки', () => {
  // Пунктирная обводка поверх фотографии офиса читалась как элемент интерфейса и
  // ломала погружение — единственное, ради чего сцена и сделана.
  const hit = scene.split('@click="openJournal"')[1].split('</button>')[0]
  assert.ok(!/border-dashed/.test(hit), 'вернулась пунктирная рамка хитбокса')
  assert.ok(!/border-color:/.test(hit), 'у хитбокса снова задан цвет рамки')
  // Но клавиатурой он обязан оставаться находимым: невидимое ≠ недоступное.
  assert.match(hit, /focus-visible:outline/, 'хитбокс не показывает фокус с клавиатуры')
})

test('ночь заканчивается вместе с сессией', () => {
  // На общем компьютере колледжа следующий человек не должен обнаружить, что у него
  // пропал Вектор (правило «выход — это смена владельца»).
  const resetBody = store.split('function reset(')[1].split('\n  }')[0]
  assert.match(resetBody, /fnafEnd\(\)/, 'выход из аккаунта не гасит ночную смену')
})
