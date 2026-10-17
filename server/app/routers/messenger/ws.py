"""
ws.py — Веб-сокет мессенджера: единственная точка, где держится живое соединение.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.

🔥 БАЗА — ТОЛЬКО ЧЕРЕЗ ПУЛ ПОТОКОВ (аудит 17.10.2026). Обработчик сокета обязан быть
`async def`, а SQLAlchemy у нас синхронный: запрос к базе прямо в нём держал ЕДИНСТВЕННЫЙ
цикл событий процесса — на входе в сокет и на КАЖДОМ «печатает…». Пока SQLite ждал
записи соседа (`busy_timeout`), стояли все сокеты и все асинхронные ручки. Поэтому вся
работа с базой — синхронными функциями ниже, а сокет их ждёт через `run_in_threadpool`;
сессия открывается и закрывается в той же функции и между потоками не ходит.
"""
import time

from starlette.concurrency import run_in_threadpool

from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы
from ...security import is_access_payload

#«Печатает…» — подсказка, а не данные: клиент шлёт её не чаще раза в 2 с (stores/
#messenger.js::sendTyping), и всё, что чаще, — не человек. Каждый сигнал — запрос к базе
#(кто участник беседы), поэтому частоту держит и сервер: одна беседа — не чаще раза в
#`_TYPING_EVERY_S`, а всего по сокету — не чаще раза в `_TYPING_ANY_S` (иначе перебор
#разных id бесед обходил бы первый предел).
_TYPING_EVERY_S = 2.0
_TYPING_ANY_S = 0.5


def _ws_user(payload: dict):
    """Чей это сокет: пользователь по токену или None. СИНХРОННАЯ — только через пул.

    🔒 ОТЗЫВ СЕССИИ. Раньше здесь проверялись только подпись и наличие пользователя —
    в отличие от HTTP-пути (`deps.get_current_user`), который смотрит чёрный список
    jti. Из-за этого «Выйти» и блокировка админом НЕ разрывали живой сокет: украденный
    токен ещё до пяти часов получал сигналы `{"changed", conversation_id}` — то есть
    видел, в каких беседах идёт переписка, — и мог слать «печатает…». Тексты не
    утекали (их отдаёт HTTP, а он отзыв проверяет), но это ровно та дверь, ради
    закрытия которой чёрный список jti и заводился.
    Токены БЕЗ jti (старого формата) пускаем, как и на HTTP: иначе выданные до
    введения списка сессии оборвались бы у всех разом."""
    db = SessionLocal()
    try:
        jti = payload.get("jti")
        if jti:
            sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
            if sess is None or bool(sess.revoked):
                return None
        user = db.query(User).filter(
            User.login == payload.get("sub"),
            User.deleted == False).first()  # noqa: E712
        if user is not None:
            #Поля нужны и после закрытия сессии (id, роль для псевдонима модератора):
            #объект уходит в другой поток отсоединённым и сам их уже не дочитает.
            db.expunge(user)
        return user
    finally:
        db.close()


def _typing_recipients(conv_id: str, user_id: str) -> list:
    """Кому показать «печатает…». СИНХРОННАЯ — только через пул.

    ⚠️ УЧАСТИЕ ПРОВЕРЯЕМ ЗДЕСЬ. Это единственное место мессенджера, где клиент сам
    называет беседу, а сокет уже авторизован — и раньше этого хватало, чтобы любой
    вошедший разослал «печатает…» в ЧУЖОЙ чат, просто подставив его id. Содержимого это
    не раскрывало, но давало проверять существование бесед перебором и подсовывать
    людям несуществующего собеседника. У всех остальных эндпоинтов участие сверяет
    `_require_participant`; сокет был исключением."""
    db = SessionLocal()
    try:
        everyone = _participant_ids(db, conv_id)
        return [i for i in everyone if i != user_id] if user_id in everyone else []
    finally:
        db.close()


class _TypingGate:
    """Пропускать ли очередной «печатает…» этого сокета (см. `_TYPING_*` выше)."""

    def __init__(self):
        self._last_any = 0.0
        self._last_by_conv: dict = {}

    def allow(self, conv_id: str, now: float) -> bool:
        if now - self._last_any < _TYPING_ANY_S:
            return False
        if now - self._last_by_conv.get(conv_id, -1e9) < _TYPING_EVERY_S:
            return False
        self._last_any = now
        self._last_by_conv[conv_id] = now
        if len(self._last_by_conv) > 200:          #память сокета не растёт перебором id
            self._last_by_conv = {conv_id: now}
        return True


@router.websocket("/ws")
async def messenger_ws(ws: WebSocket):
    """Живой канал событий. Авторизация — JWT ТОЛЬКО через Sec-WebSocket-Protocol (не светит
    токен в логах). ?token= в query больше НЕ принимается: он клал JWT в access-лог, а им
    никто не пользуется (см. _ws_token). Клиент получает {type:'changed', conversation_id}
    и подтягивает свежее; может слать {type:'typing', conversation_id} — сервер ретранслирует
    остальным участникам."""
    jwt_token, subproto = _ws_token(ws)
    payload = decode_token(jwt_token) if jwt_token else None
    #Тип токена — той же дверью, что HTTP (`security.is_access_payload`): без неё сокет
    #открывал challenge второго фактора, выданный по одному паролю.
    if not payload or not is_access_payload(payload):
        await ws.close(code=4401)
        return
    user = await run_in_threadpool(_ws_user, payload)
    if user is None:
        await ws.close(code=4401)
        return

    ws_manager.bind_loop()
    await ws_manager.connect(user.id, ws, subprotocol=subproto)
    gate = _TypingGate()
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "typing" and data.get("conversation_id"):
                conv_id = str(data["conversation_id"])
                if not gate.allow(conv_id, time.monotonic()):
                    continue
                ids = await run_in_threadpool(_typing_recipients, conv_id, user.id)
                if ids:
                    #Модератор «печатает» — псевдонимом (F-10): получатели разные, а
                    #событие одно, и сырой id ушёл бы тем, кому личность не положена.
                    who = moderator_alias(user) if _masked_for(user) else user.id
                    await ws_manager.send_users(
                        ids, {"type": "typing", "conversation_id": conv_id,
                              "user_id": who})
    except WebSocketDisconnect:
        ws_manager.disconnect(user.id, ws)
    except Exception:
        ws_manager.disconnect(user.id, ws)
