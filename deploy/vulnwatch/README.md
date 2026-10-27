# Сторож уязвимостей и рубильник обслуживания

Заведены 27.10.2026 после октябрьских дыр PHP2Shell, nginx и утечки Railway.

## Сторож уязвимостей (`server/app/vuln_watch.py`)

Раз в час сверяет пакеты Python боевого venv с базой OSV и списком CISA KEV. Для дыры с
выпущенным исправлением ставит наименьшую исправленную версию, проверяет `pip check`,
перезапускает службу и ждёт `/health`; не поднялось — откатывает. Тем же запуском ставит
обновления безопасности ОС и Caddy (`apt-get install --only-upgrade`, без перезагрузки — её
делает ночной unattended-upgrades). Итог — в `/var/lib/gb-vulnwatch/state.json` и в вечернем
письме, раздел «Защита».

```bash
install -m 644 deploy/vulnwatch/gb-vulnwatch.service deploy/vulnwatch/gb-vulnwatch.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gb-vulnwatch.timer
systemctl start gb-vulnwatch.service && journalctl -u gb-vulnwatch -n 5   # прогон руками
cd /root/gb-deploy/server && ../venv/bin/python -m app.vuln_watch --dry     # только посмотреть
```

Не трогает torch (колесо с отдельного индекса) — дыры в нём только в письме.

## Рубильник обслуживания — два уровня, одна страница

Страница «технические работы» с Вектором в каске одна на оба уровня:
`web/public/maintenance/` (выкладывается вместе с сайтом, `deploy/deploy-web.sh`).

- **Мягкий — из админки** («Сервер» → «Технические работы», `server/app/maintenance.py`).
  API отвечает 503 всем, кроме входа и круга сервера у администратора («Сервер» с
  мониторингом, приманки, журнал действий, сессии, сам рубильник). Сайт переводит людей на
  страницу работ, у админа — плашка. Страница показывает ссылку «Вход для администратора».
- **Жёсткий — на машине**, когда само приложение лежит или его заменяют: Caddy отдаёт ту
  же страницу вместо всего сайта, админка тоже закрыта.

```bash
bash deploy/maintenance/gb_maintenance.sh on      # жёсткий: включить
bash deploy/maintenance/gb_maintenance.sh off     # выключить
bash deploy/maintenance/gb_maintenance.sh status
```
