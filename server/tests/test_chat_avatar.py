"""
test_chat_avatar.py — аватарка группы/канала (02.09.2026, просьба Влада «в группах всё
ещё нельзя менять и ставить аватарки»).

Проверяем ГРАНИЦЫ, а не «сохраняется ли»:
  • кто вправе менять лицо беседы (то же право, что у переименования);
  • у каких бесед аватарки нет и быть не должно (личный чат — там лицо задаёт собеседник);
  • что картинка проходит ТУ ЖЕ проверку источника, что аватарка профиля: она уедет в
    `<img src>` ко всем участникам, и чужая ссылка означала бы, что один человек включил
    слежку за всей группой;
  • что правка ОДНОГО поля не затирает соседние — сервер смотрит на присутствие ключа.

🔥 Здесь же регрессия на настоящий дефект, найденный по дороге: `about` сохранялся ТОЛЬКО
вместе с изменившимся `title`, то есть правка одного описания молча не доезжала.
"""
from conftest import make_admin, make_teacher

#Своя картинка в том же формате, что даёт AvatarCropper (data:URL, jpeg).
_PIC = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
_PIC2 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABBB=="


def _group(client, headers, title="Группа проекта"):
    r = client.post("/web/messenger/chats/group",
                    json={"title": title, "member_ids": []}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _info(client, conv, headers):
    r = client.get(f"/web/messenger/chats/{conv}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_owner_sets_group_avatar_and_it_reaches_both_places(client):
    """Картинка видна и в карточке беседы, и в списке чатов.

    ⚠️ Проверяем ОБА места намеренно: обновив одно, продукт показывал бы новую аватарку
    рядом со старой, и человек решил бы, что смена не сохранилась."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a)

    r = client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["avatar"] == _PIC

    assert _info(client, conv, a)["avatar"] == _PIC
    row = next(c for c in client.get("/web/messenger/chats", headers=a).json()["chats"]
               if c["conversation_id"] == conv)
    assert row["avatar"] == _PIC


def test_a_plain_member_cannot_change_the_face_of_the_conversation(client):
    """Право то же, что у переименования: аватарка — лицо беседы для ВСЕХ участников."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    b = make_teacher(client, admin, login="teacher2")
    conv = _group(client, a)
    assert client.post(f"/web/messenger/chats/{conv}/members",
                       json={"user_ids": ["teach:teacher2"]}, headers=a).status_code == 200

    r = client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=b)
    assert r.status_code == 403, r.text
    assert _info(client, conv, a)["avatar"] == ""


def test_a_direct_chat_has_no_picture_of_its_own(client):
    """У личного чата лицо задаёт собеседник. Своя картинка поверх означала бы, что
    человек выглядит по-разному у разных собеседников."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    b = make_teacher(client, admin, login="teacher2")
    conv = client.post("/web/messenger/chats/direct/teach:teacher2", headers=a).json()["conversation_id"]

    r = client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)
    assert r.status_code == 400, r.text


def test_a_foreign_image_url_is_refused_by_the_same_rule_as_the_profile(client):
    """🔒 Картинка уедет в `<img src>` ко всем участникам беседы. Чужая ссылка означала
    бы, что каждый открывший список чатов молча сходил на посторонний хост и отдал ему
    свой IP и User-Agent, — один человек включил бы слежку за всей группой.

    ⚠️ Непрошедшее значение ГАСИМ в пустоту, а не режем: обрезанная ссылка — это битая
    картинка, которая выглядит как поломка продукта."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a)

    r = client.patch(f"/web/messenger/chats/{conv}",
                     json={"avatar": "https://evil.example/track.png"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["avatar"] == ""
    assert _info(client, conv, a)["avatar"] == ""


def test_changing_only_the_picture_does_not_wipe_the_name(client):
    """Сервер смотрит на ПРИСУТСТВИЕ ключа, а не на непустоту (тот же приём, что у дня
    рождения). Иначе форма «сменить картинку» затирала бы название и описание."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a, title="Проект К74")
    assert client.patch(f"/web/messenger/chats/{conv}",
                        json={"title": "Проект К74", "about": "Сдаём в декабре"},
                        headers=a).status_code == 200

    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)
    info = _info(client, conv, a)
    assert info["title"] == "Проект К74"
    assert info["about"] == "Сдаём в декабре"
    assert info["avatar"] == _PIC


def test_description_alone_is_saved(client):
    """🔥 РЕГРЕССИЯ НА НАСТОЯЩИЙ ДЕФЕКТ (найден 02.09.2026). `about` присваивался ВНУТРИ
    `if title != conv.title`, поэтому правка одного описания молча не доезжала: ответ
    приходил `{"ok": true}`, форма закрывалась, а текст оставался прежним. Отказ тихий и
    правдоподобный — ровно тот класс, который ловится только чтением кода."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a, title="Проект К74")

    r = client.patch(f"/web/messenger/chats/{conv}",
                     json={"title": "Проект К74", "about": "Защита 12 декабря"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["about"] == "Защита 12 декабря"
    assert _info(client, conv, a)["about"] == "Защита 12 декабря"


def test_removing_the_picture_returns_the_conversation_to_initials(client):
    """Пустая строка — «убрать». Отдельной ручки удаления не заводим: это то же поле."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a)
    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)

    r = client.patch(f"/web/messenger/chats/{conv}", json={"avatar": ""}, headers=a)
    assert r.status_code == 200 and r.json()["avatar"] == ""


def test_the_system_note_carries_a_flag_and_never_the_picture_itself(client):
    """Тело системного сообщения хранится строкой и уезжает в предпросмотр списка чатов.
    Положи туда data:URL — и в списке чатов окажется сотня килобайт base64 вместо
    строчки «Аватарка беседы обновлена»."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a)
    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)

    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"]
    notes = [m for m in msgs if m["kind"] == "system" and m["body"].startswith("avatar_changed")]
    assert notes, "смена аватарки не оставила следа в ленте"
    assert _PIC not in notes[-1]["body"]


def test_the_same_picture_twice_does_not_spam_the_feed(client):
    """Повторное сохранение того же значения — не изменение. Иначе каждое открытие
    редактора и нажатие «Сохранить» добавляло бы строку в ленту."""
    admin = make_admin(client)
    a = make_teacher(client, admin)
    conv = _group(client, a)
    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)
    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC}, headers=a)
    client.patch(f"/web/messenger/chats/{conv}", json={"avatar": _PIC2}, headers=a)

    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"]
    notes = [m for m in msgs if m["kind"] == "system" and m["body"].startswith("avatar_changed")]
    assert len(notes) == 2, f"следов в ленте {len(notes)}, а смен было две"
