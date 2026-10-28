#!/bin/bash
# Копия базы вне машины (27.10.2026): ПК администратора сам забирает ночную копию по ssh
# (tools/server-buttons/offsite_pull.ps1). Сервер до ПК не достучится — тот за роутером, —
# поэтому тянет ПК, а сервер только называет файл и принимает подтверждение.
#
#   gb_offsite.sh latest              имя, sha256 и размер свежей ночной копии
#   gb_offsite.sh confirm <имя> <sha> ПК скачал и сверил хеш — отметка для вечерней сводки
#
# Копия зашифрована ключом базы, то есть на ПК лежит шум без ключа.
set -euo pipefail
BACK=/root/gb-backups/auto
STATE=/var/lib/gb-backup

case "${1:-}" in
  latest)
    f=$(ls -1t "$BACK"/gradebook_*.db | head -1)
    echo "$(basename "$f") $(sha256sum "$f" | cut -d' ' -f1) $(stat -c %s "$f")"
    ;;
  confirm)
    name=$(basename "${2:-}")
    [[ "$name" =~ ^gradebook_[0-9_]+\.db$ ]] || { echo "чужое имя файла" >&2; exit 2; }
    [ "$(sha256sum "$BACK/$name" | cut -d' ' -f1)" = "${3:-}" ] || { echo "хеш не совпал" >&2; exit 3; }
    mkdir -p "$STATE"
    python3 -c 'import json, sys, time; json.dump({"ts": time.time(), "name": sys.argv[1]}, open(sys.argv[2], "w"))' \
      "$name" "$STATE/offsite.json"
    echo ok
    ;;
  *)
    echo "использование: $0 latest | confirm <имя> <sha256>" >&2
    exit 2
    ;;
esac
