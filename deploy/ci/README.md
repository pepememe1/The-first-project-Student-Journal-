# Автодеплой из CI

С 28.10.2026 пуш в ветку `Release-*` сам доезжает до боя, если зелёно всё: синтаксис,
линтер, серверные и клиентские тесты, веб, безопасность, сборка артефакта, смоук и
стенд с выдуманным колледжем. На бой едет тот самый архив, который всё это прошёл.

## Как устроено

| шаг | где | что |
|---|---|---|
| сборка и проверки | `.github/workflows/ci.yml` | архив `tools/build_release.py`, смоук, `qa_stand.py --check` |
| выкладка | задача `deploy`, `deploy/ci/push_release.sh` | только вперёд по истории: на бою предок этого коммита, иначе пропуск с пометкой |
| вход на сервер | пользователь `gbci`, `/usr/local/sbin/gb-ci-deploy` | умеет только `status` и `deploy <коммит> <sha256>` |
| применение | `/root/gb-deploy/maintenance/apply_release.sh` | подмена, смоук, откат при сбое, письмо |
| итог | `/root/gb-deploy/DEPLOYED.json`, `/var/log/gb-ci-deploy.log` | что на бою и откуда |

Ручная выкладка (`deploy/deploy-server.sh`, `deploy/deploy-web.sh`) применяет архив тем же
`apply_release.sh` и кладёт на сервер его свежую копию. Письмо приходит о каждой выкладке
из CI (📦) и о каждом откате (🚨).

## Что стоит на сервере

- пользователь `gbci` (системный, оболочка `/bin/sh`, пароля нет);
- `/home/gbci/.ssh/authorized_keys`:
  `restrict,command="sudo -n /usr/local/sbin/gb-ci-deploy \"$SSH_ORIGINAL_COMMAND\"" ssh-ed25519 … gb-ci-deploy@github-actions`;
- `/etc/sudoers.d/gb-ci`: `Defaults:gbci !use_pty` и `gbci ALL=(root) NOPASSWD: /usr/local/sbin/gb-ci-deploy`.
  Без `!use_pty` sudo заводит псевдотерминал и не передаёт конец потока: архив по stdin
  не дочитывается никогда;
- отпечаток ключа CI — в `/etc/gb-alarm/trusted-keys`, иначе каждый вход CI был бы тревогой.

## Что стоит в GitHub

Окружение `production` (Settings → Environments), ветки — только `Release-*`. В нём два
секрета: `GB_DEPLOY_KEY` (закрытый ключ CI) и `GB_DEPLOY_KNOWN_HOSTS` (ключи сервера из
`ssh-keyscan`, сверенные с `known_hosts` администратора). Закрытого ключа нигде, кроме
GitHub, нет.

## Сменить ключ

```bash
ssh-keygen -t ed25519 -N "" -C gb-ci-deploy@github-actions -f gb_ci
# на сервере: заменить строку в /home/gbci/.ssh/authorized_keys и отпечаток в trusted-keys
gh secret set GB_DEPLOY_KEY --env production < gb_ci
rm gb_ci
```

## Выключить автодеплой

Удалить секрет `GB_DEPLOY_KEY` в окружении `production` — задача упадёт на первом шаге,
бой не тронется. Или на сервере закомментировать строку в `authorized_keys` пользователя `gbci`.
