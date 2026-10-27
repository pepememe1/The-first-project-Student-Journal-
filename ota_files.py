"""
ota_files.py — список файлов OTA-бандла и его отпечаток (23.10.2026).

Пофайловое обновление телефона (плагин качает только изменённые файлы) было выключено с
4.1: список файлов с их SHA-256 сервер отдаёт рядом с подписанным манифестом, но сам он
подписан не был, и приложение его не брало — иначе подменой списка можно было бы
подсунуть чужой файл. Теперь выпуск подписывает отпечаток списка (`tools/sign_ota.py`),
а приложение сверяет его до закачки (`web/src/utils/otaVerify.js`).

Общий для сервера (`server/app/routers/appupdate.py` раздаёт список) и подписи выпуска:
подпись ставится над тем самым списком, который потом отдаёт сервер, и две копии обхода
архива разошлись бы молча — телефоны перестали бы принимать пофайловое обновление и
качали бы архив целиком. Отпечаток в JS — `filesDigest`, их согласие держит образец
`web/tests/fixtures/ota-files-fixture.json`. Чистый stdlib.
"""
import hashlib
import zipfile


def zip_file_list(zip_path) -> list:
    """(имя, SHA-256) каждого файла архива в порядке архива; каталоги пропускаются.

    Бросает OSError и zipfile.BadZipFile — что делать с битым архивом, решает вызывающий."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            digest = hashlib.sha256()
            with z.open(info) as fh:
                for chunk in iter(lambda: fh.read(1024 * 256), b""):
                    digest.update(chunk)
            out.append((info.filename, digest.hexdigest()))
    return out


def files_digest(entries) -> str:
    """Отпечаток списка: SHA-256 строк «имя:хеш», отсортированных и соединённых переводом
    строки. Сортировка — чтобы порядок, в котором сервер отдал список, не менял отпечаток."""
    lines = sorted(f"{name}:{str(file_hash).lower()}" for name, file_hash in entries)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
