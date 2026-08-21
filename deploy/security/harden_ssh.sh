#!/usr/bin/env bash
# harden_ssh.sh — БЕЗОПАСНОЕ ужесточение SSH на боевом VPS.
#
# Запускать НА VPS ОТ ROOT:
#   scp -i ~/.ssh/gb_vps_ed25519 deploy/security/harden_ssh.sh root@194.226.120.74:/root/
#   ssh -i ~/.ssh/gb_vps_ed25519 root@194.226.120.74
#   bash /root/harden_ssh.sh
#
# Что делает: заводит sudo-пользователя gbadmin с ТВОИМ ключом, переносит SSH на порт
# 2222, ОТКЛЮЧАЕТ вход root и вход по паролю. Всё с АВТО-ОТКАТОМ: если через 7 минут ты
# не подтвердишь, что новый вход работает, sshd сам вернётся к прежнему конфигу.
#
# ⚠️ ГЛАВНОЕ ПРАВИЛО: НЕ ЗАКРЫВАЙ текущую root-сессию, пока не проверишь новый вход в
#    ДРУГОМ окне терминала. Авто-откат — страховка, а не повод не проверять.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "нужен root"; exit 1; }
IP=194.226.120.74

TS=$(date +%F_%H%M%S)
BK=/root/ssh-harden-backup-$TS
mkdir -p "$BK"
cp /etc/ssh/sshd_config "$BK"/
cp -r /etc/ssh/sshd_config.d "$BK"/ 2>/dev/null || true
echo "[1/6] бэкап конфигов: $BK"

# --- новый sudo-пользователь с ТЕМ ЖЕ ключом, что у root ---
id gbadmin >/dev/null 2>&1 || useradd -m -s /bin/bash gbadmin
usermod -aG sudo gbadmin
install -d -m700 -o gbadmin -g gbadmin /home/gbadmin/.ssh
cp /root/.ssh/authorized_keys /home/gbadmin/.ssh/authorized_keys
chown gbadmin:gbadmin /home/gbadmin/.ssh/authorized_keys
chmod 600 /home/gbadmin/.ssh/authorized_keys
# NOPASSWD sudo — вход по ключу, пароль всё равно отключаем; для автоматизации так надо.
echo 'gbadmin ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/90-gbadmin
chmod 440 /etc/sudoers.d/90-gbadmin
visudo -c >/dev/null
# случайный пароль на консольный фолбэк (в root-only файл, не в вывод)
pw=$(openssl rand -base64 18); echo "gbadmin:$pw" | chpasswd
umask 077; echo "$pw" >/root/gbadmin_pw.txt; chmod 600 /root/gbadmin_pw.txt
echo "[2/6] gbadmin готов (ключ + NOPASSWD sudo). Пароль -> /root/gbadmin_pw.txt (600)"

# --- нейтрализуем конфликтующие drop-in (Ubuntu кладёт туда PasswordAuthentication yes,
#     и он ПЕРЕБИВАЕТ главный конфиг — первое прочитанное значение выигрывает) ---
for f in /etc/ssh/sshd_config.d/*.conf; do
  [ -f "$f" ] || continue
  sed -i -E 's/^[[:space:]]*(PasswordAuthentication|PermitRootLogin|Port)\b/#gb-was &/I' "$f"
done
# и в главном конфиге тоже гасим старые строки
sed -i -E 's/^[[:space:]]*(PasswordAuthentication|PermitRootLogin|Port)\b/#gb-was &/I' /etc/ssh/sshd_config

# --- наши настройки. Порт 22 ОСТАВЛЯЕМ временно, чтобы не отрезать себя до проверки ---
cat >/etc/ssh/sshd_config.d/99-gb-hardening.conf <<'EOF'
Port 2222
Port 22
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
EOF
echo "[3/6] hardening записан: порт 2222 (+22 временно), root off, пароль off"

# --- фаервол: открыть 2222 (и 22 пока) ---
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 2222/tcp >/dev/null; ufw allow 22/tcp >/dev/null
  echo "[4/6] ufw: открыт 2222 (и 22 временно)"
else
  echo "[4/6] ufw не активен — локальный фаервол не трогаю. ⚠️ Проверь ВНЕШНИЙ фаервол reg.ru: порт 2222 должен быть открыт снаружи!"
fi

# --- проверка синтаксиса и ЭФФЕКТИВНЫХ значений (после всех include) ---
sshd -t
echo "[5/6] эффективные настройки:"
sshd -T | grep -iE '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication) '

# --- АВТО-ОТКАТ через 7 минут ---
cat >/root/ssh-revert-$TS.sh <<EOF
#!/usr/bin/env bash
cp $BK/sshd_config /etc/ssh/sshd_config
rm -f /etc/ssh/sshd_config.d/99-gb-hardening.conf
cp -rf $BK/sshd_config.d/. /etc/ssh/sshd_config.d/ 2>/dev/null || true
systemctl restart ssh 2>/dev/null || systemctl restart sshd
echo "\$(date -Is) АВТО-ОТКАТ выполнен" >>/root/ssh-harden.log
EOF
chmod +x /root/ssh-revert-$TS.sh
setsid bash -c "sleep 420; /root/ssh-revert-$TS.sh" </dev/null >/dev/null 2>&1 &
REV=$!
echo "[6/6] АВТО-ОТКАТ вооружён (PID $REV) — сработает через 7 мин, если не отменишь."

systemctl restart ssh 2>/dev/null || systemctl restart sshd
echo
echo "=================================================================="
echo " НЕ ЗАКРЫВАЯ это окно, в ДРУГОМ терминале проверь новый вход:"
echo
echo "   ssh -i ~/.ssh/gb_vps_ed25519 -p 2222 gbadmin@$IP 'sudo whoami'"
echo "   -> должно вывести:  root"
echo
echo " РАБОТАЕТ? Закрепи (убери порт 22 и отмени откат):"
echo "   kill $REV"
echo "   sed -i '/^Port 22\$/d' /etc/ssh/sshd_config.d/99-gb-hardening.conf"
echo "   command -v ufw >/dev/null && ufw delete allow 22/tcp"
echo "   systemctl restart ssh"
echo
echo " НЕ РАБОТАЕТ? Ничего не делай — через 7 мин авто-откат вернёт вход root:22."
echo "=================================================================="
echo
echo " ⚠️ После закрепления мои будущие команды к VPS пойдут так:"
echo "    ssh -i ~/.ssh/gb_vps_ed25519 -p 2222 gbadmin@$IP 'sudo <команда>'"
echo "    — обнови мне правило: Bash(ssh -i ~/.ssh/gb_vps_ed25519 -p 2222 *)"
