#!/usr/bin/env bash
# Автодеплой из CI (задача «Выкладка на бой» в .github/workflows/ci.yml, 28.10.2026).
#
# Везёт на бой тот самый архив релиза, который в этом прогоне прошёл тесты, смоук и стенд
# с выдуманным колледжем. Ключ — секрет окружения production (только ветки Release-*),
# на сервере он умеет лишь status и deploy (deploy/ci/gb-ci-deploy).
#
# Выкладка только ВПЕРЁД по истории: если на бою коммит, который не предок этого (старый
# выпуск, чужая параллельная ветка, ручная выкладка неопубликованного), задача честно
# пропускается с пометкой — CI не откатит чужую работу сам.
set -euo pipefail
: "${GB_DEPLOY_KEY:?нет секрета GB_DEPLOY_KEY}"
: "${GB_DEPLOY_KNOWN_HOSTS:?нет секрета GB_DEPLOY_KNOWN_HOSTS}"
HOST=${GB_DEPLOY_HOST:-gbci@194.226.120.74}
SHA_COMMIT=${GITHUB_SHA:?}

install -m 700 -d "$HOME/.ssh"
printf '%s\n' "$GB_DEPLOY_KEY" > "$HOME/.ssh/gb_ci"
chmod 600 "$HOME/.ssh/gb_ci"
printf '%s\n' "$GB_DEPLOY_KNOWN_HOSTS" > "$HOME/.ssh/known_hosts"
SSH=(ssh -i "$HOME/.ssh/gb_ci" -o IdentitiesOnly=yes -o BatchMode=yes
     -o StrictHostKeyChecking=yes -o ConnectTimeout=25 -o ServerAliveInterval=15)

ART=$(ls dist-release/gradebook-*.tar.gz | head -1)
SHA=$(sha256sum "$ART" | cut -d' ' -f1)
echo "архив: $ART ($SHA)"

# Сервер и сайт выкладываются частями и могут стоять на разных коммитах (откатился один
# сайт — первый автодеплой 28.10.2026). Пропуск — только если на этом коммите обе части.
read -r server web < <("${SSH[@]}" "$HOST" status | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(*[((d.get(p) or {}).get("commit") or "-").split("+")[0] for p in ("server", "web")])')
echo "на бою: сервер ${server}, сайт ${web}"
if [ "$server" = "$SHA_COMMIT" ] && [ "$web" = "$SHA_COMMIT" ]; then
  echo "этот коммит уже на бою — выкладывать нечего"
  exit 0
fi
for part in "$server" "$web"; do
  if [ "$part" != "-" ] && ! git merge-base --is-ancestor "$part" "$SHA_COMMIT" 2>/dev/null; then
    echo "::notice title=Выкладка пропущена::На бою ${part:0:12}, и это не предок ${SHA_COMMIT:0:12}: ветка не продолжает то, что на бою. Выкладка — вручную (deploy/deploy-server.sh)."
    exit 0
  fi
done
"${SSH[@]}" "$HOST" "deploy $SHA_COMMIT $SHA" < "$ART"
