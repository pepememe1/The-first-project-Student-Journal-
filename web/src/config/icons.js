// Словарь значков: одно действие — один значок на сайте, в программе и в телефоне.
//
// Интерфейс один на три платформы, а визуальная память держится на том, что «удалить»
// везде корзина, а «назад» везде один и тот же шеврон. До 27.10.2026 «обновить» рисовали
// двумя разными значками, «назад» — стрелкой и шевроном, а часть кнопок — эмодзи,
// которые каждая система рисует по-своему (флаги языков на Windows выходили буквами).
// Новое место берёт значок отсюда по смыслу: <GbIcon name="delete" class="size-4" />.
// Синонимы из FORBIDDEN_SYNONYMS держит под запретом web/tests/iconSystem.test.mjs.
import {
  Ban, BadgeCheck, BookOpen, Cake, ClipboardCheck, FileDown, CalendarDays, ChartColumn, Check, ChevronLeft,
  ChevronRight, CircleArrowUp, CircleCheck, CircleHelp, CircleX, Clock, Copy, Download,
  EllipsisVertical, Eraser, Eye, EyeOff, FileSpreadsheet, FileText, Globe, GraduationCap,
  Hourglass, Info, Keyboard, KeyRound, Lightbulb, Link, LoaderCircle, Lock, Mail, MailCheck, Menu,
  Mic, MoveHorizontal, OctagonAlert, Paperclip, PartyPopper, Pencil, PenLine, Pin, Plus,
  RotateCw, School, Search, Send, Settings, Star, Trash2, TriangleAlert, Trophy, Upload,
  UserPlus, UserSearch, Users, VolumeX, X,
} from '@lucide/vue'
import { HoneyPot, VectorHead } from '../components/icons/brandIcons.js'

export const ICONS = Object.freeze({
  // действия
  close: X,
  remove: X,
  cancel: X,
  back: ChevronLeft,
  forward: ChevronRight,
  edit: Pencil,
  delete: Trash2,
  save: Check,
  confirm: Check,
  add: Plus,
  search: Search,
  refresh: RotateCw,
  settings: Settings,
  send: Send,
  download: Download,
  upload: Upload,
  copy: Copy,
  more: EllipsisVertical,
  menu: Menu,
  show: Eye,
  hide: EyeOff,
  link: Link,
  invite: UserPlus,
  mail: Mail,
  mailSent: MailCheck,
  key: KeyRound,
  clear: Eraser,
  promote: CircleArrowUp,
  // состояния
  ok: CircleCheck,
  fail: CircleX,
  warn: TriangleAlert,
  alert: OctagonAlert,
  info: Info,
  help: CircleHelp,
  pending: Hourglass,
  loading: LoaderCircle,
  locked: Lock,
  blocked: Ban,
  silenced: VolumeX,
  verified: BadgeCheck,
  // предметная область
  risk: GraduationCap,
  attestation: ClipboardCheck,
  importPlan: FileDown,
  hours: Clock,
  calendar: CalendarDays,
  group: Users,
  findTeacher: UserSearch,
  school: School,
  globe: Globe,
  journal: BookOpen,
  excel: FileSpreadsheet,
  word: FileText,
  document: FileText,
  report: ChartColumn,
  tip: Lightbulb,
  trophy: Trophy,
  celebrate: PartyPopper,
  birthday: Cake,
  star: Star,
  pin: Pin,
  attachment: Paperclip,
  board: PenLine,
  mic: Mic,
  keyboard: Keyboard,
  scrollX: MoveHorizontal,
  // свои, нарисованные по сетке lucide
  vector: VectorHead,
  honeypot: HoneyPot,
})

// Значки lucide, которые рисуют уже занятое действие иначе (или старые имена того же
// значка). Новое место их не импортирует, а берёт значок из ICONS по смыслу.
export const FORBIDDEN_SYNONYMS = Object.freeze({
  RefreshCw: 'refresh',
  RefreshCcw: 'refresh',
  AlertTriangle: 'warn',
  Loader: 'loading',
  Loader2: 'loading',
  CheckCircle: 'ok',
  CheckCircle2: 'ok',
  XCircle: 'fail',
  HelpCircle: 'help',
  MoreHorizontal: 'more',
  MoreVertical: 'more',
  Ellipsis: 'more',
  Edit: 'edit',
  Edit2: 'edit',
  Edit3: 'edit',
  Trash: 'delete',
})
