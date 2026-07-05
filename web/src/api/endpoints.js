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
}

// ЛИЧНЫЕ НАСТРОЙКИ (тема и пр.) ──────────────────────────────────────────────────
export const meApi = {
  getPrefs: () => api.get('/me/prefs'),
  setPrefs: (prefs) => api.post('/me/prefs', { prefs }),
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
  journal: () => api.get('/web/student/journal'),
  stats: () => api.get('/web/student/stats'),
}

// ПРЕПОДАВАТЕЛЬ ───────────────────────────────────────────────────────────────────
export const teacherApi = {
  overview: () => api.get('/web/teacher/overview'),
  journal: (group, subject) => api.get('/web/teacher/journal', { params: { group, subject } }),
  students: (group) => api.get('/web/teacher/students', { params: { group } }),
  stats: (group, subject) => api.get('/web/teacher/stats', { params: { group, subject } }),
  // Запись оценки (Phase B). Пустой grade = снять оценку. Сервер ставит метку LWW.
  setGrade: (surname, name, lesson_id, grade) =>
    api.post('/web/teacher/grade', { surname, name, lesson_id, grade }),
  // Занятия/пары (Phase B): наполнение журнала. id = uuid на сервере.
  createLesson: (payload) => api.post('/web/teacher/lesson', payload),
  updateLesson: (id, payload) => api.put(`/web/teacher/lesson/${encodeURIComponent(id)}`, payload),
  deleteLesson: (id) => api.delete(`/web/teacher/lesson/${encodeURIComponent(id)}`),
  // Экспорт журнала в xlsx (тот же стиль, что в десктопе: Times New Roman 14).
  journalXlsx: (group, subject) =>
    api.get('/web/teacher/journal.xlsx', { params: { group, subject }, responseType: 'blob' }),
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
  createSubject: (name) => api.post('/web/admin/subjects', { name }),
  deleteSubject: (name) => api.delete(`/web/admin/subjects/${encodeURIComponent(name)}`),
  // CRUD преподавателей (Phase B). id на сервере = teach:login.
  createTeacher: (payload) => api.post('/web/admin/teachers', payload),
  updateTeacher: (login, payload) => api.put(`/web/admin/teachers/${encodeURIComponent(login)}`, payload),
  deleteTeacher: (login) => api.delete(`/web/admin/teachers/${encodeURIComponent(login)}`),
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
}

// «ВЕКТОР» — серверный анти-галлюцинационный конвейер (intents→SQL→анонимизация→LLM)
export const vectorApi = {
  ask: (message) => api.post('/web/vector/ask', { message }),
}

// Десктоп-клиент (публичный эндпоинт: доступность и размер GradeBookAI.exe).
export const desktopApi = {
  info: () => api.get('/desktop-info'),
}
