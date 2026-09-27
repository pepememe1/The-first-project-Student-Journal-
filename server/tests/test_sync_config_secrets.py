"""
test_sync_config_secrets.py — ключ ИИ не покидает сервер через `/sync/pull` (26.09.2026).

━━ ЧТО БЫЛО ━━
Фильтр секретов смотрел только на ИМЯ строки `config`, а настройки ИИ сайт кладёт ВНУТРЬ
строки `config` — словарём с `gigachat_credentials` (`POST /web/admin/ai-config`). Рабочий
ключ к платному внешнему сервису уезжал каждому преподавателю и студенту, на все ПК
колледжа, при докстринге, обещавшем обратное. Сторож засевал ключ отдельной строкой — не
так, как его сохраняет продукт, — и был зелёным рядом с утечкой.

Следствие, которое пришлось закрыть вместе с утечкой: локальный Вектор программы звонил в
GigaChat этим утёкшим ключом. Теперь он просит переформулировку у боя (`/vector/voice`,
`vector_llm.set_remote`), и озвучка в программе не пропадает.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать чистку значения в `_config_without_secrets` — краснеют
проверки утечки; убрать ветку `_remote_needed` из `voice`/`free_chat` — краснеют проверки
озвучки через бой; перестать передавать язык в `/vector/voice` — краснеет проверка языка.
"""
import pytest

from conftest import make_admin, make_teacher

SECRET = "GIGA-SECRET-26-09"


def _save_key_like_the_site(client, admin):
    r = client.post("/web/admin/ai-config",
                    json={"vector_llm": "gigachat", "gigachat_credentials": SECRET,
                          "gigachat_scope": "GIGACHAT_API_PERS"}, headers=admin)
    assert r.status_code == 200, r.text


def _student(client, admin, login="sec_st"):
    from app.security import hash_password
    client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "surname": "Сек", "name": "Рет",
        "group_name": "ИС-21"}]}}, headers=admin)
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("who", ["teacher", "student", "admin"])
def test_key_saved_on_the_site_never_reaches_a_pc(client, who):
    admin = make_admin(client)
    _save_key_like_the_site(client, admin)
    headers = {"teacher": lambda: make_teacher(client, admin, login="sec_t"),
               "student": lambda: _student(client, admin),
               "admin": lambda: admin}[who]()
    body = client.get("/sync/pull", headers=headers).text
    assert SECRET not in body, f"ключ GigaChat уехал в /sync/pull роли {who}"


def test_the_rest_of_the_ai_settings_still_reach_the_pc(client):
    """Провайдер и прочее — не секрет, и копии они нужны: по ним локальный Вектор
    понимает, что озвучивать надо через бой. Вырезать всё значит молча выключить озвучку."""
    admin = make_admin(client)
    _save_key_like_the_site(client, admin)
    th = make_teacher(client, admin, login="sec_t2")
    rows = client.get("/sync/pull", headers=th).json()["changes"]["config"]
    cfg = next(c["value"] for c in rows if c["key"] == "config")
    assert cfg.get("vector_llm") == "gigachat"
    assert cfg.get("gigachat_scope") == "GIGACHAT_API_PERS"
    assert "gigachat_credentials" not in cfg


def test_the_stored_config_is_not_mutated_by_the_pull(client):
    """Чистка идёт по КОПИИ: `_row_to_dict` отдаёт тот же словарь, что лежит в сессии."""
    admin = make_admin(client)
    _save_key_like_the_site(client, admin)
    th = make_teacher(client, admin, login="sec_t3")
    client.get("/sync/pull", headers=th)
    from app.db import SessionLocal
    from app.models import ConfigKV
    with SessionLocal() as db:
        assert dict(db.get(ConfigKV, "config").value).get("gigachat_credentials") == SECRET


# ── Озвучка Вектора там, где ключа нет (программа) ───────────────────────────────────
@pytest.fixture()
def remote(monkeypatch):
    from app import vector_llm
    calls = []

    def fake(mode, payload):
        calls.append((mode, payload))
        return f"ОЗВУЧЕНО-{mode}"
    monkeypatch.setattr(vector_llm, "_remote", fake)
    return calls


def test_without_a_key_the_vector_asks_the_server(remote):
    from app import vector_llm
    out = vector_llm.voice({"vector_llm": "gigachat"}, "Средний балл 4.5", "student", "q", "en")
    assert out == "ОЗВУЧЕНО-voice", "без ключа программа перестала озвучивать Вектора"
    assert remote[0][1]["locale"] == "en" and remote[0][1]["facts"] == "Средний балл 4.5"
    chat = vector_llm.free_chat({"vector_llm": "gigachat"}, "как дела?", "student")
    assert chat == "ОЗВУЧЕНО-chat"


def test_with_a_key_or_another_provider_nothing_goes_remote(remote, monkeypatch):
    """На бою ключ есть — хук не зовётся; Ollama живёт на той же машине и ключа не ждёт."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "_voice_gigachat", lambda *a, **k: "СВОЙ-КЛЮЧ")
    assert vector_llm.voice({"vector_llm": "gigachat", "gigachat_credentials": "k"},
                            "факты") == "СВОЙ-КЛЮЧ"
    monkeypatch.setattr(vector_llm, "_voice_ollama", lambda *a, **k: "OLLAMA")
    assert vector_llm.voice({"vector_llm": "ollama"}, "факты") == "OLLAMA"
    assert remote == []


def test_remote_failure_falls_back_to_the_facts(monkeypatch):
    from app import vector_llm

    def broken(mode, payload):
        raise OSError("нет сети")
    monkeypatch.setattr(vector_llm, "_remote", broken)
    assert vector_llm.voice({"vector_llm": "gigachat"}, "Факты как есть") == "Факты как есть"


def test_server_voice_door_takes_the_language_and_the_chat_mode(client, monkeypatch):
    from app import vector_llm
    seen = {}

    def fake_voice(cfg, facts, role="student", question="", locale="ru"):
        seen["voice"] = locale
        return "v"

    def fake_chat(cfg, question, role="student", context="", locale="ru"):
        seen["chat"] = (question, context, locale)
        return "c"
    monkeypatch.setattr(vector_llm, "voice", fake_voice)
    monkeypatch.setattr(vector_llm, "free_chat", fake_chat)
    admin = make_admin(client)
    th = make_teacher(client, admin, login="sec_t4")
    r = client.post("/vector/voice", json={"facts": "ф", "locale": "zh"}, headers=th)
    assert r.json() == {"text": "v"} and seen["voice"] == "zh"
    r = client.post("/vector/voice", json={"mode": "chat", "question": "привет",
                                           "locale": "en"}, headers=th)
    assert r.json() == {"text": "c"}
    assert seen["chat"] == ("привет", "", "en"), "в свободный разговор уехало лишнее"
