r"""
sign_ota.py — подпись OTA-бандла мобильного приложения (аудит 22.09.2026, находка F-24).

    python tools/sign_ota.py sign   server/ota_bundles/latest.json
    python tools/sign_ota.py verify server/ota_bundles/latest.json

━━ ЗАЧЕМ ━━
Контрольная сумма бандла едет ТЕМ ЖЕ каналом, что и сам архив: она ловит битую закачку и
не ловит подмену. Получивший доступ к хранилищу бандлов или к учётке выкладки заменил бы
архив и сумму в манифесте разом — и телефоны сами поставили бы чужой JavaScript внутрь
приложения с токенами и данными людей. Тот же довод, что у подписи обновления программы
(`desktop_update.py`), только канал другой.

Подписывается пара «версия + SHA-256 архива»: версия — чтобы наша же прошлая подпись не
годилась для манифеста, откатывающего телефоны на старый бандл; сумма — чтобы подпись
относилась к тому архиву, который телефон реально скачает (Capgo сверяет её сам).

━━ ФОРМАТ ━━
ECDSA P-256 + SHA-256, подпись — 64 байта r||s в base64 (ровно так её ждёт WebCrypto в
браузере, `web/src/utils/otaVerify.js`). P-256, а не Ed25519, как у программы: WebCrypto
в WebView старых Android не умеет Ed25519, а тащить в приложение самописную криптографию
ради одного вызова нельзя. Строка подписи — `otaPayload` ниже; она же в JS — одна формула,
её сверяет общий тест-образец (`web/tests/fixtures/ota-sig-fixture.json`).

⚠️ Закрытый ключ — `~/.gradebook/ota_signing_key.pem`, ВНЕ репозитория (как ключ подписи
программы). Потеря = нельзя выпускать OTA до выхода нового APK с новым ключом.
⚠️ `verify` проверяет тем же списком ключей, что вшит в приложение
(`web/src/config/ota-public-keys.json`): «есть ли поле sig» ничего не доказывает — подпись
чужим ключом тоже поле.
"""
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_FILE = os.path.join(ROOT, "web", "src", "config", "ota-public-keys.json")
PRIVATE_KEY = os.path.join(os.path.expanduser("~"), ".gradebook", "ota_signing_key.pem")


def ota_payload(version: str, checksum: str) -> bytes:
    """Что подписывается. ОДНА формула с `otaPayload` в `web/src/utils/otaVerify.js`."""
    return f"gradebook-ota:v1:{version}:{(checksum or '').lower()}".encode("utf-8")


def public_keys(path: str = KEYS_FILE) -> list:
    with open(path, encoding="utf-8") as fh:
        return [k for k in (json.load(fh).get("keys") or []) if k]


def sign_payload(payload: bytes, private_pem: bytes) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key = serialization.load_pem_private_key(private_pem, password=None)
    der = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode("ascii")


def verify_payload(payload: bytes, sig_b64: str, keys: list) -> bool:
    """Годится ли подпись хотя бы одним из ключей. Ничего не бросает."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    try:
        raw = base64.b64decode(sig_b64 or "", validate=True)
    except (ValueError, TypeError):
        return False
    if len(raw) != 64:
        return False
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    for k in keys:
        try:
            pub = serialization.load_der_public_key(base64.b64decode(k))
            pub.verify(der, payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError, TypeError):
            continue
    return False


def _read_manifest(path: str) -> dict:
    #utf-8-sig: `Set-Content -Encoding utf8` в PowerShell 5.1 пишет метку BOM.
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def main(argv) -> int:
    if len(argv) != 3 or argv[1] not in ("sign", "verify"):
        print(__doc__.strip().splitlines()[2])
        print(__doc__.strip().splitlines()[3])
        return 2
    path = argv[2]
    data = _read_manifest(path)
    version, checksum = str(data.get("version") or ""), str(data.get("checksum") or "")
    if not version or not checksum:
        print("ОШИБКА: в манифесте нет version или checksum — подписывать нечего")
        return 1
    keys = public_keys()
    if not keys:
        print("ОШИБКА: список ключей в web/src/config/ota-public-keys.json пуст — телефоны "
              "не примут ни одного бандла")
        return 1
    if argv[1] == "sign":
        if not os.path.isfile(PRIVATE_KEY):
            print(f"ОШИБКА: нет закрытого ключа {PRIVATE_KEY} — выкладку с этой машины "
                  "подписать нечем")
            return 1
        with open(PRIVATE_KEY, "rb") as fh:
            data["sig"] = sign_payload(ota_payload(version, checksum), fh.read())
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"подписан {version}")
    if not verify_payload(ota_payload(version, checksum), str(data.get("sig") or ""), keys):
        print("ОШИБКА: подпись манифеста не сходится с ключами приложения — телефоны "
              "откажутся ставить этот бандл")
        return 1
    print(f"подпись {version} сходится с ключом приложения")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
