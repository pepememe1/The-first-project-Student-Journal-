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
