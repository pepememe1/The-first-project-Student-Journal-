"""Объектное хранилище для вложений мессенджера (S3-совместимое).

━━ ГЛАВНОЕ ПРАВИЛО: ФАЙЛ ЧЕРЕЗ НАШ СЕРВЕР НЕ ПРОХОДИТ ━━
Ни при загрузке, ни при скачивании. Браузер работает с хранилищем НАПРЯМУЮ по временной
подписанной ссылке, а мы храним только метаданные — имя, размер, тип, кто и в какой
беседе. Это не оптимизация, а условие работоспособности: на боевой машине ОДНО ядро и
ОДИН процесс uvicorn, который раздаёт журнал. Прогони через него пару лекций — и лягут
оценки с расписанием, а не мессенджер (замеры и разбор — docs/MESSENGER-ATTACHMENTS-PLAN.md).

━━ ПОЧЕМУ БЕЗ boto3 ━━
Подпись AWS SigV4 — это несколько вызовов hmac/sha256, здесь она занимает полсотни строк.
boto3 тянет botocore и десятки мегабайт в образ ради одной операции «подпиши ссылку».
На машине с 960 МБ ОЗУ и на сборке .exe это заметно, а выгоды нет никакой.

━━ ГДЕ ХРАНИМ (152-ФЗ) ━━
Только РФ: Yandex Object Storage, VK Cloud, Selectel, Timeweb — все S3-совместимы,
поэтому код от провайдера не зависит и переезд стоит только новых ключей.
⚠️ Cloudflare R2 / AWS нельзя: данные учащихся обязаны оставаться в России.

⚠️ Пока ключи не заданы, `configured()` отдаёт False, и ручки честно отвечают «хранилище
не настроено». Это НЕ заглушка «потом доделаем»: молча принять файл и потерять его —
хуже отказа, потому что человек будет уверен, что отправил.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from urllib.parse import quote

#Настройки — из окружения, как всё остальное (см. config.py). Ничего не хардкодим:
#переезд на сервера ВСГУТУ или другой VPS не должен требовать правок кода.
ENDPOINT = os.environ.get("GRADEBOOK_S3_ENDPOINT", "").strip().rstrip("/")
REGION = os.environ.get("GRADEBOOK_S3_REGION", "ru-central1").strip()
BUCKET = os.environ.get("GRADEBOOK_S3_BUCKET", "").strip()
ACCESS_KEY = os.environ.get("GRADEBOOK_S3_KEY", "").strip()
SECRET_KEY = os.environ.get("GRADEBOOK_S3_SECRET", "").strip()

#Потолок размера. 25 МБ — это учебный документ, презентация или скан, но не видео:
#видео живёт ссылкой на видеохостинг (механизм А в плане), и так и должно остаться.
MAX_SIZE = int(os.environ.get("GRADEBOOK_S3_MAX_MB", "25")) * 1024 * 1024

#Сколько живёт подписанная ссылка. Загрузка — дольше (большой файл на слабом канале),
#скачивание — короче: ссылка утекает пересылкой в чужой чат, и час чужого доступа
#заметно хуже пятнадцати минут.
UPLOAD_TTL_S = 900
DOWNLOAD_TTL_S = 900

#⚠️ БЕЛЫЙ список типов, а не чёрный. Чёрный всегда неполон, и первым же пропущенным
#типом окажется исполняемый. Картинки и видео сюда НЕ входят намеренно (см. выше).
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/rtf": ".rtf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/zip": ".zip",
}


def configured() -> bool:
    """Готово ли хранилище. Без него ручки вложений отвечают честным отказом."""
    return bool(ENDPOINT and BUCKET and ACCESS_KEY and SECRET_KEY)


def mime_ok(mime: str) -> bool:
    return (mime or "").split(";")[0].strip().lower() in ALLOWED_MIME


def _sign_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = ("AWS4" + secret).encode()
    for part in (date, region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return k


def presign(method: str, key: str, expires: int, *, content_type: str = "",
            extra: dict = None) -> str:
    """Временная ссылка на объект: подпись SigV4 в query-параметрах.

    ⚠️ `UNSIGNED-PAYLOAD` намеренно: тело подписывать нельзя — при загрузке браузер шлёт
    файл, которого у нас нет и быть не должно. Целостность обеспечивает TLS, а доступ —
    сама подпись и её срок.

    ⚠️ Ключ объекта кодируем с `safe="/"`: слэши в пути обязаны остаться слэшами, иначе
    хранилище увидит один объект со странным именем вместо папки.
    """
    if not configured():
        raise RuntimeError("хранилище не настроено")

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    host = ENDPOINT.split("://", 1)[-1]
    scope = f"{date}/{REGION}/s3/aws4_request"

    canon_uri = f"/{BUCKET}/{quote(key, safe='/')}"

    #🔥 ТИП СОДЕРЖИМОГО ВХОДИТ В ПОДПИСЬ (находка Полковника 25.08.2026). Раньше
    #`content_type` принимался и НИГДЕ не использовался: подпись связывала только хост,
    #поэтому по ссылке, выданной под «конспект.txt, text/plain», можно было залить
    #исполняемый файл любого размера — проверки жили только в нашей декларации, а не в
    #самом разрешении. Теперь заголовок подписан, и хранилище отвергнет запрос с другим
    #типом: клиент ОБЯЗАН прислать ровно тот `Content-Type`, под который подписано.
    #⚠️ Размер так связать нельзя: `content-length-range` есть только у POST-policy, а мы
    #грузим PUT'ом. Поэтому размер проверяется ПОСЛЕ загрузки (`head_object` +
    #`confirm_upload`): не сошёлся — объект удаляется и готовым не считается.
    signed = {"host": host}
    if content_type:
        signed["content-type"] = content_type
    signed_names = ";".join(sorted(signed))

    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{ACCESS_KEY}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": signed_names,
    }
    params.update(extra or {})
    canon_qs = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}"
                        for k, v in sorted(params.items()))
    canon_headers = "".join(f"{k}:{signed[k]}\n" for k in sorted(signed))
    canon_req = "\n".join([
        method.upper(), canon_uri, canon_qs,
        canon_headers, signed_names, "UNSIGNED-PAYLOAD",
    ])
    to_sign = "\n".join([
        "AWS4-HMAC-SHA256", stamp, scope,
        hashlib.sha256(canon_req.encode()).hexdigest(),
    ])
    signature = hmac.new(_sign_key(SECRET_KEY, date, REGION, "s3"),
                         to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{ENDPOINT}{canon_uri}?{canon_qs}&X-Amz-Signature={signature}"


def upload_url(key: str, content_type: str) -> str:
    return presign("PUT", key, UPLOAD_TTL_S, content_type=content_type)


def download_url(key: str, name: str = "", mime: str = "") -> str:
    """Ссылка на скачивание. Имя файла подставляем ЗАГОЛОВКОМ ответа.

    🔥 Докстринг `object_key` обещал это с самого начала, а кода не было (находка
    Полковника 25.08.2026): браузер сохранял объект под ключом `att:<hex>` — без имени и
    без расширения. Предпросмотр это скрывал, потому что тянет байты сам, так что
    заметили бы только на живом хранилище.

    ⚠️ `response-content-disposition` — подписанный query-параметр, поэтому подменить его
    в уже выданной ссылке нельзя. Имя кодируем по RFC 5987 (`filename*`): в наших именах
    кириллица, а сырой заголовок её не переживёт.
    """
    extra = {}
    if name:
        safe = quote(name, safe="")
        extra["response-content-disposition"] = f"attachment; filename*=UTF-8''{safe}"
    if mime:
        extra["response-content-type"] = mime
    return presign("GET", key, DOWNLOAD_TTL_S, extra=extra)


def head_object(key: str) -> dict:
    """Настоящие размер и тип объекта в хранилище.

    ⚠️ Нужен потому, что подписанный PUT не умеет ограничивать РАЗМЕР: `content-length-
    range` есть только у POST-policy. Значит единственная честная проверка — посмотреть,
    что реально легло, и отвергнуть несовпадение (см. `confirm_upload`).
    """
    if not configured():
        return {}
    import urllib.error
    import urllib.request
    req = urllib.request.Request(presign("HEAD", key, 300), method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"size": int(resp.headers.get("Content-Length") or 0),
                    "mime": (resp.headers.get("Content-Type") or "").split(";")[0].strip()}
    except urllib.error.HTTPError:
        return {}
    except Exception:
        return {}


def object_key(conv_id: str, att_id: str) -> str:
    """Путь объекта. Беседа в пути — чтобы уборку и разбор инцидента можно было сделать
    по префиксу, не поднимая базу.

    ⚠️ Имя файла в ключ НЕ кладём: оно приходит от человека, содержит что угодно вплоть
    до `../`, и путь в хранилище — последнее место, где стоит доверять такому вводу.
    Настоящее имя живёт в базе и подставляется заголовком при скачивании.
    """
    safe_conv = "".join(c for c in conv_id if c.isalnum() or c in "-_:")[:64]
    return f"messenger/{safe_conv}/{att_id}"


def delete_object(key: str) -> bool:
    """Удалить объект. Зовётся уборкой по сроку, а не удалением сообщения.

    ⚠️ Почему не сразу: сообщения удаляются ТУМБСТОУНОМ ради модерации — жалоба обязана
    показать оригинал, и автор не должен заметать следы, удалив сообщение после жалобы.
    Файл — часть сообщения, значит правило то же. Физически стираем позже, когда ссылок
    на вложение не осталось и срок разбора вышел.
    """
    if not configured():
        return False
    import urllib.error
    import urllib.request
    req = urllib.request.Request(presign("DELETE", key, 300), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        return e.code == 404          #уже нет — считаем, что задача выполнена
    except Exception:
        return False
