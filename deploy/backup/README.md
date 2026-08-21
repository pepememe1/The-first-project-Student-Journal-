# Автобэкап боевой БД (суточный, зашифрованный, с проверкой)

Суточный снимок SQLCipher-базы, который сам себя проверяет и сам чистит старьё.

## Что делает `gb_backup.sh`

1. **Консистентный снимок** через `VACUUM INTO` (не `cp` — рядом пишется WAL). Копия
   остаётся **зашифрованной** тем же ключом, что и боевая база.
2. **Верификация**: снимок открывается тем же ключом, проходит `PRAGMA integrity_check`
   и должен содержать пользователей. Не прошёл — снимок удаляется, а не выдаётся за годный.
3. `chmod 600` на снимок.
4. **Ротация**: держим последние `KEEP=14` снимков в `/root/gb-backups/auto/`. Ручные
   снимки (`/root/gb-backups/pre-*`) НЕ трогаются.

Ключ БД читается из `server/.env` и **не попадает** ни в argv (виден в `ps`), ни в лог.
Лог — `/var/log/gb-backup.log`.

## Расписание

`gb-backup.timer` → `OnCalendar=*-*-* 00:00:00 Asia/Irkutsk` — **00:00 по Улан-Удэ**
(UTC+8), независимо от таймзоны машины. `Persistent=true` — пропущенный запуск (машина
была выключена) наверстывается при старте.

## Установка на VPS

```bash
install -m 700 deploy/backup/gb_backup.sh /root/gb-deploy/tools/gb_backup.sh
install -m 644 deploy/backup/gb-backup.service /etc/systemd/system/gb-backup.service
install -m 644 deploy/backup/gb-backup.timer   /etc/systemd/system/gb-backup.timer
systemctl daemon-reload
systemctl enable --now gb-backup.timer
systemctl start gb-backup.service      # прогнать один раз сейчас и проверить
cat /var/log/gb-backup.log
systemctl list-timers gb-backup.timer  # когда следующий запуск
```

## Чего этот бэкап НЕ закрывает (честно)

- **Off-box.** Снимки лежат на той же машине. Пожар/потеря диска → потеря и базы, и
  копий. Реальный DR — увозить снимки на другую машину (следующая задача).
- **Ключ.** Снимки зашифрованы ключом из `.env` на этой же машине. Умрёт машина вместе с
  `.env` — зашифрованные копии станут бесполезны. Ключ нужно держать и отдельно (эскроу).
- Это дополняет, а не заменяет ручные `pre-*` снимки перед опасными операциями.
