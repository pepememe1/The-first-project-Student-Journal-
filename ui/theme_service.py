"""
theme_service.py — Логика выбора и сохранения темы оформления (клиент).

Связывает три источника темы и решает, какую применить:
  1) ЛОКАЛЬНЫЙ кэш этого ПК (data_store.local_*, не синхронизируется) — что
     пользователь видел в прошлый раз на этом устройстве (мгновенно и офлайн);
  2) персональная тема из синхронизированной записи пользователя (prefs.theme,
     приезжает с сервера на pull) — это и есть «роуминг» темы между ПК;
  3) тема учебного заведения из общего config (institution_theme), которую задаёт
     администратор и которая синхронизируется на всех.

Тонкость по ТЗ. У темы есть «источник» (theme_source):
  • "institution" — пользователь ещё не выбирал тему сам, ему досталась тема вуза.
    Если админ сменит тему вуза — у таких пользователей она обновится.
  • "user" — пользователь выбрал тему сам. Теперь смена темы вуза его НЕ трогает,
    а его выбор «роумится» на другие его ПК.

Поток из ТЗ: подключаемся к БД → ставится тема вуза, id улетает в БД (source=
institution) → меняем тему на своём аккаунте → source=user, id темы в БД меняется.
"""
import themes
import log
from data_store import get_store, local_get, local_set, _kv_set

#Локальный кэш применённой темы. Хранит {"spec":..,"source":..}. ВАЖНО: ключ
#привязан к КОНКРЕТНОМУ аккаунту (а не к устройству) — иначе на общем ПК колледжа
#тема одного пользователя «утекала» бы соседу по той же машине.
_LOCAL_PREFIX = "my_theme"
_INSTITUTION_CFG = "institution_theme"


def _ident_token(role: str, identity: dict) -> str:
    """Стабильный токен аккаунта для ключа локального кэша темы."""
    identity = identity or {}
    if role == "teacher":
        return "teacher:" + (identity.get("name", "") or "?")
    if role == "student":
        return "student:{}|{}|{}".format(identity.get("f", ""), identity.get("n", ""),
                                         identity.get("g", ""))
    if role == "admin":
        return "admin"
    return "default"


def _local_key(role: str, identity: dict) -> str:
    return f"{_LOCAL_PREFIX}:{_ident_token(role, identity)}"


#Низкоуровневые помощники
def _config() -> dict:
    try:
        return get_store()._config()
    except Exception:
        return {}


def _institution_spec():
    """Спецификация темы вуза из config ('' / None — не задана)."""
    raw = _config().get(_INSTITUTION_CFG)
    return themes.spec_from_json(raw) if raw else None


def _local_record(role: str, identity: dict) -> dict | None:
    """{"spec":..,"source":..} из локального кэша ЭТОГО аккаунта на этом ПК (None — нет)."""
    rec = local_get(_local_key(role, identity), None)
    if isinstance(rec, dict) and rec.get("spec"):
        return {"spec": themes.normalize_spec(rec["spec"]),
                "source": rec.get("source", "user")}
    return None


def _set_local(role: str, identity: dict, spec: dict, source: str):
    local_set(_local_key(role, identity),
              {"spec": themes.normalize_spec(spec), "source": source})


def _user_prefs(role: str, identity: dict) -> dict:
    """prefs пользователя из его синхронизированной локальной записи (или {})."""
    identity = identity or {}
    try:
        store = get_store()
        if role == "teacher":
            name = identity.get("name", "")
            return store.get_teachers().get(name, {}).get("prefs") or {}
        if role == "student":
            f, n, g = identity.get("f", ""), identity.get("n", ""), identity.get("g", "")
            for s in store.get_students():
                if (s.get("surname", "") == f and s.get("name", "") == n
                        and s.get("group", "") == g):
                    return s.get("prefs") or {}
    except Exception:
        pass
    return {}


def _push(spec: dict, source: str):
    """Лучшая попытка отправить тему в БД (self-scope /me/prefs). Офлайн — пропустит."""
    try:
        import sync_runner
        sync_runner.push_my_prefs({"theme": themes.normalize_spec(spec),
                                   "theme_source": source})
    except Exception:
        pass


#Публичный интерфейс
def current_spec(role: str = "", identity: dict = None) -> dict:
    """Тема, применённая для этого аккаунта сейчас (для инициализации редактора)."""
    rec = _local_record(role, identity or {})
    if rec:
        return rec["spec"]
    return _institution_spec() or {"id": themes.DEFAULT_ID}


def apply_startup_default():
    """Применить тему вуза (или дефолт) ДО входа — чтобы экран входа был в теме.
    Локальный кэш НЕ трогаем (это ещё не выбор конкретного пользователя)."""
    themes.apply_spec(_institution_spec() or {"id": themes.DEFAULT_ID})


def save_user_theme(spec: dict, role: str, identity: dict) -> dict:
    """Пользователь нажал «Сохранить» в профиле: применяем, кэшируем, шлём в БД."""
    spec = themes.normalize_spec(spec)
    _set_local(role, identity, spec, "user")
    _push(spec, "user")
    return themes.apply_spec(spec)


def save_institution_theme(spec: dict) -> dict:
    """Админ задал тему учебного заведения: пишем в общий config (уедет всем) и
    применяем у себя. Тему вуза пушит только админ — права уже так устроены."""
    spec = themes.normalize_spec(spec)
    try:
        cfg = get_store()._config()
        cfg[_INSTITUTION_CFG] = themes.spec_to_json(spec)
        _kv_set("config", cfg)   #wake=True по умолчанию — config уедет на сервер
    except Exception as e:
        log.get("theme_service").warning(f"[theme] не удалось сохранить тему вуза: {e}")
    #У самого админа эта тема становится текущей темой аккаунта на этом ПК.
    _set_local("admin", {}, spec, "institution")
    return themes.apply_spec(spec)


def resolve_and_apply(role: str, identity: dict) -> dict:
    """Выбрать и применить тему при входе пользователя (см. порядок в шапке)."""
    cached = _local_record(role, identity)
    #Явный выбор пользователя на этом ПК — высший приоритет (даже над темой вуза).
    if cached and cached["source"] == "user":
        return themes.apply_spec(cached["spec"])

    prefs = _user_prefs(role, identity)
    rec_theme = prefs.get("theme")
    rec_source = prefs.get("theme_source", "user")

    #Персональная тема пользователя, выбранная им на ДРУГОМ ПК (роуминг).
    if rec_theme and rec_source == "user":
        sp = themes.normalize_spec(rec_theme)
        _set_local(role, identity, sp, "user")
        return themes.apply_spec(sp)

    #Иначе — тема вуза: применяем и фиксируем как персональную (id улетает в БД).
    inst = _institution_spec()
    if inst:
        _set_local(role, identity, inst, "institution")
        _push(inst, "institution")
        return themes.apply_spec(inst)

    #На крайний случай — то, что осталось в кэше (тема вуза с прошлого раза), либо дефолт.
    if cached:
        return themes.apply_spec(cached["spec"])
    return themes.apply_spec({"id": themes.DEFAULT_ID})


def on_sync_refresh(role: str, identity: dict) -> bool:
    """Вызывается после фоновой синхронизации. Возвращает True, если тему сменили
    (тогда UI стоит пересобрать). Догоняет два случая:
      • пользователь сменил тему на другом ПК (roam) — у кого здесь нет своего выбора;
      • админ сменил тему вуза — у тех, кто на теме вуза (source != user)."""
    cached = _local_record(role, identity)
    if cached and cached["source"] == "user":
        return False   #на этом ПК пользователь выбрал тему сам — не трогаем

    prefs = _user_prefs(role, identity)
    rec_theme = prefs.get("theme")
    rec_source = prefs.get("theme_source", "user")

    #Персональный выбор приехал с другого ПК — применяем здесь.
    if rec_theme and rec_source == "user":
        sp = themes.normalize_spec(rec_theme)
        if cached is None or sp != cached["spec"]:
            _set_local(role, identity, sp, "user")
            themes.apply_spec(sp)
            return True
        return False

    #Тема вуза изменилась — обновляем у тех, кто на ней.
    inst = _institution_spec()
    if inst and (cached is None or themes.normalize_spec(inst) != cached["spec"]):
        _set_local(role, identity, inst, "institution")
        themes.apply_spec(inst)
        return True
    return False
