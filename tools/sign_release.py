#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sign_release.py — ПОДПИСЬ ВЫПУСКА ДЕСКТОПА (Ed25519).

Закрывает пункт, который висел незакрытым и был честно назван в README: контрольная
сумма обновления едет ТЕМ ЖЕ каналом, что и файл. Она ловит битую закачку и не ловит
подмену — подменивший .exe перепишет и хеш в манифесте, а клиент добросовестно сверит
подделку саму с собой.

Подпись ломает эту симметрию: закрытый ключ у нас, открытый вшит в программу.

━━ КАК ЭТИМ ПОЛЬЗОВАТЬСЯ ━━
Один раз, при заведении ключа:

    python tools/sign_release.py --gen-key

Скрипт напечатает открытый ключ — его надо вписать в `desktop_update.UPDATE_PUBLIC_KEYS`
и выложить вместе со сборкой. Закрытый ляжет ВНЕ репозитория.

Дальше на каждой выкладке (это делает `tools/publish_desktop_update.sh`):

    python tools/sign_release.py --manifest downloads/updates/manifest.json

━━ 🔴 ЧЕГО ЭТОТ ИНСТРУМЕНТ НЕ ДЕЛАЕТ, И ЭТО НАДО ЗНАТЬ ДО ТОГО, КАК ПОЛАГАТЬСЯ ━━
Ключ лежит файлом на машине выкладки, а не в offline-хранилище и не в HSM. Значит
получивший эту машину получает и возможность подписывать. Настоящая offline-подпись
(ключ на отдельном носителе, подписание руками) — отдельная работа и отдельное решение,
см. `docs/security/PLAN-SECURITY-2.0.md`.
Это НЕ повод не делать текущий шаг: он закрывает подмену на канале и на сервере раздачи,
а это и есть самый вероятный случай. Но писать «обновления защищены» без оговорки нельзя.

🔑 ПОТЕРЯ ЗАКРЫТОГО КЛЮЧА = НЕВОЗМОЖНОСТЬ ВЫПУСКАТЬ ОБНОВЛЕНИЯ для всех, у кого уже
стоит сборка с этим открытым ключом. Ровно та же цена, что у `release.keystore` для
RuStore, и хранить его надо так же: копия вне рабочей машины.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop_update as DU  # noqa: E402

#Дом закрытого ключа — вне репозитория, чтобы его нельзя было закоммитить случайно.
#Тот же приём, что у `web/android/keystore.properties`.
DEFAULT_KEY_PATH = os.path.join(os.path.expanduser("~"), ".gradebook",
                                "release_signing_key.hex")


def _load_private(path: str):
    """Прочитать закрытый ключ. Ошибки называем ПРИЧИНОЙ, а не трейсбеком."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not os.path.isfile(path):
        raise SystemExit(
            "Закрытого ключа нет: %s\n"
            "Заведите его один раз: python tools/sign_release.py --gen-key" % path)
    raw = io.open(path, encoding="utf-8").read().strip()
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        raise SystemExit("Файл ключа повреждён (ожидались 64 hex-символа): %s" % path) from None
    if len(data) != 32:
        raise SystemExit("Ключ должен быть ровно 32 байта (64 hex), а в файле %d"
                         % len(data))
    return Ed25519PrivateKey.from_private_bytes(data)


def gen_key(path: str) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if os.path.exists(path):
        #Молча перезаписать существующий ключ значило бы обнулить обновления у всего
        #парка — и узнать об этом только когда обновление перестанет ставиться.
        raise SystemExit(
            "Ключ уже существует: %s\nЕсли нужен НОВЫЙ ключ — уберите файл вручную и "
            "не забудьте оставить прежний открытый ключ в UPDATE_PUBLIC_KEYS, пока парк "
            "не обновится." % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(encoding=serialization.Encoding.Raw,
                             format=serialization.PrivateFormat.Raw,
                             encryption_algorithm=serialization.NoEncryption())
    io.open(path, "w", encoding="utf-8").write(raw.hex())
    try:
        os.chmod(path, 0o600)          #на Windows почти без эффекта, на Linux значим
    except OSError:
        pass
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    print("Закрытый ключ записан: %s" % path)
    print("НЕ КОММИТИТЬ. Сделайте копию вне этой машины — потеря = конец обновлений.")
    print()
    print("Открытый ключ (вписать в desktop_update.UPDATE_PUBLIC_KEYS):")
    print('    UPDATE_PUBLIC_KEYS = (\n        "%s",\n    )' % pub)
    return 0


def sign_manifest(manifest_path: str, key_path: str) -> int:
    priv = _load_private(key_path)
    with io.open(manifest_path, encoding="utf-8") as f:
        man = json.load(f)

    version = DU.normalize(man.get("version") or "")
    if not version:
        raise SystemExit("В манифесте нет версии — подписывать нечего")

    signed = 0
    full = man.get("full") or {}
    if full.get("sha256"):
        full["sig"] = priv.sign(DU.signing_payload(version, full["sha256"])).hex()
        signed += 1

    #Патч подписывается по `target_sha256` — по хешу ИТОГОВОГО .exe, а не самого патча.
    #Причина в шапке desktop_update.py: клиент перед подменой проверяет итоговый файл, и
    #подпись обязана относиться ровно к тому, что проверяется последним.
    for p in man.get("patches") or []:
        if p.get("target_sha256"):
            p["sig"] = priv.sign(
                DU.signing_payload(version, p["target_sha256"])).hex()
            signed += 1

    with io.open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    print("Подписано записей: %d -> %s" % (signed, manifest_path))
    if not DU.UPDATE_PUBLIC_KEYS:
        print("ВНИМАНИЕ: в desktop_update.UPDATE_PUBLIC_KEYS пусто — программа подпись "
              "проверять НЕ БУДЕТ. Впишите открытый ключ и пересоберите .exe.")
    return 0


def verify_manifest(manifest_path: str) -> int:
    """Проверить манифест ТЕМ ЖЕ кодом, которым его будет проверять программа.

    🔑 Почему не «есть ли поле sig»: подпись ЧУЖИМ ключом — это тоже поле. Проверка,
    разбирающая данные иначе, чем настоящий потребитель, не проверяет ничего, а лишь
    создаёт уверенность (урок `.claude/validate-agents.py`, оплаченный тремя неделями
    мёртвой сети граней). Поэтому зовём `desktop_update.release_signature_ok` — ровно
    ту функцию, что стоит в клиенте на обоих гейтах.

    ⚠️ Ворота нужны потому, что отказ здесь ТИХИЙ. Неподписанный манифест выкладывается
    совершенно успешно, сервер отдаёт его с кодом 200, проверка «версия обновилась»
    проходит — и только программа у человека молча перестаёт обновляться. Узнать об
    этом можно было бы при следующем выпуске, то есть через недели.
    """
    with io.open(manifest_path, encoding="utf-8") as f:
        man = json.load(f)
    version = DU.normalize(man.get("version") or "")
    if not version:
        print("В манифесте нет версии", file=sys.stderr)
        return 1

    if not DU.signature_required():
        #Ключ не заведён — проверять нечего, и это законное состояние (см. шапку
        #desktop_update.py). Но молчать нельзя: человек, зовущий --verify, ждёт ответа
        #про защиту, а получил бы «ок» от выключенной защиты.
        print("Ключ не заведён (UPDATE_PUBLIC_KEYS пуст) — подпись НЕ проверяется, "
              "поведение прежнее (только хеш).")
        return 0

    bad = []
    checked = 0
    entries = [("full", man.get("full") or {}, "sha256")]
    for i, p in enumerate(man.get("patches") or []):
        entries.append(("patches[%d]" % i, p, "target_sha256"))

    for name, entry, hash_field in entries:
        digest = entry.get(hash_field)
        if not digest:
            continue                      #записи нет — нечего и проверять
        checked += 1
        if not DU.release_signature_ok(version, digest, entry.get("sig") or ""):
            bad.append(name)

    if not checked:
        print("В манифесте нет ни одной записи с хешем", file=sys.stderr)
        return 1
    if bad:
        print("ПОДПИСЬ НЕ СХОДИТСЯ: %s" % ", ".join(bad), file=sys.stderr)
        print("Выкладывать НЕЛЬЗЯ: программы с заведённым ключом отвергнут это "
              "обновление, и парк молча останется на старой версии.", file=sys.stderr)
        return 1
    print("Подпись сходится у всех записей: %d (версия %s)" % (checked, version))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Подпись выпуска десктопа (Ed25519)")
    ap.add_argument("--gen-key", action="store_true", help="завести закрытый ключ")
    ap.add_argument("--manifest", help="подписать записи манифеста")
    ap.add_argument("--verify", help="проверить подписи манифеста (ворота выкладки)")
    ap.add_argument("--key", default=DEFAULT_KEY_PATH, help="путь к закрытому ключу")
    args = ap.parse_args()

    if args.gen_key:
        return gen_key(args.key)
    if args.manifest:
        return sign_manifest(args.manifest, args.key)
    if args.verify:
        return verify_manifest(args.verify)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
