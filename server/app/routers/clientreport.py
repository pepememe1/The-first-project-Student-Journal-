"""
clientreport.py — приём ошибок интерфейса и времени старта от клиентов (app/client_metrics.py).

Адрес под публичным префиксом `/app`: отчёт приходит и до входа, а ошибка на экране входа
важна не меньше прочих. Поэтому ручка ничего не пишет в базу, не отвечает данными и читает
не больше MAX_BODY байт: открытый адрес не должен становиться способом занять память
или диск сервера. Сколько и чего копится, ограничивает сам `client_metrics`.
"""
import json

from fastapi import APIRouter, HTTPException, Request, Response

from .. import client_metrics, throttle

router = APIRouter(prefix="/app", tags=["client-report"])

#Десять ошибок по 160 знаков и замер старта укладываются в пару килобайт.
MAX_BODY = 16 * 1024


@router.post("/client-report", status_code=204)
async def client_report(request: Request):
    """Принять отчёт клиента: `{platform, version, errors: [...], startup: {...}}`.

    `async def` ради чтения тела потоком с потолком: заголовок Content-Length присылает
    клиент, и верить ему нельзя (§4.38). Разбор — несколько словарей в памяти, без базы
    и без блокирующих вызовов (§4.42)."""
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "Отчёт слишком большой")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise HTTPException(413, "Отчёт слишком большой")
    try:
        data = json.loads(body or b"{}")
    except (ValueError, RecursionError):
        #RecursionError — «[[[[…]]]]» в несколько тысяч уровней. Без него открытый адрес
        #отвечал 500, а каждый 500 — запись в общем журнале событий, кольце на 500 строк:
        #им можно было вытеснить записи защиты (ревью 23.10.2026).
        raise HTTPException(400, "Отчёт не в формате JSON") from None
    client_metrics.metrics.ingest(data, throttle.client_ip(request))
    return Response(status_code=204)
