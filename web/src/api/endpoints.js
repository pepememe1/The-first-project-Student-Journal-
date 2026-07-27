/**
 * endpoints.js — типизированные обёртки над REST API.
 *
 * Здесь собран ВЕСЬ контракт, который использует веб-клиент. Часть эндпоинтов уже
 * есть на сервере (/auth/*, /me/*, /admin/*, /connect/*), часть — новые role-scoped
 * READ-представления под веб (/web/*), которые считаются на сервере (grading.py как
 * единый источник расчёта). Пока /web/* не реализованы — страницы показывают пустое
 * состояние (запрос вернёт 404), это ожидаемо на текущем этапе.
 *
 * Почему вебу нужны отдельные /web/*, а не /sync/pull: pull отдаёт ВСЕ строки всех
 * таблиц (включая password_hash и чужие оценки) — в браузер это выгружать нельзя.
 * /web/* возвращают только то, что роль вправе видеть, уже в готовом для UI виде.
 */
import { api } from './client'

// АВТОРИЗАЦИЯ ──────────────────────────────────────────────────────────────────
export const authApi = {
  login: (login, password) => api.post('/auth/login', { login, password }),
  refresh: (refresh_token) => api.post('/auth/refresh', { refresh_token }),
  logout: () => api.post('/auth/logout'),
  // Самостоятельная регистрация студента (заявка админу) и восстановление пароля.
  register: (payload) => api.post('/auth/register', payload),
  recover: (email) => api.post('/auth/recover', { email }),
  // Passkeys (вход по Face ID / отпечатку). begin выдаёт опции с challenge, complete
  // проверяет ответ устройства. register — под токеном (включить), login — публичный.
  webauthnRegisterBegin: () => api.post('/auth/webauthn/register/begin'),
  webauthnRegisterComplete: (payload) => api.post('/auth/webauthn/register/complete', payload),
  webauthnLoginBegin: (login = '') => api.post('/auth/webauthn/login/begin', { login }),
  webauthnLoginComplete: (payload) => api.post('/auth/webauthn/login/complete', payload),
  webauthnList: () => api.get('/auth/webauthn/credentials'),
  webauthnDelete: (id) => api.post('/auth/webauthn/credentials/delete', { id }),
}

// ЛИЧНЫЕ НАСТРОЙКИ (тема и пр.) ──────────────────────────────────────────────────
export const meApi = {
  getPrefs: () => api.get('/me/prefs'),
  setPrefs: (prefs) => api.post('/me/prefs', { prefs }),
  // Пуш-уведомления (только в мобильном приложении — в браузере токена нет).
  // Токен подтверждаем при КАЖДОМ запуске: сервер по нему обновляет владельца
  // устройства и метку «живо», иначе уборка выбросит рабочий телефон.
  registerPushToken: (token, platform = 'android') =>
    api.post('/me/push-token', { token, platform }),
  deletePushToken: (token) => api.delete('/me/push-token', { data: { token } }),
  // Куда открыть экран по нажатому уведомлению (детали НЕ приходят в самом пуше).
  getEvent: (id) => api.get(`/me/events/${id}`),
  // Без параметров сервер отдаёт ТОЛЬКО непрочитанные — так исторически ждёт
  // мобильное приложение, поэтому вызов оставлен как есть.
  unreadEvents: () => api.get('/me/events'),
  // Вкладка «Уведомления»: вся почта, включая прочитанное.
  events: (params = {}) => api.get('/me/events', { params: { filter: 'all', ...params } }),
  unreadCount: () => api.get('/me/events/unread-count'),
  markEventRead: (id) => api.post(`/me/events/${id}/read`),
  markAllEventsRead: () => api.post('/me/events/read-all'),
}

// ВЕБ-ПОДТВЕРЖДЕНИЕ УСТРОЙСТВА (для teacher/admin) ────────────────────────────────
// Тот же поток, что в десктопе: запрос → админ выдаёт 6-значный код → ввод кода.
export const connectApi = {
  request: (device_id, hostname) => api.post('/connect/request', { device_id, hostname }),
  status: (device_id) => api.get('/connect/status', { params: { device_id } }),
  verify: (device_id, code) => api.post('/connect/verify', { device_id, code }),
  // админ:
  list: () => api.get('/connect/requests'),
  approve: (device_id) => api.post('/connect/approve', { device_id }),
  reject: (device_id) => api.post('/connect/reject', { device_id }),
}

// СТУДЕНТ ────────────────────────────────────────────────────────────────────────
export const studentApi = {
  overview: () => api.get('/web/student/overview'),
  // params: { year, semester } — просмотр архива; без них — текущий семестр.
  journal: (params = {}) => api.get('/web/student/journal', { params }),
  stats: (params = {}) => api.get('/web/student/stats', { params }),
  insights: () => api.get('/web/student/insights'),
}

// ПРЕПОДАВАТЕЛЬ ───────────────────────────────────────────────────────────────────
export const teacherApi = {
  overview: () => api.get('/web/teacher/overview'),
  // params: { year, semester } — архив прошлого семестра; без них — текущий.
  journal: (group, subject, params = {}) => api.get('/web/teacher/journal', { params: { group, subject, ...params } }),
  students: (group) => api.get('/web/teacher/students', { params: { group } }),
  stats: (group, subject, params = {}) => api.get('/web/teacher/stats', { params: { group, subject, ...params } }),
  insights: (group) => api.get('/web/teacher/insights', { params: { group } }),
  // Запись оценки (Phase B). Пустой grade = снять оценку. Сервер ставит метку LWW.
  setGrade: (surname, name, lesson_id, grade) =>
    api.post('/web/teacher/grade', { surname, name, lesson_id, grade }),
  // Занятия/пары (Phase B): наполнение журнала. id = uuid на сервере.
  createLesson: (payload) => api.post('/web/teacher/lesson', payload),
  updateLesson: (id, payload) => api.put(`/web/teacher/lesson/${encodeURIComponent(id)}`, payload),
  deleteLesson: (id) => api.delete(`/web/teacher/lesson/${encodeURIComponent(id)}`),
  // Экспорт журнала (fmt=xlsx|docx) за выбранный семестр. Единый стиль TNR 14, ч/б.
  journalExport: (group, subject, params = {}) =>
    api.get('/web/teacher/journal-export', { params: { group, subject, ...params }, responseType: 'blob' }),
  // Итоговые оценки за семестр (промежуточная аттестация) + ведомость (fmt=xlsx|docx).
  setTermGrade: (payload) => api.post('/web/teacher/term-grade', payload),
  termGrades: (group, subject, params = {}) => api.get('/web/teacher/term-grades', { params: { group, subject, ...params } }),
  vedomost: (group, subject, params = {}) =>
    api.get('/web/teacher/vedomost', { params: { group, subject, ...params }, responseType: 'blob' }),
}

// УЧЕБНЫЙ ПЕРИОД (год/семестр) ────────────────────────────────────────────────────
export const termsApi = {
  list: () => api.get('/web/terms'),
}

// КУРАТОР (read-only по курируемым группам) ───────────────────────────────────────
export const curatorApi = {
  groups: () => api.get('/web/curator/groups'),
  // group/subject идут в QUERY, а не в путь: имена групп содержат слэш («К75/1»), и в
  // пути %2F ломает роутинг FastAPI (эндпоинт молча 404-ил → «нет предметов»).
  subjects: (group, params = {}) =>
    api.get('/web/curator/subjects', { params: { group, ...params } }),
  groupSubject: (group, subject, params = {}) =>
    api.get('/web/curator/group-subject', { params: { group, subject, ...params } }),
  // Сводный отчёт успеваемости. groups: 'all' | 'К74/1,К75/1'; fmt: 'xlsx' | 'docx'.
  // responseType blob — сервер отдаёт файл, а не JSON.
  report: (groups, fmt, params = {}) =>
    api.get('/web/curator/report', {
      params: { groups, fmt, ...params }, responseType: 'blob',
    }),
}

// АДМИН ──────────────────────────────────────────────────────────────────────────
export const adminApi = {
  overview: () => api.get('/web/admin/overview'),
  teachers: () => api.get('/web/admin/teachers'),
  students: (group = '') => api.get('/web/admin/students', { params: { group } }),
  groups: () => api.get('/web/admin/groups'),
  subjects: () => api.get('/web/admin/subjects'),
  // CRUD студентов (Phase B). id на сервере = stud:login (как в синке десктопа).
  createStudent: (payload) => api.post('/web/admin/students', payload),
  updateStudent: (login, payload) =>
    api.put(`/web/admin/students/${encodeURIComponent(login)}`, payload),
  deleteStudent: (login) =>
    api.delete(`/web/admin/students/${encodeURIComponent(login)}`),
  // CRUD групп и предметов (Phase B).
  createGroup: (payload) => api.post('/web/admin/groups', payload),
  updateGroup: (name, payload) => api.put(`/web/admin/groups/${encodeURIComponent(name)}`, payload),
  deleteGroup: (name) => api.delete(`/web/admin/groups/${encodeURIComponent(name)}`),
  // Привязать предметы из расписания ко ВСЕМ группам (+ пополнить каталог).
  bindSubjects: () => api.post('/web/admin/groups/bind-subjects'),
  // Учебные часы группы: план на семестр по каждому предмету + уже пройденное.
  groupHours: (group) => api.get('/web/admin/group-hours', { params: { group } }),
  saveGroupHours: (group, hours) => api.post('/web/admin/group-hours', { group, hours }),
  createSubject: (name) => api.post('/web/admin/subjects', { name }),
  deleteSubject: (name) => api.delete(`/web/admin/subjects/${encodeURIComponent(name)}`),
  // CRUD преподавателей (Phase B). id на сервере = teach:login.
  createTeacher: (payload) => api.post('/web/admin/teachers', payload),
  updateTeacher: (login, payload) => api.put(`/web/admin/teachers/${encodeURIComponent(login)}`, payload),
  deleteTeacher: (login) => api.delete(`/web/admin/teachers/${encodeURIComponent(login)}`),
  // Перевод на курс (rollover): продвинуть текущий учебный период. Прошлые — в архив.
  rolloverTerm: (payload = {}) => api.post('/web/admin/term/rollover', payload),
  // Заявки на регистрацию студентов.
  registrations: () => api.get('/web/admin/registrations'),
  approveRegistration: (id) => api.post('/web/admin/registrations/approve', { id }),
  rejectRegistration: (id, note = '') => api.post('/web/admin/registrations/reject', { id, note }),
  // Настройки ИИ «Вектор» (провайдер + ключ GigaChat/модель Ollama). Хранятся в той же
  // строке config, что и на десктопе → синхронизируются в обе стороны.
  aiConfig: () => api.get('/web/admin/ai-config'),
  aiConfigSave: (payload) => api.post('/web/admin/ai-config', payload),
  aiConfigTest: (payload) => api.post('/web/admin/ai-config/test', payload),
  // Редактор расписания (правки ПОВЕРХ портала). schedule — слитое расписание + правки;
  // set — задать/заменить/скрыть пару в ячейке; del — убрать правку (вернуться к порталу).
  schedule: (group) => api.get('/web/admin/schedule', { params: { group } }),
  setScheduleOverride: (payload) => api.post('/web/admin/schedule/override', payload),
  deleteScheduleOverride: (id) => api.delete(`/web/admin/schedule/override/${encodeURIComponent(id)}`),
  // Пачечное сохранение черновика редактора (переносы/правки) — одной транзакцией.
  saveScheduleOverrides: (overrides) => api.post('/web/admin/schedule/overrides', { overrides }),
  // «Взять с ВСГУТУ» — форс-обновление кэша портала (для группы или для всех — в фоне).
  refreshSchedule: (group = '', all = false) =>
    api.post('/web/admin/schedule/refresh', null, { params: all ? { all: 1 } : { group } }),
  // Сброс правок: снова берётся портал. all=1 стирает ВСЕ правки колледжа (подтверждать!).
  resetSchedule: (group = '', all = false) =>
    api.post('/web/admin/schedule/reset', null, { params: all ? { all: 1 } : { group } }),
  // Накладки конкретного слота при переносе пары (подсветка сразу после drag-drop).
  slotConflicts: (params) => api.get('/web/admin/schedule/slot-conflicts', { params }),
  // Сверка расписаний: накладки (один преподаватель/аудитория в одном слоте у разных
  // групп). ⚠️ Ответ с building=true означает «снимок портала ещё собирается», а НЕ
  // «накладок нет» — показывать эти состояния надо по-разному.
  scheduleConflicts: () => api.get('/web/admin/schedule/conflicts'),
  // Пометить слот совместной парой (законное совпадение) / снять пометку.
  setScheduleJoint: (payload) => api.post('/web/admin/schedule/joint', payload),
  deleteScheduleJoint: (id) => api.delete(`/web/admin/schedule/joint/${encodeURIComponent(id)}`),
  // Разослать уведомление об изменении расписания группы (явная кнопка, а не автомат
  // на каждую правку ячейки — иначе студент получит десятки уведомлений подряд).
  publishSchedule: (group) => api.post('/web/admin/schedule/publish', { group }),
  // Инфо-панель «Сервер и сайт» (адрес, БД, шифрование, ГОСТ, онлайн, период).
  serverInfo: () => api.get('/web/admin/server-info'),
  // Служебное — уже реализовано на сервере:
  online: () => api.get('/admin/online'),
  events: (since = 0) => api.get('/admin/events', { params: { since } }),
  sessions: (active = true) => api.get('/admin/sessions', { params: { active } }),
  revoke: (payload) => api.post('/admin/sessions/revoke', payload),
}

// РАСПИСАНИЕ (сервер отдаёт снимок с portal.esstu.ru; ПДн не участвуют) ───────────
export const scheduleApi = {
  get: (group) => api.get('/web/schedule', { params: { group } }),
  groups: () => api.get('/web/schedule/groups'),
  // Расписание преподавателя (пункт 2): без name сервер матчит ФИО текущего юзера.
  teacher: (name = '') => api.get('/web/schedule/teacher', { params: { name } }),
  // Выгрузка расписания группы файлом (fmt: xlsx|docx). Строится из ТОГО ЖЕ слитого
  // расписания (портал + правки админа), что показано на сайте.
  exportFile: (group, fmt = 'xlsx') =>
    api.get('/web/schedule/export', { params: { group, fmt }, responseType: 'blob' }),
}

// РОДИТЕЛЬ — самый ограниченный кабинет: журнал своих детей и Вектор по ним же.
// Доступ открывает не привязка сотрудника, а подтверждение самого студента, поэтому
// journal/vector отвечают 403, пока согласия нет (см. server/app/routers/parent.py).
export const parentApi = {
  children: () => api.get('/web/parent/children'),
  journal: (studentId = '', year = '', semester = 0) =>
    api.get('/web/parent/journal', { params: { student_id: studentId, year, semester } }),
  vectorAsk: (message, studentId = '') =>
    api.post('/web/parent/vector/ask', { message, student_id: studentId }),
}

// Согласие студента на доступ родителя к его журналу (152-ФЗ) — в кабинете студента.
export const consentApi = {
  links: () => api.get('/web/student/parent-links'),
  decide: (linkId, approve) =>
    api.post(`/web/student/parent-links/${encodeURIComponent(linkId)}/decide`, { approve }),
}

// Привязка родителей сотрудником (админ — любые группы, куратор — только свои).
export const staffParentApi = {
  parents: () => api.get('/web/staff/parents'),
  links: (group = '') => api.get('/web/staff/parent-links', { params: { group } }),
  link: (parentId, studentId) =>
    api.post('/web/staff/parent-links', { parent_id: parentId, student_id: studentId }),
  unlink: (linkId) => api.delete(`/web/staff/parent-links/${encodeURIComponent(linkId)}`),
  create: (payload) => api.post('/web/admin/parents', payload),
}

// «ВЕКТОР» — серверный анти-галлюцинационный конвейер (intents→SQL→анонимизация→LLM)
export const vectorApi = {
  ask: (message) => api.post('/web/vector/ask', { message }),
  // Озвучка (TTS): текст ответа → WAV-аудио. Голос — male|female из настроек.
  // arraybuffer — чтобы декодировать через Web Audio API (надёжнее автоплея <audio>).
  ttsStatus: () => api.get('/web/vector/tts/status'),
  tts: (text, voice = 'male') =>
    api.post('/web/vector/tts', { text, voice }, { responseType: 'arraybuffer' }),
}

// МЕССЕНДЖЕР (см. docs/MESSENGER-PLAN.md) ─────────────────────────────────────────
// Отдельная онлайн-подсистема (НЕ через /sync). Фаза 1/2: личные чаты + каталог людей.
export const messengerApi = {
  // Каталог/поиск людей для выбора собеседника (role: student|teacher).
  users: (role = 'student', q = '', page = 0) =>
    api.get('/web/messenger/users', { params: { role, q, page } }),
  profile: (id) => api.get(`/web/messenger/users/${encodeURIComponent(id)}/profile`),
  // Чаты.
  chats: () => api.get('/web/messenger/chats'),
  openDirect: (userId) => api.post(`/web/messenger/chats/direct/${encodeURIComponent(userId)}`),
  // Сообщения: history (before=<id>) / poll (after=<id>) / последние (без параметров).
  messages: (convId, params = {}) =>
    api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/messages`, { params }),
  // clientNonce (§D10): UUID клиента — повтор с тем же nonce не создаёт дубль на сервере
  // (защита от ретраев при обрыве сети/двойном клике).
  send: (convId, body, replyToId = 0, clientNonce = '') =>
    api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/messages`,
      { body, reply_to_id: replyToId, client_nonce: clientNonce }),
  read: (convId, lastMessageId = 0) =>
    api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/read`,
      { last_message_id: lastMessageId }),
  // Мьют беседы у себя (без пушей по ней).
  muteChat: (convId, muted = true) =>
    api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/mute`, { muted }),
  // Удалить переписку у себя (clearOnly — только очистить историю, чат остаётся).
  deleteChat: (convId, clearOnly = false) =>
    api.delete(`/web/messenger/chats/${encodeURIComponent(convId)}`,
      { params: { clear_only: clearOnly } }),
  // Действия над сообщением (Фаза 3).
  edit: (id, body) => api.patch(`/web/messenger/messages/${id}`, { body }),
  deleteMessage: (id, scope = 'self') =>
    api.delete(`/web/messenger/messages/${id}`, { params: { scope } }),
  pin: (id) => api.post(`/web/messenger/messages/${id}/pin`),
  unpin: (id) => api.delete(`/web/messenger/messages/${id}/pin`),
  pinned: (convId) => api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/pinned`),
  forward: (messageIds, toConversationIds) =>
    api.post('/web/messenger/messages/forward',
      { message_ids: messageIds, to_conversation_ids: toConversationIds }),
  // Реакции-эмодзи (§D3) и история редактирования (§D11).
  addReaction: (mid, emoji) => api.post(`/web/messenger/messages/${mid}/reactions`, { emoji }),
  removeReaction: (mid, emoji) =>
    api.delete(`/web/messenger/messages/${mid}/reactions/${encodeURIComponent(emoji)}`),
  reactionUsers: (mid) => api.get(`/web/messenger/messages/${mid}/reactions`),
  messageHistory: (mid) => api.get(`/web/messenger/messages/${mid}/history`),
  report: (messageId, reasonCode, description = '') =>
    api.post('/web/messenger/reports',
      { message_id: messageId, reason_code: reasonCode, description }),
  // Чат с модерацией (кнопка ⚙).
  moderation: () => api.get('/web/messenger/moderation'),
  // Группы и каналы (Фазы 5–6).
  // classGroups (§12, режим куратора) — названия учебных групп, чьи студенты добавятся
  // автоматически; сервер сам ограничит их курируемыми группами звонящего.
  createGroup: (title, memberIds = [], about = '', classGroups = []) =>
    api.post('/web/messenger/chats/group',
      { title, member_ids: memberIds, about, class_groups: classGroups }),
  createChannel: (title, writerIds = [], isPublic = true, about = '') =>
    api.post('/web/messenger/chats/channel', { title, writer_ids: writerIds, is_public: isPublic, about }),
  channels: (q = '') => api.get('/web/messenger/channels', { params: { q } }),
  join: (convId) => api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/join`),
  leave: (convId) => api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/leave`),
  convInfo: (convId) => api.get(`/web/messenger/chats/${encodeURIComponent(convId)}`),
  // §D6: переименовать группу/канал (owner/admin) — пишет системное сообщение.
  renameChat: (convId, title, about) =>
    api.patch(`/web/messenger/chats/${encodeURIComponent(convId)}`, { title, about }),
  // §D7: статус (поверх presence) — dnd/studying/away + текст (только у преподавателя).
  getStatus: () => api.get('/web/messenger/status'),
  setStatus: (kind, customText = '') =>
    api.post('/web/messenger/status', { kind, custom_text: customText }),
  // Группы, которые сотрудник может адресовать (объявления/отчёты) — для выпадающего
  // списка вместо ручного ввода.
  myGroups: () => api.get('/web/messenger/my-groups'),
  // §D12: открыть/создать системный канал «Объявления · Группа» (teacher/admin), дальше
  // публикация — обычным send() в этот же чат (это просто kind='channel').
  // ⚠️ Группа идёт в QUERY, а не в путь: имена вида «К75/1» в пути превращались в %2F,
  // Starlette декодировал его обратно в «/», роут не совпадал и запрос молча 404-ил.
  ensureAnnouncementsChannel: (groupName) =>
    api.post('/web/messenger/channels/announcements', null, { params: { group: groupName } }),
  // §12: канал «Отчёты · Группа» (куратор). Группа — тоже в query, причина та же.
  ensureCuratorReportsChannel: (groupName) =>
    api.post('/web/messenger/channels/curator-reports', null, { params: { group: groupName } }),
  // §12: кому предложить отчёт (родители с подтверждённой связью + подходящие беседы).
  reportRecipients: (group) =>
    api.get('/web/messenger/report-recipients', { params: { group } }),
  // §12: создать отчёт и отправить его сообщением. Без адресатов — себе в «Избранное».
  createReport: (group, toUserIds = [], toConversationIds = []) =>
    api.post('/web/messenger/curator-reports',
      { group, to_user_ids: toUserIds, to_conversation_ids: toConversationIds }),
  // Организация списка чатов (docs/MESSENGER-ADDON-PLAN-GPT*.md): закреп/архив/избранное.
  pinChat: (convId) => api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/pin`),
  unpinChat: (convId) => api.delete(`/web/messenger/chats/${encodeURIComponent(convId)}/pin`),
  archiveChat: (convId) => api.post(`/web/messenger/chats/${encodeURIComponent(convId)}/archive`),
  unarchiveChat: (convId) => api.delete(`/web/messenger/chats/${encodeURIComponent(convId)}/archive`),
  openSaved: () => api.post('/web/messenger/chats/saved'),
  // Треды (ответы на сообщение) и поиск внутри чата.
  thread: (convId, messageId) =>
    api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/messages/thread/${messageId}`),
  searchInChat: (convId, q) =>
    api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/messages/search`, { params: { q } }),
  // §17: поиск по СМЫСЛУ. Модель расширяет ЗАПРОС словоформами и синонимами; сама
  // переписка ей не показывается (сопоставление делает сервер). Нет модели — результат
  // совпадает с обычным searchInChat, поле expanded приходит пустым.
  aiSearchInChat: (convId, q) =>
    api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/messages/ai-search`, { params: { q } }),
  // §18: сводка переписки. Запускается ТОЛЬКО кнопкой (запрос к модели на каждый вход в
  // чат — заметная нагрузка на одноядерный VPS). ФИО маскируются на сервере до отправки.
  chatSummary: (convId) =>
    api.get(`/web/messenger/chats/${encodeURIComponent(convId)}/summary`),
  // §19: напоминания. Дату из текста разбирает СЕРВЕР детерминированно, без модели.
  reminderSuggest: (mid) => api.get(`/web/messenger/messages/${mid}/reminder-suggest`),
  createReminder: (mid, when = '') =>
    api.post(`/web/messenger/messages/${mid}/reminder`, when ? { when } : {}),
  reminders: () => api.get('/web/messenger/reminders'),
  deleteReminder: (rid) => api.delete(`/web/messenger/reminders/${rid}`),
  // Кто прочитал конкретное сообщение (переиспользует last_read_at участников).
  readBy: (mid) => api.get(`/web/messenger/messages/${mid}/read_by`),
  // Личные шаблоны быстрых ответов преподавателя.
  templates: () => api.get('/web/messenger/templates'),
  createTemplate: (body) => api.post('/web/messenger/templates', { body }),
  deleteTemplate: (id) => api.delete(`/web/messenger/templates/${id}`),
  // §12: данные оверлея отчёта (круговая + плоские по предметам) и дрилл-даун по предмету.
  reportOverview: (id) => api.get(`/web/messenger/reports/${encodeURIComponent(id)}`),
  reportSubject: (id, subject) =>
    api.get(`/web/messenger/reports/${encodeURIComponent(id)}/subject`, { params: { subject } }),
}

// МОДЕРАЦИЯ МЕССЕНДЖЕРА (только админ) ─────────────────────────────────────────────
export const messengerModApi = {
  reports: (status = 'open') => api.get('/web/admin/messenger/reports', { params: { status } }),
  resolve: (id, status, note = '') =>
    api.post(`/web/admin/messenger/reports/${id}/resolve`, { status, resolution_note: note }),
  conversations: (q = '', kind = '') =>
    api.get('/web/admin/messenger/conversations', { params: { q, kind } }),
  conversationMessages: (id) =>
    api.get(`/web/admin/messenger/conversations/${encodeURIComponent(id)}/messages`),
  reply: (id, body) =>
    api.post(`/web/admin/messenger/conversations/${encodeURIComponent(id)}/reply`, { body }),
  // Глобальный мьют/размьют пользователя модерацией (не может писать никому).
  muteUser: (uid, muted = true) =>
    api.post(`/web/admin/messenger/users/${encodeURIComponent(uid)}/mute`, { muted }),
  // Удалить любое сообщение у всех (модерация; пишется в аудит).
  deleteMessage: (mid) => api.delete(`/web/admin/messenger/messages/${mid}`),
}

// Мероприятия/события (олимпиады, конкурсы и т.п.) — заводит преподаватель/админ,
// уходит уведомлением выбранной аудитории (вкладка «Мероприятия» в NotificationsInbox).
export const eventsApi = {
  create: (title, body, groups = []) => api.post('/web/events', { title, body, groups }),
}

// Десктоп-клиент (публичный эндпоинт: доступность и размер GradeBookAI.exe).
export const desktopApi = {
  info: () => api.get('/desktop-info'),
}
