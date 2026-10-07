// stores/tracker.js — трекер задач беседы: серверное состояние, рабочая копия и пачка правок.
//
// 🔑 ГЛАВНОЕ ПРАВИЛО: НИ ОДНА ПРАВКА НЕ УХОДИТ НА СЕРВЕР, ПОКА ЧЕЛОВЕК НЕ НАЖАЛ «СОХРАНИТЬ»
// (требование Ярослава 05.10.2026: «чтобы уведомления из трекера не спамили, если кучу
// задач делят на кучу людей, — сделать кнопку сохранить, при нажатии на которую сохранятся
// все действия и придут уведомления тем, кого назначили»). Поэтому состояний два:
//   • `server` — то, что отдал сервер;
//   • `draft`  — рабочая копия, которую видит человек: `server` + несохранённые `ops`.
// Любое действие интерфейса — это операция: она применяется к `draft` и встаёт в `ops`.
// «Сохранить» отправляет сжатую пачку ОДНИМ запросом; сервер применяет её одной
// транзакцией и шлёт каждому назначенному одно письмо.
//
// ⚠️ У стора НЕТ действий, которые пишут на сервер мимо `save()` (кроме настроек самого
// трекера — их меняет владелец, и это не правка задач). Появись такое — правило «одно
// письмо на сохранение» перестало бы действовать именно на этом действии; держит
// `web/tests/trackerStore.test.mjs`.
import { defineStore } from 'pinia'
import { messengerApi } from '@/api/endpoints'
import { isStaleSession } from '@/api/responseOwner'
import { applyOp, cloneState, compactOps, rebase } from '@/utils/tracker'

const emptyFilter = () => ({ q: '', assignee: '', priority: '', kind: '', label: '', status: '' })

export const useTrackerStore = defineStore('tracker', {
  state: () => ({
    open: false,
    convId: '',
    loading: false,
    error: '',
    server: null,
    draft: null,
    ops: [],
    saving: false,
    //Что сервер НЕ применил при последнем сохранении: [{op, reason}] — показываем человеку,
    //а не глотаем: «сохранено» при пропущенной половине пачки было бы неправдой.
    skipped: [],
    notified: 0,
    savedAt: 0,
    projectId: '',
    view: 'board',                  // board | list | timeline | summary
    filter: emptyFilter(),
    taskId: '',                     // открытая задача ('' — окно задачи закрыто)
    //Пока есть несохранённое, с сервера пришло чужое изменение. Рабочую копию мы
    //переложили на свежее состояние, но человеку стоит об этом знать.
    remoteChanged: false,
    //Поколение серверного состояния. Ответ на загрузку, начатую ДО более свежего события
    //(другой загрузки или сохранения), принимать нельзя: он старше того, что уже на экране.
    //Без этого опрос, ушедший за миг до «Сохранить», возвращался после него и откатывал
    //доску к состоянию до сохранения — только что назначенные задачи пропадали с экрана.
    seq: 0,
  }),

  getters: {
    dirty: (s) => s.ops.length > 0,
    enabled: (s) => !!s.draft?.enabled,
    canManage: (s) => !!s.draft?.can_manage,
    canConfigure: (s) => !!s.draft?.can_configure,
    me: (s) => s.draft?.me || '',
    members: (s) => s.draft?.members || [],
    memberById() { return Object.fromEntries(this.members.map((m) => [m.user_id, m])) },
    //Архивные работы в переключателе не показываем — их открывают из списка работ.
    projects: (s) => (s.draft?.projects || []).filter((p) => !p.archived),
    archivedProjects: (s) => (s.draft?.projects || []).filter((p) => p.archived),
    project(s) {
      const all = s.draft?.projects || []
      return all.find((p) => p.id === s.projectId) || this.projects[0] || null
    },
    columns() {
      return [...(this.project?.columns || [])].sort((a, b) => a.position - b.position)
    },
    tasks(s) {
      const pid = this.project?.id
      return pid ? (s.draft?.tasks || []).filter((t) => t.project_id === pid) : []
    },
    task: (s) => (s.draft?.tasks || []).find((t) => t.id === s.taskId) || null,
    filterActive: (s) => Object.values(s.filter).some((v) => !!v),
  },

  actions: {
    _ctx() { return { me: this.me, now: new Date().toISOString() } },

    /** Открыть трекер беседы. `taskId` — сразу показать задачу (ссылка из письма). */
    async openFor(convId, { projectId = '', taskId = '' } = {}) {
      if (this.convId !== convId) {
        //Другая беседа — другая пачка. Несохранённое прежней беседы здесь не выживает:
        //спросить «сохранить?» обязан тот, кто закрывает окно (см. `TrackerOverlay`).
        this.$patch({ server: null, draft: null, ops: [], skipped: [], projectId: '', taskId: '', filter: emptyFilter(), view: 'board', remoteChanged: false })
      }
      this.convId = convId
      this.open = true
      await this.load()
      if (projectId && (this.draft?.projects || []).some((p) => p.id === projectId)) this.projectId = projectId
      if (taskId) {
        const t = (this.draft?.tasks || []).find((x) => x.id === taskId)
        //Задачу из ссылки успели удалить — окно задачи не открываем и ПРЕЖНЕЕ не оставляем:
        //человек шёл к другой задаче, и чужая на её месте читалась бы как «вот она».
        if (t) { this.projectId = t.project_id; this.taskId = taskId } else this.taskId = ''
      }
    },

    close() {
      this.open = false
      this.taskId = ''
    },

    /** Забрать состояние с сервера. Несохранённые правки перекладываются поверх. */
    async load({ silent = false } = {}) {
      const convId = this.convId
      if (!convId) return
      if (!silent) { this.loading = true; this.error = '' }
      const seq = ++this.seq
      try {
        const { data } = await messengerApi.tracker(convId)
        if (this.convId !== convId) return            //пока ждали, открыли другую беседу
        if (seq !== this.seq) return                  //пока ждали, пришло более свежее
        this._adopt(data)
      } catch (e) {
        if (isStaleSession(e)) return                 //ответ прежней сессии — не наш
        if (!silent) this.error = e?.response?.data?.detail || 'load-failed'
      } finally {
        if (!silent) this.loading = false
      }
    },

    _adopt(serverState) {
      const hadDraft = !!this.draft
      const before = this.server ? JSON.stringify(this.server.tasks) + JSON.stringify(this.server.projects) : ''
      this.server = serverState
      this.draft = this.ops.length ? rebase(serverState, this.ops, this._ctx()) : cloneState(serverState)
      if (hadDraft && this.ops.length
          && before !== JSON.stringify(serverState.tasks) + JSON.stringify(serverState.projects)) {
        this.remoteChanged = true
      }
      const visible = this.projects
      if (!visible.some((p) => p.id === this.projectId)
          && !(this.draft.projects || []).some((p) => p.id === this.projectId)) {
        this.projectId = visible[0]?.id || ''
      }
      if (this.taskId && !this.draft.tasks.some((t) => t.id === this.taskId)) this.taskId = ''
    },

    /** Сигнал сокета «в трекере этой беседы что-то поменяли» — подтянуть свежее. */
    onRemoteChange(convId) {
      if (!this.open || convId !== this.convId || this.saving) return
      this.load({ silent: true })
    },

    /** Положить действие в пачку: применить к рабочей копии и запомнить. */
    stage(opOrOps) {
      if (!this.draft) return
      const list = Array.isArray(opOrOps) ? opOrOps : [opOrOps]
      const ctx = this._ctx()
      for (const op of list) {
        if (!op || !op.op) continue
        applyOp(this.draft, op, ctx)
        this.ops.push(op)
      }
    },

    /** Отправить пачку. Возвращает true, если сервер её принял. */
    async save() {
      if (!this.ops.length || this.saving) return false
      const convId = this.convId
      const sent = this.ops.slice()
      const batch = compactOps(sent)
      this.saving = true
      this.error = ''
      try {
        const { data } = await messengerApi.trackerSave(convId, batch)
        if (this.convId !== convId) return false
        //Пока запрос шёл, человек мог успеть ещё что-то поправить — эти операции
        //остаются в пачке и перекладываются на свежее состояние.
        this.ops = this.ops.slice(sent.length)
        this.skipped = (data.skipped || []).map((s) => ({ ...s, source: batch[s.i] || null }))
        this.notified = data.notified || 0
        this.savedAt = Date.now()
        this.remoteChanged = false
        this.seq += 1                                 //загрузки, начатые раньше, устарели
        this._adopt(data.state)
        return true
      } catch (e) {
        if (isStaleSession(e)) return false
        //⚠️ Пачка ОСТАЁТСЯ: отказ сервера (нет связи, заглушён в беседе, частые
        //сохранения) не должен стирать минуты работы. Причину показываем как есть.
        const detail = e?.response?.data?.detail
        this.error = (typeof detail === 'string' ? detail : detail?.message) || 'save-failed'
        return false
      } finally {
        this.saving = false
      }
    },

    /** Выбросить несохранённое и вернуться к тому, что на сервере. */
    discard() {
      this.ops = []
      this.skipped = []
      this.remoteChanged = false
      this.error = ''
      if (this.server) this._adopt(this.server)
    },

    /** Настройки трекера (включить, выключить, кто ведёт задачи) — только владелец. */
    async setSettings(payload, convId = this.convId) {
      const { data } = await messengerApi.trackerSettings(convId, payload)
      if (convId === this.convId) { this.seq += 1; this._adopt(data) }
      return data
    },

    resetFilter() { this.filter = emptyFilter() },

    /** Выход из аккаунта: устройство меняет владельца, чужая доска в памяти не остаётся. */
    reset() {
      this.$reset()
    },
  },
})
