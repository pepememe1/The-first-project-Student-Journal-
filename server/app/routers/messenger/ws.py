"""
ws.py — Веб-сокет мессенджера: единственная точка, где держится живое соединение.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы


@router.websocket("/ws")
async def messenger_ws(ws: WebSocket):
    """Живой канал событий. Авторизация — JWT ТОЛЬКО через Sec-WebSocket-Protocol (не светит
    токен в логах). ?token= в query больше НЕ принимается: он клал JWT в access-лог, а им
    никто не пользуется (см. _ws_token). Клиент получает {type:'changed', conversation_id}
    и подтягивает свежее; может слать {type:'typing', conversation_id} — сервер ретранслирует
    остальным участникам."""
    jwt_token, subproto = _ws_token(ws)
    payload = decode_token(jwt_token) if jwt_token else None
    if not payload:
        await ws.close(code=4401)
        return
    db = SessionLocal()
    try:
        #🔒 ОТЗЫВ СЕССИИ. Раньше здесь проверялись только подпись и наличие пользователя —
        #в отличие от HTTP-пути (`deps.get_current_user`), который смотрит чёрный список
        #jti. Из-за этого «Выйти» и блокировка админом НЕ разрывали живой сокет: украденный
        #токен ещё до пяти часов получал сигналы `{"changed", conversation_id}` — то есть
        #видел, в каких беседах идёт переписка, — и мог слать «печатает…». Тексты не
        #утекали (их отдаёт HTTP, а он отзыв проверяет), но это ровно та дверь, ради
        #закрытия которой чёрный список jti и заводился.
        #Токены БЕЗ jti (старого формата) пускаем, как и на HTTP: иначе выданные до
        #введения списка сессии оборвались бы у всех разом.
        jti = payload.get("jti")
        revoked = False
        if jti:
            sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
            revoked = sess is None or bool(sess.revoked)
        user = None if revoked else db.query(User).filter(
            User.login == payload.get("sub"),
            User.deleted == False).first()  # noqa: E712
    finally:
        db.close()
    if user is None:
        await ws.close(code=4401)
        return

    ws_manager.bind_loop()
    await ws_manager.connect(user.id, ws, subprotocol=subproto)
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "typing" and data.get("conversation_id"):
                db2 = SessionLocal()
                try:
                    #⚠️ УЧАСТИЕ ПРОВЕРЯЕМ ЗДЕСЬ. Это единственное место мессенджера, где
                    #клиент сам называет беседу, а сокет уже авторизован — и раньше этого
                    #хватало, чтобы любой вошедший разослал «печатает…» в ЧУЖОЙ чат,
                    #просто подставив его id. Содержимого это не раскрывало, но давало
                    #проверять существование бесед перебором и подсовывать людям
                    #несуществующего собеседника. У всех остальных эндпоинтов участие
                    #сверяет `_require_participant`; сокет был исключением.
                    everyone = _participant_ids(db2, data["conversation_id"])
                    ids = [i for i in everyone if i != user.id] if user.id in everyone else []
                finally:
                    db2.close()
                if ids:
                    await ws_manager.send_users(
                        ids, {"type": "typing", "conversation_id": data["conversation_id"],
                              "user_id": user.id})
    except WebSocketDisconnect:
        ws_manager.disconnect(user.id, ws)
    except Exception:
        ws_manager.disconnect(user.id, ws)
