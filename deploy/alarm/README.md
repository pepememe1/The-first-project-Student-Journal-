# Сторож тревог

`server/app/alarm_watch.py` (служба `gb-alarm`) шлёт письмо сразу, не дожидаясь вечерней
сводки, когда:

- на сервер вошли ключом, которого нет в `/etc/gb-alarm/trusted-keys`, или по паролю;
- кто-то вошёл в консоль сервера (VNC в панели reg.ru);
- упала служба: `gradebook`, `caddy`, `fail2ban`, `ssh`, `ufw`, таймеры копий, сводки и
  уязвимостей;
- ядро убило процесс из-за нехватки памяти;
- изменились ключи входа, учётные записи ОС, `sudoers`, настройки sshd, cron, юниты systemd;
- кто-то вошёл учёткой-приманкой (утёк дамп базы);
- журнал или сайт не отвечают три минуты подряд: сторож сам перезапускает службу и пишет,
  а когда всё поднялось — пишет «снова работает»;
- на диске осталось меньше 8 %.

Адресов в письме нет — только отпечаток, страна и провайдер (письмо лежит у почтового
сервиса). Получатели и SMTP те же, что у сводки: `GRADEBOOK_REPORT_EMAIL` и
`GRADEBOOK_SMTP_*` в `server/.env`.

## Установка на бою (один раз)

```bash
# свои ключи — все, что пускают на сервер сейчас; вход ими тревогу не поднимает
install -d -m 700 /etc/gb-alarm
{ echo "# отпечаток подпись — вход этими ключами не будит сторожа";
  for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do ssh-keygen -lf "$f"; done \
    | awk '{print $2, $3}' | sort -u; } > /etc/gb-alarm/trusted-keys
chmod 600 /etc/gb-alarm/trusted-keys
cp deploy/alarm/gb-alarm.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gb-alarm
```

Новый человек с ключом — дописать его отпечаток в `trusted-keys` (`ssh-keygen -lf ключ.pub`).
Правка этого файла сама придёт письмом: так и задумано.

## Проверка

```bash
cd /root/gb-deploy/server && ../venv/bin/python -m app.alarm --test   # проверочное письмо
journalctl -u gb-alarm -n 30                                           # что видел сторож
cat /var/lib/gb-alarm/state.json                                      # история тревог
```

Скрипты, которые останавливают журнал намеренно (восстановление базы), пишут в
`/run/gb-alarm.pause` время, до которого сторож не перезапускает службы.
