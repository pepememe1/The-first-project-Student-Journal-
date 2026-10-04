# Вечерняя сводка на почту

`server/app/nightly_report.py` собирает за сутки активность, приманки (honeypot) и
состояние машины и шлёт красивое HTML-письмо через тот же SMTP, что письма регистрации.

## Установка на бою (один раз)

```bash
# 1. получатели — в server/.env (НЕ в коде: репозиторий публичный)
echo 'GRADEBOOK_REPORT_EMAIL=адрес@пример.ру' >> /root/gb-deploy/server/.env
# 2. база стран и провайдеров для приманок (публичная iptoasn, ~25 МБ)
cd /root/gb-deploy/server && ../venv/bin/python -m app.ipgeo --update
# 3. таймер
cp deploy/report/gb-report.service deploy/report/gb-report.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gb-report.timer
```

## Проверка

```bash
cd /root/gb-deploy/server
../venv/bin/python -m app.nightly_report --dry /tmp/report.html   # собрать, не отправлять
../venv/bin/python -m app.nightly_report --to адрес@пример.ру      # одно письмо руками
systemctl list-timers gb-report.timer                               # когда следующий запуск
journalctl -u gb-report -n 20                                       # что было в прошлый раз
```

Код выхода значим: 2 — не задан получатель, 3 — не настроен SMTP, 4 — письмо не ушло.

🔒 В письме только агрегированные числа: ни IP-адресов, ни логинов, ни ФИО — оно
хранится у почтового сервиса (Gmail — Google LLC), а п. 5.6.1 политики ВСГУТУ запрещает
трансграничную передачу ПДн. Адреса атакующих — в разделе «Приманки» админки.
