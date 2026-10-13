// useDeleteConfirm — окно удаления, которое называет последствия.
//
// Одна дверь на четыре раздела администратора (группы, предметы, студенты,
// преподаватели): у каждого была своя строка «Удалить …?» без единого слова о том, что
// за этим стоит. Числа считает сервер; не ответил — спрашиваем всё равно, но говорим,
// что посчитать не удалось: молчаливое окно без чисел выглядело бы как «удалять нечего».
//
//   const { confirmDelete } = useDeleteConfirm()
//   if (await confirmDelete({ kind: 'group', key: g.name, title: '…' })) { … }
import { useConfirm } from './useConfirm'
import { adminApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import { impactRows, needsTyping } from '@/utils/deleteImpact'

export function useDeleteConfirm() {
  const { confirm } = useConfirm()
  const loc = useLocaleStore()

  /** Подпись одного числа. Ключи записаны буквально — их сверяет тест словаря. */
  function rowText(kind, field, n) {
    const key = `${kind}.${field}`
    switch (key) {
      case 'group.students': return loc.t('deleteImpact.group.students', { n })
      case 'group.lessons': return loc.t('deleteImpact.group.lessons', { n })
      case 'group.marks': return loc.t('deleteImpact.group.marks', { n })
      case 'group.teachers': return loc.t('deleteImpact.group.teachers', { n })
      case 'subject.groups': return loc.t('deleteImpact.subject.groups', { n })
      case 'subject.lessons': return loc.t('deleteImpact.subject.lessons', { n })
      case 'subject.marks': return loc.t('deleteImpact.subject.marks', { n })
      case 'student.marks': return loc.t('deleteImpact.student.marks', { n })
      case 'student.finals': return loc.t('deleteImpact.student.finals', { n })
      case 'student.parents': return loc.t('deleteImpact.student.parents', { n })
      case 'teacher.subjects': return loc.t('deleteImpact.teacher.subjects', { n })
      case 'teacher.journals': return loc.t('deleteImpact.teacher.journals', { n })
      case 'teacher.curated': return loc.t('deleteImpact.teacher.curated', { n })
      default: return ''
    }
  }

  /** Что станет после удаления — словами, для каждого вида своими. */
  function effectText(kind) {
    if (kind === 'group') return loc.t('deleteImpact.group.effect', 'Группа пропадёт из журналов, расписания и списков.')
    if (kind === 'subject') return loc.t('deleteImpact.subject.effect', 'Предмет пропадёт из справочника.')
    if (kind === 'student') return loc.t('deleteImpact.student.effect', 'Студент не сможет войти и пропадёт из журналов.')
    if (kind === 'teacher') return loc.t('deleteImpact.teacher.effect', 'Преподаватель не сможет войти.')
    return ''
  }

  async function confirmDelete({ kind, key, title, okText }) {
    let counts = null
    try { counts = (await adminApi.deleteImpact(kind, key)).data?.counts || null } catch { counts = null }
    const lines = []
    if (counts) lines.push(...impactRows(kind, counts).map((r) => rowText(kind, r.field, r.n)))
    else lines.push(loc.t('deleteImpact.unknown', 'Посчитать, что затронет удаление, не удалось — проверьте сами, прежде чем продолжать.'))
    lines.push(effectText(kind))
    if (kind === 'group') lines.push(loc.t('deleteImpact.group.archiveTip', 'Если группа выпустилась, отправьте её в архив — там данные остаются видны.'))
    lines.push(loc.t('deleteImpact.final', 'Отменить удаление самостоятельно нельзя.'))
    return confirm({
      title,
      message: lines.filter(Boolean).join('\n'),
      okText: okText || loc.t('common.delete'),
      danger: true,
      requireText: needsTyping(kind, counts) ? key : '',
      requireLabel: loc.t('deleteImpact.typeToConfirm', { text: key }),
    })
  }

  return { confirmDelete }
}
