"""
test_me_prefs.py — Личные настройки пользователя (POST/GET /me/prefs).

Проверяем, что:
  • пользователь сохраняет СВОИ prefs и видит их обратно;
  • prefs уезжают через обычный /sync/pull (чтобы тема «роумилась» между ПК);
  • слияние ключей prefs не теряет ранее сохранённые;
  • без авторизации эндпоинт закрыт (нельзя править чужой/анонимный профиль).
"""
from conftest import make_admin, make_teacher


def test_set_and_get_own_prefs(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"theme": {"id": "violet"}}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["theme"] == {"id": "violet"}

    r = client.get("/me/prefs", headers=teacher)
    assert r.status_code == 200
    assert r.json()["prefs"]["theme"] == {"id": "violet"}


def test_prefs_merge_keeps_existing(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={"theme": {"id": "blue"}}, headers=teacher)
    client.post("/me/prefs", json={"foo": "bar"}, headers=teacher)

    prefs = client.get("/me/prefs", headers=teacher).json()["prefs"]
    assert prefs["theme"] == {"id": "blue"}   #старый ключ не потерян
    assert prefs["foo"] == "bar"


def test_prefs_roam_via_pull(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={"theme": {"id": "amber"}}, headers=teacher)

    #Любой авторизованный pull отдаёт пользователей со столбцом prefs.
    data = client.get("/sync/pull", headers=admin).json()
    users = data["changes"]["users"]
    me = next(u for u in users if u["login"] == "teacher1")
    assert me["prefs"]["theme"] == {"id": "amber"}


def test_prefs_requires_auth(client):
    r = client.post("/me/prefs", json={"theme": {"id": "blue"}})
    assert r.status_code == 401


def test_name_font_accepts_known_value(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"name_font": "caveat"}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["name_font"] == "caveat"


def test_name_font_rejects_unknown_value(client):
    #Проверяем на сервере, не только в UI (§5.4 — публичное поле, другие видят его
    #в мессенджере и в карточке профиля).
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"name_font": "comicsans"}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["name_font"] == ""
def test_name_effect_accepts_known_and_rejects_unknown(client):
    #Эффект имени (3.7) — публичное поле, из которого КЛИЕНТ склеивает имя CSS-класса
    #(.gb-nfx-<id>), поэтому произвольная строка сюда попадать не должна ровно по той же
    #причине, что и у шрифта: подделанный запрос идёт мимо UI.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"name_effect": "rainbow"}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["name_effect"] == "rainbow"

    r = client.post("/me/prefs", json={"name_effect": "drop-shadow: url(evil)"}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["name_effect"] == ""


def test_name_color_is_trimmed_like_profile_color(client):
    #Цвет имени — id пресета палитры, как profile_color: списка из 16 названий на сервере
    #НЕТ намеренно (второй источник правды разъехался бы с палитрой клиента), поэтому
    #проверяем то же, что и там, — что длинная строка не уедет в БД целиком.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"name_color": "violet"}, headers=teacher)
    assert r.json()["prefs"]["name_color"] == "violet"

    r = client.post("/me/prefs", json={"name_color": "x" * 500}, headers=teacher)
    assert r.status_code == 200, r.text
    assert len(r.json()["prefs"]["name_color"]) <= 32


def test_new_nickname_fonts_are_accepted(client):
    #Список шрифтов вырос в 3.7 с семи до девятнадцати. Тест держит СВЯЗЬ трёх мест:
    #сервер (NAME_FONTS здесь), web/src/config/nameFonts.js и @font-face в style.css —
    #id, принятый сервером, но забытый в двух других, дал бы «стиль сохранился, а имя
    #выглядит как обычно», и заметить это можно было бы только глазами.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    for font_id in ("russo", "pixel", "glitch", "wetpaint", "oswald", "pacifico"):
        r = client.post("/me/prefs", json={"name_font": font_id}, headers=teacher)
        assert r.status_code == 200, r.text
        assert r.json()["prefs"]["name_font"] == font_id, font_id


# ── Медиа профиля: аватарка (картинка ИЛИ гифка) и гифка-баннер ─────────────────────
#
# 🔒 До 3.7 поле `avatar` не проверялось на сервере ВООБЩЕ — годилась любая строка.
# Пока туда клала значение только наша же обрезалка, вреда не было; с появлением
# гифок поле стало принимать ссылки, и без белого списка один человек мог бы поставить
# себе «аватаркой» картинку с постороннего хоста — тогда КАЖДЫЙ, кто откроет список
# чатов, молча сходил бы туда и отдал свой IP. На бою это ловил CSP, но CSP — заслонка
# браузера: внутри программы страницу отдаёт локальный сервер, и её там нет.

KLIPY = "https://static.klipy.com/gif/abc123/md.gif"
FOREIGN = "https://evil.example.com/track.gif"
TINY_IMAGE = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_avatar_accepts_own_picture_and_klipy_gif(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"avatar": TINY_IMAGE}, headers=teacher)
    assert r.json()["prefs"]["avatar"] == TINY_IMAGE

    r = client.post("/me/prefs", json={"avatar": KLIPY}, headers=teacher)
    assert r.json()["prefs"]["avatar"] == KLIPY


def test_avatar_from_a_foreign_host_is_dropped(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"avatar": FOREIGN}, headers=teacher)
    assert r.status_code == 200, r.text
    #Гасим в пустоту, а не сохраняем и не режем: пустое поле честно показывает буквы
    #имени, а обрезанная ссылка выглядела бы как поломка продукта.
    assert r.json()["prefs"]["avatar"] == ""


def test_avatar_rejects_non_image_data_url(client):
    #`data:` — не синоним «картинки»: data:text/html внутри <img> безвреден, но поле
    #публичное, и пускать в него произвольный тип содержимого незачем.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"avatar": "data:text/html,<b>hi</b>"}, headers=teacher)
    assert r.json()["prefs"]["avatar"] == ""


def test_banner_takes_klipy_gif_but_not_a_data_url(client):
    #Баннеру своя картинка не разрешена НАМЕРЕННО: интерфейса для неё нет ни на одной
    #платформе, а полоса во всю ширину карточки съела бы лимит настроек целиком.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"profile_banner": KLIPY}, headers=teacher)
    assert r.json()["prefs"]["profile_banner"] == KLIPY

    r = client.post("/me/prefs", json={"profile_banner": TINY_IMAGE}, headers=teacher)
    assert r.json()["prefs"]["profile_banner"] == ""

    r = client.post("/me/prefs", json={"profile_banner": FOREIGN}, headers=teacher)
    assert r.json()["prefs"]["profile_banner"] == ""


def test_banner_can_be_removed_by_empty_string(client):
    #«Убрать баннер» — обычное сохранение пустой строки, отдельного эндпоинта нет.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={"profile_banner": KLIPY}, headers=teacher)
    r = client.post("/me/prefs", json={"profile_banner": ""}, headers=teacher)
    assert r.json()["prefs"]["profile_banner"] == ""


def test_a_photo_sized_avatar_actually_saves(client):
    """🔥 Регрессия на настоящий баг: лимит настроек был 16 КБ, а аватарка-ФОТОГРАФИЯ
    (256×256 JPEG q0.85, как её отдаёт обрезалка) весит в data:URL около 14.5 КБ.

    Вместе с «О себе», настройками уведомлений и избранными гифками сумма переваливала
    за лимит, и сервер отвечал 413. Со стороны это выглядело беспричинно: однотонная
    картинка (2 КБ) сохранялась, фотография — нет. Клиент к тому же ошибку глотал, то
    есть аватарка менялась на экране и пропадала после перезахода."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={
        "bio": "к" * 400,
        "gif_favorites": [{"slug": f"g{i}", "title": "t", "url": KLIPY,
                           "thumb_url": KLIPY, "width": 1, "height": 1} for i in range(10)],
    }, headers=teacher)

    photo = "data:image/jpeg;base64," + ("A" * 14_500)
    r = client.post("/me/prefs", json={"avatar": photo}, headers=teacher)
    assert r.status_code == 200, r.text
    assert client.get("/me/prefs", headers=teacher).json()["prefs"]["avatar"] == photo


def test_prefs_still_have_an_upper_bound(client):
    #Лимит подняли, но не убрали: без него авторизованный пользователь раздувает свою
    #строку в БД произвольным JSON, и это уезжает каждому синку.
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"junk": "x" * (200 * 1024)}, headers=teacher)
    assert r.status_code == 413
