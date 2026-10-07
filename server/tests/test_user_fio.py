"""
test_user_fio.py — ФИО человека собирается ОДНОЙ функцией, и студент виден с фамилией.

Жалоба Ярослава (05.10.2026): «серьёзный баг со студентами: видно лишь отчество и имя, а
фамилию нет; если отчество не указано — видно лишь имя, из-за чего непонятно, что за
юзер».

🔥 ПРИЧИНА. Подпись человека собиралась выражением `full_name or name` — в тридцати трёх
местах (мессенджер, активности, родительский раздел, письма). У студента, заведённого
администратором, `full_name` пуст (`admin_create_student` пишет туда пустую строку), а
`name` — это «Имя Отчество», исторический ключ оценок. У заведённых по заявке или
приглашению `full_name` заполнен, поэтому дефект жил ровно у тех, кого завели руками, —
то есть у большинства, — и не был виден ни на стенде, ни в тестах: фикстуры всегда
задавали `full_name`.

Проверяем три вещи:
  1. саму функцию — на раскладках полей, которые реально лежат в базе;
  2. живой путь: студент, заведённый админом, виден в мессенджере с фамилией;
  3. СВОЙСТВО: выражения `X.full_name or X.name` в `server/app` больше нет нигде, кроме
     самой функции. Перечислить 33 места тестами нельзя — тридцать четвёртое появится
     раньше, чем о нём вспомнят.

⚠️ Обратный ход проверен: вернуть в `models.user_fio` прежнее `full or name` — краснеют
`test_admin_created_student_has_surname` и два теста мессенджера ниже.
"""
import os
import re
from types import SimpleNamespace as NS

from conftest import make_admin, make_teacher
from app.models import user_fio

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


# ── 1. Функция ───────────────────────────────────────────────────────────────────────

def test_admin_created_student_has_surname():
    """Тот самый случай: full_name пуст, name = «Имя Отчество»."""
    u = NS(full_name="", surname="Иванов", name="Пётр Сергеевич", patronymic="Сергеевич")
    assert user_fio(u) == "Иванов Пётр Сергеевич"


def test_student_without_patronymic_still_has_surname():
    """Вторая половина жалобы: «если отчество не указано — видно лишь имя»."""
    u = NS(full_name="", surname="Иванов", name="Пётр", patronymic="")
    assert user_fio(u) == "Иванов Пётр"


def test_patronymic_from_its_own_field_is_appended_once():
    """Строки со старого десктопа: отчество только в своём поле, в name его нет."""
    u = NS(full_name="", surname="Иванов", name="Пётр", patronymic="Сергеевич")
    assert user_fio(u) == "Иванов Пётр Сергеевич"
    #…а когда оно уже в name — второй раз не дописывается.
    u2 = NS(full_name="", surname="Иванов", name="Пётр Сергеевич", patronymic="Сергеевич")
    assert user_fio(u2).count("Сергеевич") == 1


def test_teacher_keyed_by_full_name_is_untouched():
    """У преподавателя ключ — full_name, фамилии отдельным полем может не быть вовсе."""
    u = NS(full_name="Семёнова Анна Петровна", surname="", name="", patronymic="")
    assert user_fio(u) == "Семёнова Анна Петровна"


def test_stale_full_name_does_not_override_current_fields():
    """Студентке сменили фамилию: поля обновлены, full_name остался прежним. Показать
    старую фамилию значило бы вернуть в переписку имя, которого у человека уже нет."""
    u = NS(full_name="Петрова Анна Игоревна", surname="Сидорова", name="Анна Игоревна",
           patronymic="Игоревна")
    assert user_fio(u) == "Сидорова Анна Игоревна"


def test_fuller_full_name_wins():
    """Поля беднее полного имени (name пуст) — тогда верим full_name."""
    u = NS(full_name="Орлов Игорь Васильевич", surname="Орлов", name="", patronymic="")
    assert user_fio(u) == "Орлов Игорь Васильевич"


def test_compound_patronymic_is_not_doubled():
    """🔥 Нашёл Полковник (06.10.2026). Заявка и приглашение пишут `name` = всё после
    фамилии, `patronymic` = всё после имени (`reg_utils`): у «Мамедова Али Вели оглы» это
    «Али Вели оглы» и «Вели оглы». Первая версия искала отчество среди ОТДЕЛЬНЫХ слов
    `name`, не находила и дописывала второй раз — «…Вели оглы Вели оглы»."""
    u = NS(full_name="Мамедов Али Вели оглы", surname="Мамедов", name="Али Вели оглы",
           patronymic="Вели оглы")
    assert user_fio(u) == "Мамедов Али Вели оглы"
    u2 = NS(full_name="", surname="Алиева", name="Лейла Рашид кызы", patronymic="Рашид кызы")
    assert user_fio(u2) == "Алиева Лейла Рашид кызы"
    #Обратная сторона: слова отчества есть в `name`, но НЕ подряд — это не оно.
    u3 = NS(full_name="", surname="Иванов", name="Оглы Вели", patronymic="Вели оглы")
    assert user_fio(u3) == "Иванов Оглы Вели Вели оглы"


def test_yo_and_ye_are_the_same_patronymic():
    u = NS(full_name="", surname="Иванов", name="Пётр Семенович", patronymic="Семёнович")
    assert user_fio(u) == "Иванов Пётр Семенович"
    u2 = NS(full_name="", surname="Иванов", name="Петр Семёнович", patronymic="СЕМЕНОВИЧ")
    assert user_fio(u2) == "Иванов Петр Семёнович"


def test_longer_but_stale_full_name_does_not_return_the_old_surname():
    """Смена фамилии правит `surname`, а `full_name` правка студента не трогает. Прежний
    `full_name` мог быть ДЛИННЕЕ собранного (в нём отчество, а в полях его нет) и
    побеждал по числу слов — человек показывался под девичьей фамилией."""
    u = NS(full_name="Петрова Анна Ивановна", surname="Сидорова", name="Анна", patronymic="")
    assert user_fio(u) == "Сидорова Анна"
    #А полный `full_name` С ТОЙ ЖЕ фамилией по-прежнему побеждает (в т.ч. «ё/е»).
    u2 = NS(full_name="Семёнова Анна Петровна", surname="Семенова", name="Анна", patronymic="")
    assert user_fio(u2) == "Семёнова Анна Петровна"


def test_stale_full_name_does_not_survive_a_corrected_patronymic():
    """🔥 Нашёл Полковник вторым проходом (07.10.2026). Правка студента меняет имя и
    отчество, а `full_name` не трогает. Правило «`full_name` длиннее и с той же фамилией»
    возвращало ПРЕЖНЕЕ отчество: исправили «Вели оглы» на «Велиевич» — человек по-прежнему
    показывался по-старому. Побеждать `full_name` вправе, только продолжая собранное."""
    u = NS(full_name="Мамедов Али Вели оглы", surname="Мамедов", name="Али Велиевич",
           patronymic="Велиевич")
    assert user_fio(u) == "Мамедов Али Велиевич"
    #Отчество убрали вовсе, имя исправили — прежние слова не возвращаются.
    u2 = NS(full_name="Иванова Мария Петровна", surname="Иванова", name="Марина", patronymic="")
    assert user_fio(u2) == "Иванова Марина"
    #А продолжение собранного по-прежнему побеждает: в полях отчества нет, в `full_name` есть.
    u3 = NS(full_name="Иванова Марина Петровна", surname="Иванова", name="Марина", patronymic="")
    assert user_fio(u3) == "Иванова Марина Петровна"


def test_nameless_user_gives_empty_string_not_crash():
    assert user_fio(NS(full_name="", surname="", name="", patronymic="")) == ""
    assert user_fio(NS()) == ""          #объект без полей вовсе (заглушка в тестах)


# ── 2. Живой путь: мессенджер ────────────────────────────────────────────────────────

def _admin_student(client, admin, login, surname, name, patronymic="", group="К-24"):
    """Студент заводится РУЧКОЙ АДМИНКИ — так же, как их заводят в колледже. Через
    `/sync/push` с готовым full_name (как в соседних файлах) дефект не воспроизводится."""
    r = client.post("/web/admin/students", headers=admin, json={
        "surname": surname, "name": name, "patronymic": patronymic,
        "login": login, "group": group, "password": "studpass1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return f"stud:{login}", {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_messenger_directory_shows_student_with_surname(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="tfio")
    _admin_student(client, admin, "fio_a", "Цыренов", "Баир", "Доржиевич")
    r = client.get("/web/messenger/users", params={"q": "Цыренов"}, headers=teacher)
    assert r.status_code == 200, r.text
    names = [u["full_name"] for u in r.json().get("users", r.json().get("items", []))]
    assert "Цыренов Баир Доржиевич" in names, (
        f"студент, заведённый админом, виден без фамилии или не находится по ней: {names}")


def test_group_chat_member_and_sender_have_surname(client):
    """Участник группы и автор сообщения подписаны полным ФИО; группа — в `group_name`
    (её клиент рисует тегом справа от имени)."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="tfio2")
    sid, student = _admin_student(client, admin, "fio_b", "Дашиева", "Арюна", "", "К74/1")
    r = client.post("/web/messenger/chats/group", headers=teacher,
                    json={"title": "Проект", "member_ids": [sid]})
    assert r.status_code == 200, r.text
    conv = r.json()["conversation_id"]

    info = client.get(f"/web/messenger/chats/{conv}", headers=teacher).json()
    me = next(p for p in info["participants"] if p["user_id"] == sid)
    assert me["full_name"] == "Дашиева Арюна"
    assert me["group_name"] == "К74/1"

    r = client.post(f"/web/messenger/chats/{conv}/messages", headers=student,
                    json={"body": "привет"})
    assert r.status_code == 200, r.text
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=teacher).json()
    mine = [m for m in msgs.get("messages", msgs.get("items", [])) if m.get("sender_id") == sid]
    assert mine and mine[-1]["sender_name"] == "Дашиева Арюна"


# ── 3. Свойство: второй копии сборки имени нет ───────────────────────────────────────

_PATTERN = re.compile(r"\b(\w+)\.full_name or \1\.name\b")


def _offenders(root=APP):
    found = []
    for dp, _dn, files in os.walk(root):
        if "__pycache__" in dp:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dp, fn)
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if _PATTERN.search(line):
                        found.append(f"{os.path.relpath(path, root)}:{i}")
    return found


def test_no_second_copy_of_display_name_rule():
    """`X.full_name or X.name` — это и есть дефект: у студента без full_name оно даёт
    «Имя Отчество». Сборка имени живёт в `models.user_fio`, и только там."""
    assert _offenders() == [], (
        "подпись человека снова собирается мимо models.user_fio — студент, заведённый "
        f"админом, будет виден без фамилии: {_offenders()}")


def test_the_property_check_can_fail(tmp_path):
    """Обратный ход сторожа: на дословной строке дефекта он обязан покраснеть."""
    bad = tmp_path / "bad.py"
    bad.write_text('name = u.full_name or u.name or u.login\n', encoding="utf-8")
    assert _offenders(str(tmp_path)) == ["bad.py:1"]
    ok = tmp_path / "ok.py"
    ok.write_text('name = user_fio(u) or u.login\n', encoding="utf-8")
    bad.unlink()
    assert _offenders(str(tmp_path)) == []
