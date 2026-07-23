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
  subjects: (group, params = {}) =>
    api.get(`/web/curator/group/${encodeURIComponent(group)}/subjects`, { params }),
  groupSubject: (group, subject, params = {}) =>
    api.get(`/web/curator/group/${encodeURIComponent(group)}/subject/${encodeURIComponent(subject)}`, { params }),
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

// «ВЕКТОР» — серверный анти-галлюцинационный конвейер (intents→SQL→анонимизация→LLM)
export const vectorApi = {
  ask: (message) => api.post('/web/vector/ask', { message }),
}

// Десктоп-клиент (публичный эндпоинт: доступность и размер GradeBookAI.exe).
export const desktopApi = {
  info: () => api.get('/desktop-info'),
}
