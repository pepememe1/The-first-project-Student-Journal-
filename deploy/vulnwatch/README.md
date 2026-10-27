# Сторож уязвимостей и рубильник обслуживания

Заведены 27.10.2026 после октябрьских дыр PHP2Shell, nginx и утечки Railway.

## Сторож уязвимостей (`server/app/vuln_watch.py`)

Раз в час сверяет пакеты Python боевого venv с базой OSV и списком CISA KEV. Для дыры с
выпущенным исправлением ставит наименьшую исправленную версию, проверяет `pip check`,
перезапускает службу и ждёт `/health`; не поднялось — откатывает. Тем же запуском ставит
обновления безопасности ОС и Caddy (`unattended-upgrade` без перезагрузки). Итог — в
`/var/lib/gb-vulnwatch/state.json` и в вечернем письме, раздел «Защита».

```bash
install -m 644 deploy/vulnwatch/gb-vulnwatch.service deploy/vulnwatch/gb-vulnwatch.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gb-vulnwatch.timer
systemctl start gb-vulnwatch.service && journalctl -u gb-vulnwatch -n 5   # первый прогон руками
cd /root/gb-deploy/server && ../venv/bin/python -m app.vuln_watch --dry     # только посмотреть
```

Не трогает torch (колесо с отдельного индекса) — дыры в нём только в письме.

## Рубильник обслуживания (`deploy/maintenance/gb_maintenance.sh`)

Весь сайт и API отвечают 503 со страницей «технические работы» (блок `@maintenance` в
`server/Caddyfile`). Перезагружать Caddy не нужно.

```bash
bash gb_maintenance.sh install   # положить страницу в /var/www/gb-maintenance (после правки страницы)
bash gb_maintenance.sh on        # включить
bash gb_maintenance.sh off       # выключить
```

Картинка Вектора — `deploy/maintenance/page/_maint/vector.webp`; заменить файл и снова
`install`.
