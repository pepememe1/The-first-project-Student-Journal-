// people.js — мелкие правила про человека в списках, общие для всего мессенджера.

/**
 * Учебная группа, если перед нами СТУДЕНТ; иначе пустая строка.
 *
 * ⚠️ У человека в наших ответах ДВА поля с именем «роль», и путать их нельзя:
 *   • карточка человека (`_safe_user`: каталог, собеседник в личном чате) несёт СИСТЕМНУЮ
 *     роль в `role` — student / teacher / admin / parent;
 *   • участник беседы (`conversation_info.participants`) несёт в `role` роль В БЕСЕДЕ —
 *     owner / admin / member / reader, а системную — отдельным `user_role`.
 * Спроси у участника беседы `role === 'student'` — и тег группы не появится ни у кого:
 * «student» там не бывает. Поэтому сначала смотрим `user_role`, и только при его
 * отсутствии — `role`.
 *
 * Группу показываем только студенту: у преподавателя `group_name` пуст, а у родителя
 * «его группа» — это группа ребёнка, и рисовать её тегом значило бы выдать родителя за
 * учащегося.
 */
export function studentGroup(person) {
  if (!person) return ''
  const systemRole = person.user_role || person.role || ''
  if (systemRole !== 'student') return ''
  return String(person.group_name || '').trim()
}
