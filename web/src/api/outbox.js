/**
 * outbox.js — всё, что преподаватель сделал БЕЗ СЕТИ, и выгрузка этого на сервер.
 *
 * Идея взята у десктопного синка (`sync/sync_runner.py`), но НЕ его реализация, и
 * различие принципиальное. Десктоп держит полноценную копию базы и сливает её
 * построчно, потому что умеет считать средние, часы и долги сам. Телефон этого не
 * умеет и не должен: вся методика живёт в одном месте — на сервере (`grading.py` и
 * далее). Повторить её в JavaScript значило бы завести ВТОРУЮ формулу среднего балла,
 * то есть ровно то, что запрещено инвариантом продукта. Поэтому здесь очередь
 * НАМЕРЕНИЙ («поставить оценку», «создать домашку»), а не копия базы.
 *
 * ━━ ЧТО УМЕЕТ ━━
 *   grade          оценка И ПОСЕЩАЕМОСТЬ (Н/Б/О) — на сервере это один эндпоинт;
 *   lesson.create  новое занятие любого типа, включая ДЗ;
 *   lesson.update  правка занятия (тема, дата, номер);
 *   lesson.delete  удаление занятия;
 *   term           итоговая оценка за семестр (аттестация).
 * То есть тот же набор, что преподаватель делает в журнале на десктопе.
 *
 * ━━ ПОЧЕМУ ЭТО БЕЗОПАСНО ━━
 * • Записи уходят ТЕМИ ЖЕ эндпоинтами, что и с сайта. Отдельного «мобильного» пути
 *   записи нет, значит нет и второй проверки прав: сервер как проверял назначение
 *   преподавателя на предмет и группу, так и проверяет.
 * • Метку времени для LWW ставит СЕРВЕР в момент приёма (инвариант §4.3). Часам
 *   телефона мы не верим вовсе — их владелец волен перевести, и правка «из будущего»
 *   выиграла бы у чужой свежей.
 * • Ключ оценки на сервере детерминирован (`grade_id(student_id, lesson_id)`), запись
 *   идёт upsert'ом: повтор БЕЗВРЕДЕН. Связь оборвалась после отправки, но до ответа —
 *   отправим ещё раз и получим то же самое, а не дубль.
 * • Очередь привязана к ЛОГИНУ автора и выгружается, только когда вошёл он же. На
 *   общем телефоне следующий вошедший не отправит чужие записи под своим именем.
 *
 * ━━ ВРЕМЕННЫЕ id ━━
 * Занятие получает id на СЕРВЕРЕ. Создавая домашку офлайн, мы не знаем его заранее, но
 * оценки по ней преподаватель ставит тут же — им нужно на что-то ссылаться. Поэтому
 * занятие получает временный `tmp:…`, а после успешного создания мы переписываем ВСЕ
 * ждущие записи, которые на него ссылались, на настоящий id. Переписываем сразу и
 * сохраняем: если связь оборвётся следующим же запросом, занятие на сервере уже есть,
 * и оценки обязаны знать его настоящий id — иначе они вечно бились бы о 404.
 *
 * ━━ ЧТО С КОНФЛИКТАМИ ━━
 * Пока преподаватель был офлайн, ту же клетку мог поправить кто-то ещё — в том числе он
 * сам с ПК. До 4.1 побеждала запись, пришедшая позже, то есть ранняя офлайн-правка с
 * телефона молча затирала более позднюю (исследование синка W-13б). Теперь оценка едет с
 * номером изменения клетки, который человек ВИДЕЛ (`base_seq` из журнала), и если клетку
 * за это время поменяли, сервер отвечает 409: запись уходит в «не принято» с пометкой
 * конфликта, и человек сам выбирает — оставить своё или серверное. Тот же порядок, что у
 * очереди программы (F-09): конфликт решает человек, а не порядок доставки.
 * Отказ по СУЩЕСТВУ (предмет больше не ваш, занятие удалено) повторять бессмысленно —
 * такие записи тоже уходят в `rejected` и показываются человеку. Молча выбрасывать их
 * нельзя: для преподавателя это потерянная работа, о которой он не узнает.
 *
 * ━━ ГДЕ ЛЕЖИТ ━━
 * Главная копия — localStorage. В приложении очередь ещё и зеркалится в надёжное
 * хранилище (`@capacitor/preferences`, `setDurableStore`): по документации Capacitor
 * localStorage «временный», ОС вправе освободить его при нехватке места (W-13в), и
 * неотправленные оценки пропали бы вместе с ним. На старте пустая локальная копия
 * восстанавливается из зеркала (`restoreFromDurable`).
 */
import { computed, ref, watch } from 'vue'

// Расширения «.js» здесь обязательны: очередь проверяется голым `node --test`, мимо
// сборщика, а он путь без расширения не разрешает. Тот же случай уже был с grading.js.
import { online } from './offlineSession.js'

const LS_PREFIX = 'gb.outbox.'          // НЕ 'gb.cache.' — переживает выход из аккаунта
const LS_REJECTED = 'gb.outbox.rejected.'
const MAX_TRIES = 5
const TMP = 'tmp:'
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Временные сбои, после которых повтор ОСМЫСЛЕН (аудит 22.09.2026, находка F-06).
 * Раньше любой 4xx считался отказом по существу, и 408 (таймаут) и 429 (ограничитель)
 * выбрасывали запись из очереди в «отклонённые» — оценка, которую сервер просто не
 * успел принять, считалась отвергнутой навсегда.
 */
const TRANSIENT_4XX = new Set([408, 425, 429])
//Повтор по таймеру: 5 c, 10 c, 20 c … до 5 мин, плюс случайная добавка до 30 % —
//чтобы сотня телефонов, потерявших связь разом, не пришла на сервер одной волной.
const RETRY_BASE_MS = 5000
const RETRY_MAX_MS = 5 * 60 * 1000

/** Очередь текущего автора (реактивная копия того, что лежит в localStorage). */
export const pending = ref([])
/** Записи, которые сервер отверг по существу — их надо показать человеку. */
export const rejected = ref([])
/** Идёт ли выгрузка прямо сейчас (чтобы не запустить две разом). */
export const flushing = ref(false)

/**
 * 🔥 ЗАПИСЬ, КОТОРАЯ ПРЯМО СЕЙЧАС ЛЕТИТ НА СЕРВЕР (07.09.2026).
 *
 * Дефект, ради которого заведено. Проверка `if (!pending.value.includes(entry)) continue`
 * закрывала только один случай — запись убрали ДО её очереди. А главная дыра была
 * ВНУТРИ `await send(entry)`: запрос уже ушёл со снимком полей, и всё, что человек делал
 * следующие полсекунды, пропадало молча.
 *   • правка: отправка началась → преподаватель исправил тему занятия → сервер сохранил
 *     ПРЕЖНЮЮ, а очередь опустела. Правки больше нет нигде;
 *   • удаление: удалённое временное занятие всё равно создавалось на сервере — и
 *     оставалось там навсегда, потому что удалять было уже нечего.
 *
 * Лечится ВЕРСИЕЙ операции (`rev`) плюс состоянием «в полёте». Изменение во время
 * полёта не пытается догнать уже ушедший запрос — оно превращается в СЛЕДУЮЩУЮ
 * операцию, которая уйдёт, когда станет известен настоящий id занятия.
 */
let inFlight = null            // { key, rev } — что именно сейчас в сети
//Временные занятия, которые человек удалил, пока их создание летело на сервер.
//Настоящего id ещё нет, поэтому удаление ждёт его здесь.
const deleteAfterCreate = new Set()

/** Только для тестов: что сейчас в полёте. */
export function _inFlight() { return inFlight }

export const pendingCount = computed(() => pending.value.length)

/** Похоже ли это на занятие, которого на сервере ещё нет. */
export function isTempId(id) {
  return typeof id === 'string' && id.startsWith(TMP)
}

function newTempId() {
  const rnd = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`)
  return `${TMP}${rnd}`
}

/** Новый UUID для занятия ('' — генератора нет, id выдаст сервер). */
export function newLessonId() {
  const id = globalThis.crypto?.randomUUID?.() || ''
  return UUID_RE.test(id) ? id.toLowerCase() : ''
}

/**
 * UUID внутри временного id — его и получает сервер как id занятия (F-05).
 * Временный id без UUID (старая очередь, нет генератора) — '' : id выдаст сервер.
 */
export function uuidFromTempId(tempId) {
  const raw = isTempId(tempId) ? tempId.slice(TMP.length) : ''
  return UUID_RE.test(raw) ? raw.toLowerCase() : ''
}

function currentLogin() {
  try {
    return JSON.parse(localStorage.getItem('gb.user') || 'null')?.login || ''
  } catch {
    return ''
  }
}

/**
 * Хранилище отказало в записи (переполнена квота, приватный режим, запрет сайту).
 *
 * 🔥 ЗАЧЕМ ФЛАГ, А НЕ ТИХИЙ `catch` (находка ревью O01). Здесь стояло
 * `catch { /* квота переполнена — очередь короткая, терять нечего *\/ }`, и «терять
 * нечего» было неправдой: очередь и есть та самая работа преподавателя, которую он
 * сделал без сети. Отказ выглядел как успех целиком — журнал писал «оценка сохранена и
 * уйдёт, когда появится связь», а на диск не легло ничего. Следующая же перезагрузка
 * очереди (её делает КАЖДАЯ выгрузка, первой строкой) читала пустой диск и затирала
 * память: оценка исчезала, не дождавшись даже перезапуска вкладки.
 *
 * Флаг делает две вещи: показывает человеку правду и запрещает затирать память
 * неподтверждённым содержимым диска.
 */
export const storageFailed = ref(false)

/**
 * Чей список сейчас лежит в памяти. Нужен ровно для одного различения: «перечитываем
 * своё» (при сломанном диске память свежее) против «сменился человек» (читать обязаны,
 * иначе чужие оценки окажутся на чужом экране — см. O02 ниже).
 */
let loadedFor = ''

function load(key, target) {
  const login = currentLogin()
  if (!login) { target.value = []; return }
  //Диск не подтверждён, и это ТОТ ЖЕ человек — в памяти правда свежее. Перечитать
  //значило бы своими руками стереть его работу пустотой.
  //⚠️ При СМЕНЕ владельца перечитываем всё равно, и работа прежнего в этот момент
  //теряется. Цена названа честно: показать её новому человеку нельзя, а держать
  //невидимой в памяти — значит однажды отправить чужую оценку от его имени.
  if (storageFailed.value && login === loadedFor && target.value.length) return
  try {
    target.value = JSON.parse(localStorage.getItem(key + login) || '[]')
  } catch {
    target.value = []
  }
}

/**
 * Владелец, которому принадлежит ИДУЩАЯ выгрузка. Пусто — выгрузки нет.
 *
 * 🔥 ЗАЧЕМ ОТДЕЛЬНАЯ ПЕРЕМЕННАЯ, А НЕ `currentLogin()` (находка ревью O02). Ответ
 * сервера приходит ПОЗЖЕ отправки, и между этими моментами человек успевает выйти, а
 * на общем компьютере колледжа — войти под другим. `save()` спрашивал логин В МОМЕНТ
 * ЗАПИСИ, то есть поздний отказ по запросу A дописывал ФИО и оценку A в очередь
 * отклонённых у B: чужая фамилия с чужим баллом появлялась на экране человека, который
 * этого не делал. Пока выгрузка идёт, все записи адресуются ТОМУ, чьи это данные.
 */
let flushOwner = ''

// Надёжное зеркало очереди (W-13в). Пусто — зеркала нет (сайт, старый APK без плагина).
let durable = null
export function setDurableStore(store) { durable = store || null }

function mirrorDurable(key, json) {
  if (!durable) return
  try {
    Promise.resolve(durable.set(key, json)).catch(() => {})
  } catch { /* плагина нет в этой сборке — зеркало просто не работает */ }
}

/**
 * Вернуть очередь из надёжного зеркала, если локальная копия пуста (ОС освободила
 * localStorage). Локальная копия — главная: она пишется первой и синхронно, поэтому при
 * живой локальной копии зеркалу не верим. Возвращает, было ли что восстановить.
 */
export async function restoreFromDurable() {
  const login = currentLogin()
  if (!durable || !login) return false
  let restored = false
  for (const prefix of [LS_PREFIX, LS_REJECTED]) {
    let local = null
    try { local = localStorage.getItem(prefix + login) } catch { local = null }
    if (local && local !== '[]') continue
    let saved = null
    try { saved = await durable.get(prefix + login) } catch { saved = null }
    if (!saved || saved === '[]') continue
    try {
      JSON.parse(saved)
      localStorage.setItem(prefix + login, saved)
      restored = true
    } catch { /* битое зеркало или полный диск — оставляем как есть */ }
  }
  if (restored) reloadOutbox()
  return restored
}

function save(key, source) {
  const login = flushOwner || currentLogin()
  if (!login) return false
  //Зеркало — до основной записи и независимо от неё: если локальное хранилище
  //отказало, работа преподавателя переживёт перезапуск хотя бы в зеркале.
  mirrorDurable(key + login, JSON.stringify(source.value))
  try {
    localStorage.setItem(key + login, JSON.stringify(source.value))
    //Запись прошла — прежняя беда позади, и плашку пора убрать. Гасим только на
    //удачной записи: «кажется, стало лучше» тут неотличимо от «стало хуже молча».
    storageFailed.value = false
    return true
  } catch {
    storageFailed.value = true
    return false
  }
}

/** Перечитать очередь текущего пользователя (после входа/смены аккаунта). */
export function reloadOutbox() {
  const login = currentLogin()
  //Сменился человек — прежний флаг к нему не относится: у него своя запись и свой диск.
  if (login !== loadedFor) storageFailed.value = false
  load(LS_PREFIX, pending)
  load(LS_REJECTED, rejected)
  loadedFor = login
}
reloadOutbox()

function persist() {
  pending.value = [...pending.value].sort((a, b) => a.seq - b.seq)
  return save(LS_PREFIX, pending)
}

/**
 * Положить операцию в очередь, схлопнув повтор по тому же ключу.
 *
 * ⚠️ Схлопывание обязательно. Преподаватель, поправивший одну и ту же оценку трижды,
 * должен отправить последнее значение, а не три подряд: сервер применил бы их по
 * очереди, а при обрыве посередине оставил бы не то, что человек видел на экране.
 * Хранить надо намерение, а не историю нажатий.
 */
function enqueue(kind, key, payload) {
  const prev = pending.value.find((e) => e.key === key)
  const rest = pending.value.filter((e) => e.key !== key)
  rest.push({
    kind,
    key,
    payload,
    seq: prev?.seq ?? Date.now() + rest.length,   // порядок постановки переживает правку
    //Версия НАМЕРЕНИЯ. Схлопывание повторов (см. выше) переписывает payload на месте, и
    //без счётчика отличить «то же самое» от «человек успел поправить» нечем: объект тот
    //же, поля другие. Именно на этом и терялась правка, сделанная во время отправки.
    rev: (prev?.rev ?? 0) + 1,
    queuedAt: Date.now(),
    tries: 0,
    lastError: '',
  })
  pending.value = rest
  //Ключ возвращаем как прежде: на него смотрят вызывающие. Правду о том, легло ли на
  //диск, несёт `storageFailed` — иначе пришлось бы менять контракт у пяти постановщиков
  //ради одного редкого случая, и первый забывший проверить вернул бы дефект обратно.
  persist()
  return key
}

// ───────────────────────── постановка операций ─────────────────────────

/**
 * Оценка ИЛИ отметка посещаемости (Н/Б/О) — на сервере это одно и то же.
 *
 * ⚠️ `student_id` едет вместе с ФИО (J08): у двух полных тёзок в группе имя не
 * различает адресата, и сервер выбирал первого найденного. Он же входит в КЛЮЧ — иначе
 * оценки тёзок схлопывались бы в очереди в одну запись, и вторая пропадала бы молча.
 * Пусто у старых записей и клиентов — тогда сервер решает по ФИО, как раньше.
 */
export function enqueueGrade({ surname, name, lesson_id, grade, student_id = '', base_seq }) {
  const key = gradeKey(lesson_id, { student_id, surname, name })
  //База — номер клетки, который человек видел ДО своей первой правки. Повторные правки
  //той же клетки без сети основаны на его же первой, поэтому база не переписывается:
  //иначе вторая правка сравнивалась бы с тем, чего сервер ещё не видел.
  const prev = pending.value.find((e) => e.key === key)
  const payload = { surname, name, lesson_id, grade: grade ?? '', student_id }
  const base = prev ? prev.payload.base_seq : base_seq
  if (Number.isInteger(base) && base >= 0) payload.base_seq = base
  return enqueue('grade', key, payload)
}

/**
 * Решение человека по КОНФЛИКТУ: «оставить моё» — дослать ту же правку БЕЗ сверки базы
 * (осознанно затереть серверное); «оставить серверное» — просто убрать запись.
 *
 * ⚠️ Только для конфликта. Отказ по существу (предмет не ваш, занятие удалено) повтором
 * не лечится, и «оставить моё» для него было бы той самой кнопкой, которая заведомо не
 * поможет (сторож `rejectedWritesVisible.test.mjs`). Для такой записи — ничего не делаем.
 * Возвращает, была ли правка поставлена заново.
 */
export function resolveConflict(key, keepMine) {
  const e = rejected.value.find((x) => x.key === key)
  if (!e || !e.conflict) return false
  dismissRejected(key)
  if (!keepMine) return false
  const payload = { ...e.payload }
  delete payload.base_seq
  enqueue(e.kind, e.key, payload)
  flushOutbox().catch(() => {})
  return true
}

/**
 * Ключ оценки в очереди — ОДНА функция на все места (исследование синка 25.09.2026,
 * W-13а). Их было три, и форматов тоже три: постановка ключевала по `student_id`,
 * поиск ждущей оценки — по ФИО, перепривязка к настоящему id занятия — снова по ФИО.
 * Поиск не находил ни одной современной записи: пунктир «не отправлено» не рисовался,
 * а средний балл без сети не учитывал выставленное — ровно то, ради чего он заведён.
 */
function gradeKey(lessonId, { student_id = '', surname = '', name = '' }) {
  return `grade|${lessonId}|${student_id || `${surname}|${name}`}`
}

/** Та же ли это клетка: по id, если он есть у обеих сторон, иначе по ФИО (J08). */
function sameStudent(p, studentId, surname, name) {
  if (p.student_id && studentId) return p.student_id === studentId
  return p.surname === surname && p.name === name
}

/**
 * Новое занятие (в том числе ДЗ). Возвращает ВРЕМЕННЫЙ id — на него уже можно
 * ставить оценки, очередь сама перепривяжет их к настоящему после отправки.
 */
/**
 * Создание занятия. `lessonId` — UUID, который интерфейс уже пытался отправить онлайн
 * (см. TeacherJournal.saveLesson): если тот запрос дошёл до сервера, а ответ потерялся,
 * повтор с ТЕМ ЖЕ id сервер узнаёт и второго занятия не заводит (аудит F-05). Раньше
 * здесь всегда рождался новый временный id — и потерянный ответ давал дубль.
 */
export function enqueueLessonCreate(payload, lessonId = '') {
  const tempId = UUID_RE.test(lessonId || '') ? `${TMP}${lessonId.toLowerCase()}` : newTempId()
  const body = { ...payload }
  delete body.id
  enqueue('lesson.create', `lesson.create|${tempId}`, { ...body, __tempId: tempId })
  return tempId
}

/**
 * Правка занятия. Если оно ещё само не уехало на сервер, правка ВЛИВАЕТСЯ в его
 * создание: отправлять «создай, а теперь поправь» бессмысленно, а на сервере такого
 * занятия для правки пока и нет.
 */
export function enqueueLessonUpdate(id, payload) {
  if (isTempId(id)) {
    const create = pending.value.find((e) => e.key === `lesson.create|${id}`)
    if (create) {
      create.payload = { ...create.payload, ...payload }
      //⚠️ Версию двигаем ВСЕГДА, а не только когда запись в полёте. Проверять «летит ли
      //прямо сейчас» пришлось бы в каждом месте правки — то есть завести ещё одно
      //место, где однажды забудут. Счётчик дешевле любой проверки.
      create.rev = (create.rev ?? 0) + 1
      persist()
      return create.key
    }
  }
  return enqueue('lesson.update', `lesson.update|${id}`, { id, ...payload })
}

/**
 * Удаление занятия. Занятие, которое ещё не уехало, просто ИСЧЕЗАЕТ из очереди вместе
 * со всеми оценками по нему: создавать его на сервере, чтобы тут же удалить, — лишний
 * круг и лишний шум в чужих уведомлениях (создание ДЗ рассылает письма студентам).
 */
export function enqueueLessonDelete(id) {
  if (isTempId(id)) {
    //🔥 Занятие уже летит на сервер — «просто убрать из очереди» здесь НЕПРАВДА: оно
    //там появится, а удалять будет нечем. Запоминаем намерение и исполним его, как
    //только сервер вернёт настоящий id.
    if (inFlight && inFlight.key === `lesson.create|${id}`) {
      deleteAfterCreate.add(id)
    }
    pending.value = pending.value.filter((e) => !referencesLesson(e, id))
    persist()
    return ''
  }
  return enqueue('lesson.delete', `lesson.delete|${id}`, { id })
}

/**
 * Итоговая оценка за семестр (аттестация).
 *
 * ⚠️ ПЕРИОД ВХОДИТ И В КЛЮЧ, И В ПОЛЕЗНУЮ НАГРУЗКУ (находка ревью J10). Ключ — чтобы
 * ведомости за РАЗНЫЕ семестры не схлопывались в одну запись: без периода итоговая,
 * поставленная в декабре и не успевшая уехать, замещалась бы январской по тому же
 * ключу, и первая исчезала бы молча. Нагрузка — чтобы сервер записал её туда, куда
 * человек ставил: `current_term` считается в момент ИСПОЛНЕНИЯ, а между нажатием и
 * доставкой у очереди лежат каникулы.
 *
 * ⚠️ Период необязателен: у записей, уже лежащих в очереди со старой сборки, его нет, и
 * они обязаны доехать по-прежнему. Сервер сверяет его, только если он пришёл.
 */
export function enqueueTermGrade(payload) {
  const { group, subject, surname, name, student_id, year, semester } = payload
  const term = year && semester ? `|${year}|${semester}` : ''
  //Адресат в ключе — по id, когда он известен (J08): у полных тёзок ключ по ФИО один на
  //двоих, и итоговая одного вытесняла бы итоговую другого прямо в очереди.
  const who = student_id || `${surname}|${name}`
  return enqueue('term', `term|${group}|${subject}|${who}${term}`, payload)
}

// ───────────────────────── чтение очереди интерфейсом ─────────────────────────

/** Значение, ожидающее отправки для этой клетки, или undefined. */
export function pendingGrade(lesson_id, surname, name, student_id = '') {
  //По содержимому, а не по ключу: в очереди телефона могут лежать записи прежних
  //сборок, ключ которых собран по ФИО, — их тоже надо увидеть.
  return pending.value.find((e) => e.kind === 'grade' && e.payload.lesson_id === lesson_id
    && sameStudent(e.payload, student_id, surname, name))?.payload.grade
}

/**
 * Занятия, созданные без сети и ещё не уехавшие. Журналу они нужны, чтобы показать
 * колонку: иначе преподаватель создал бы домашку офлайн и не увидел, куда ставить
 * оценки, — то есть фича существовала бы только на бумаге.
 */
export function pendingLessons(group, subject) {
  return pending.value
    .filter((e) => e.kind === 'lesson.create'
      && (!group || e.payload.group === group)
      && (!subject || e.payload.subject === subject))
    .map((e) => ({ ...e.payload, id: e.payload.__tempId, pending: true }))
}

/** Ссылается ли запись на это занятие (само занятие или оценка по нему). */
function referencesLesson(entry, lessonId) {
  if (entry.kind === 'lesson.create') return entry.payload.__tempId === lessonId
  if (entry.kind === 'grade') return entry.payload.lesson_id === lessonId
  if (entry.kind === 'lesson.update' || entry.kind === 'lesson.delete') {
    return entry.payload.id === lessonId
  }
  return false
}

/** Убрать запись из отвергнутых (человек её посмотрел). */
export function dismissRejected(key) {
  rejected.value = rejected.value.filter((e) => e.key !== key)
  save(LS_REJECTED, rejected)
}

/** Полностью очистить очередь текущего автора. Только по явной команде человека. */
export function clearOutbox() {
  pending.value = []
  rejected.value = []
  deleteAfterCreate.clear()
  save(LS_PREFIX, pending)
  save(LS_REJECTED, rejected)
}

function reject(entry, reason, conflict = null) {
  const item = { ...entry, reason, rejectedAt: Date.now() }
  if (conflict) item.conflict = conflict
  rejected.value = [...rejected.value, item]
  save(LS_REJECTED, rejected)
}

// ───────────────────────── отправка ─────────────────────────

/**
 * Кто именно отправляет запись. Обычно — тот же axios-клиент, что и весь сайт; в
 * тестах подменяется. Импорт ленивый НАМЕРЕННО: очередь не должна тянуть за собой
 * HTTP-клиент, который при загрузке модуля лезет в localStorage и в адрес сервера, —
 * иначе её нельзя проверить иначе как в живом браузере, а сторож, который негде
 * запустить, не пишется вовсе.
 */
let sender = null
export function setSender(fn) { sender = fn }

async function send(entry) {
  if (sender) return sender(entry)
  const { api } = await import('./client.js')
  const p = entry.payload
  switch (entry.kind) {
    case 'grade':
      return api.post('/web/teacher/grade', p)
    case 'lesson.create':
      return api.post('/web/teacher/lesson', lessonCreateBody(p))
    case 'lesson.update': {
      const body = { ...p }
      delete body.id
      return api.put(`/web/teacher/lesson/${encodeURIComponent(p.id)}`, body)
    }
    case 'lesson.delete':
      return api.delete(`/web/teacher/lesson/${encodeURIComponent(p.id)}`)
    case 'term':
      return api.post('/web/teacher/term-grade', p)
    default:
      throw new Error(`неизвестный тип записи: ${entry.kind}`)
  }
}

/**
 * Занятие уехало и получило настоящий id — переписываем всех, кто на него ссылался.
 * Сразу и с сохранением: оборвись связь на следующем запросе, оценки уже знают, куда
 * им идти, и не будут вечно биться о несуществующий `tmp:…`.
 */
function remapTempId(tempId, realId) {
  for (const e of pending.value) {
    if (e.kind === 'grade' && e.payload.lesson_id === tempId) {
      e.payload.lesson_id = realId
      e.key = gradeKey(realId, e.payload)
    } else if ((e.kind === 'lesson.update' || e.kind === 'lesson.delete')
               && e.payload.id === tempId) {
      e.payload.id = realId
      e.key = `${e.kind}|${realId}`
    }
  }
  persist()
}

/**
 * Выгрузить очередь. Строго последовательно и в порядке постановки: занятие обязано
 * уехать раньше оценок по нему, а параллельные запросы с телефона на одноядерный
 * сервер ничего не ускорят, зато усложнят разбор, если что-то пойдёт не так.
 *
 * Возвращает {sent, failed, rejected}.
 */
export async function flushOutbox() {
  if (flushing.value) return { sent: 0, failed: 0, rejected: 0 }
  reloadOutbox()
  if (!pending.value.length) return { sent: 0, failed: 0, rejected: 0 }

  //🔒 Владельца закрепляем ДО первой отправки и держим до конца цикла: дальше все
  //записи в хранилище идут именно ему, а смена аккаунта останавливает выгрузку.
  const owner = currentLogin()
  if (!owner) return { sent: 0, failed: 0, rejected: 0 }
  flushOwner = owner

  flushing.value = true
  const stats = { sent: 0, failed: 0, rejected: 0 }
  try {
    for (const entry of [...pending.value].sort((a, b) => a.seq - b.seq)) {
      // Запись могли переписать или удалить, пока шёл предыдущий запрос.
      if (!pending.value.includes(entry)) continue
      //🔒 Аккаунт сменился, пока мы ждали предыдущий ответ — останавливаемся. Очередь
      //A не имеет права уезжать под токеном B: это была бы запись данных A от имени
      //другого человека, и на сервере она выглядела бы совершенно законной.
      if (currentLogin() !== owner) break
      const sentRev = entry.rev ?? 0
      inFlight = { key: entry.key, rev: sentRev }
      try {
        const resp = await send(entry)
        //🔑 СНАЧАЛА разбираемся, что произошло с записью ПОКА мы ждали ответ, и только
        //потом убираем её из очереди. Прежний порядок («убрали, потом разобрались»)
        //и терял правку: она была применена к объекту, которого уже нет в очереди.
        const changed = (entry.rev ?? 0) !== sentRev
        pending.value = pending.value.filter((e) => e !== entry)
        if (entry.kind === 'lesson.create') {
          const realId = resp?.data?.id
          if (realId) {
            remapTempId(entry.payload.__tempId, realId)
            //Занятие удалили, пока оно летело: теперь id известен — удаляем по-настоящему.
            if (deleteAfterCreate.delete(entry.payload.__tempId)) {
              enqueue('lesson.delete', `lesson.delete|${realId}`, { id: realId })
            } else if (changed) {
              //Человек поправил занятие, пока летело создание. Сервер сохранил прежние
              //поля — досылаем правку отдельной операцией, уже по настоящему id.
              const body = { ...entry.payload }
              delete body.__tempId
              enqueue('lesson.update', `lesson.update|${realId}`, { id: realId, ...body })
            }
          } else {
            // Сервер принял, но id не вернул — редкость, однако тогда оценки по этому
            // занятию отправить некуда. Честно признаём это, а не шлём их в никуда.
            dropDependents(entry.payload.__tempId,
              'занятие создано, но сервер не вернул его номер')
            deleteAfterCreate.delete(entry.payload.__tempId)
          }
        }
        //⚠️ ВЕТКИ «обычная запись изменилась в полёте» здесь НЕТ, и это не забывчивость.
        //Обычный `enqueue` не правит запись на месте: он выбрасывает прежнюю по ключу и
        //кладёт НОВЫЙ объект. Значит правка оценки во время отправки уже уцелела сама —
        //старый объект уходит из очереди, свежий остаётся и уедет следующим кругом.
        //Мутируется на месте РОВНО ОДИН случай — слияние правки с ещё не уехавшим
        //созданием занятия (`enqueueLessonUpdate` по временному id), и именно он выше.
        //Дописать сюда «на всякий случай» ещё одну ветку значило бы отправить оценку
        //дважды и завести код, который невозможно ни проверить, ни отладить.
        persist()
        stats.sent += 1
      } catch (err) {
        const status = err?.response?.status
        if (!status) {
          // Ответа нет — связь опять пропала. Прекращаем: остальное ждёт следующего
          // раза. Ошибкой записи это не считается, она не отвергнута.
          stats.failed += 1
          stats.transient = true
          break
        }
        if (status === 401 || (status === 403 && !entry.tries)) {
          // 401 — сессия кончилась, выгружать нечем; 403 на ПЕРВОЙ попытке чаще всего
          // тоже про сессию или устройство, а не про предмет. Останавливаемся и ждём,
          // пока человек войдёт заново.
          entry.tries += 1
          entry.lastError = `HTTP ${status}`
          persist()
          break
        }
        if (status >= 400 && status < 500 && !TRANSIENT_4XX.has(status)) {
          // Отказ по существу: занятие удалено, предмет больше не ваш, студента нет в
          // группе. Повторять нечего — сколько ни шли, ответ будет тот же.
          // 409 с кодом `conflict` — отдельный случай: клетку поменяли, пока правка ждала.
          // Причину показываем словами, а серверное значение — рядом, чтобы выбрать.
          pending.value = pending.value.filter((e) => e !== entry)
          const detail = err?.response?.data?.detail
          const conflict = status === 409 && detail && typeof detail === 'object'
            && detail.code === 'conflict' ? { server: detail.server || {} } : null
          reject(entry, conflict ? (detail.message || 'конфликт') : (detail || `HTTP ${status}`),
            conflict)
          stats.rejected += 1
          if (entry.kind === 'lesson.create') {
            stats.rejected += dropDependents(entry.payload.__tempId,
              'занятие не создано, оценка по нему не имеет смысла')
          }
          persist()
          continue
        }
        // 5xx, 408, 425, 429 — сервер жив, но сейчас не может. Пробуем ещё, но не
        // бесконечно: запись, которую сервер стабильно не принимает, обязана стать видимой.
        entry.tries += 1
        entry.lastError = `HTTP ${status}`
        if (entry.tries >= MAX_TRIES) {
          pending.value = pending.value.filter((e) => e !== entry)
          reject(entry, `сервер не принял после ${MAX_TRIES} попыток (HTTP ${status})`)
          stats.rejected += 1
        } else {
          stats.failed += 1
          stats.transient = true
        }
        persist()
        break
      }
    }
  } finally {
    inFlight = null
    flushing.value = false
    flushOwner = ''
    //Если за время выгрузки вошёл другой человек, в памяти модуля лежит очередь
    //ПРЕДЫДУЩЕГО: перечитываем под нового, иначе его экран покажет чужие записи.
    if (currentLogin() !== owner) reloadOutbox()
  }
  if (stats.transient && pending.value.length) scheduleRetry()
  else if (!stats.failed) retryAttempt = 0
  delete stats.transient
  return stats
}

// ───────────────────────── повтор по таймеру (F-06) ─────────────────────────
//🔥 Раньше повтор ждал ТОЛЬКО перехода «офлайн → онлайн». Сервер ответил 503 при живой
//сети — перехода не будет, и очередь лежала до перезапуска приложения или следующей
//потери связи. Человек видел «ждёт отправки» часами при работающем интернете.
let retryTimer = null
let retryAttempt = 0

function scheduleRetry() {
  if (retryTimer) return
  //Без сети таймер не нужен: сработает переход «онлайн» (startOutboxWatch).
  if (online && online.value === false) return
  const base = Math.min(RETRY_BASE_MS * 2 ** Math.min(retryAttempt, 10), RETRY_MAX_MS)
  const delay = Math.round(base + Math.random() * base * 0.3)
  retryAttempt += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    flushOutbox().catch(() => {})
  }, delay)
}

/**
 * Тело запроса создания занятия из записи очереди. Отдельной функцией — чтобы проверять
 * её напрямую: подменная отправка в тестах обходит `send`, и проверка id внутри него не
 * покраснела бы никогда.
 *
 * Тот же id при каждом повторе: ответ потерялся — сервер вернёт уже созданное занятие,
 * а не заведёт второе (аудит 22.09.2026, F-05).
 */
export function lessonCreateBody(payload) {
  const body = { ...payload }
  delete body.__tempId
  const uid = uuidFromTempId(payload.__tempId)
  if (uid) body.id = uid
  return body
}

/** Только для тестов: состояние повтора; `reset` — остановить таймер. */
export function _retryState(reset = false) {
  if (reset) {
    if (retryTimer) clearTimeout(retryTimer)
    retryTimer = null
    retryAttempt = 0
  }
  return { scheduled: Boolean(retryTimer), attempt: retryAttempt }
}

/** Снять с очереди всё, что ссылалось на несостоявшееся занятие. */
function dropDependents(tempId, reason) {
  const doomed = pending.value.filter((e) => referencesLesson(e, tempId))
  if (!doomed.length) return 0
  pending.value = pending.value.filter((e) => !doomed.includes(e))
  doomed.forEach((e) => reject(e, reason))
  persist()
  return doomed.length
}

/**
 * Выгружать, как только вернулась связь.
 *
 * Именно по ПЕРЕХОДУ офлайн -> онлайн, а не по таймеру: пока сети нет, попытки только
 * жгут батарею и ничего не меняют.
 */
export function startOutboxWatch() {
  watch(online, (isOnline, was) => {
    if (isOnline && !was) flushOutbox().catch(() => {})
  })
}
