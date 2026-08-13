"""
test_server_admin.py — раздел «Сервер» на десктопе: разбор ответов и защита от опечаток.

Сам SSH здесь не дёргается: тест чужого клиента — не наш тест. Проверяется то, что
написано нами и может тихо сломаться:

  • сборка команды ssh (без ключа/порта человек молча не подключится);
  • разбор ответа сервера (одна съехавшая метка — и вкладка показывает нули);
  • распознавание опасных команд (единственное, что стоит между уставшим админом и
    `rm -rf` не по тому пути).
"""
from desktop import server_admin


# ── Опасные команды ──────────────────────────────────────────────────────────────────
def test_destructive_commands_are_recognised():
    """Не запрет, а требование подтвердить. Разница между
    `rm -rf /root/gb-deploy/tmp` и `rm -rf /root/gb-deploy` — один символ."""
    for cmd in [
        "rm -rf /root/gb-deploy",
        "rm -fr /root",
        "sudo rm -rf --no-preserve-root /",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
        "reboot",
        "userdel gradebook",
        "DROP TABLE users",
        "chmod -R 777 /root",
    ]:
        assert server_admin.is_dangerous(cmd), f"не распознано как опасное: {cmd}"


def test_everyday_commands_are_not_flagged():
    """Ложное срабатывание не безобидно: если подтверждения требует каждая вторая
    команда, человек перестаёт их читать — и подтвердит настоящую."""
    for cmd in [
        "systemctl status gradebook",
        "journalctl -u gradebook -n 50 --no-pager",
        "df -h",
        "du -sh /root/gb-deploy/*",
        "ls -la /root/gb-backups",
        "systemctl restart gradebook",
        "rm /tmp/one-file.log",          # без -rf это обычная уборка
        "cat /etc/os-release",
    ]:
        assert not server_admin.is_dangerous(cmd), f"ложная тревога: {cmd}"


# ── Сборка команды ssh ───────────────────────────────────────────────────────────────
def test_ssh_command_uses_key_and_user():
    argv = server_admin._ssh_argv({"host": "10.0.0.5", "user": "gb",
                                   "key": "/home/u/.ssh/id_ed25519", "port": "2222"})
    assert "gb@10.0.0.5" in argv
    assert "-i" in argv and "/home/u/.ssh/id_ed25519" in argv
    assert "-p" in argv and "2222" in argv
    #IdentitiesOnly обязателен: иначе ssh-агент успевает предложить десяток чужих
    #ключей, и сервер рвёт соединение по «too many authentication failures» — при том
    #что нужный ключ указан прямо здесь.
    assert "IdentitiesOnly=yes" in argv


def test_ssh_never_asks_questions_interactively():
    """BatchMode обязателен. Спросить пароль или «доверять этому хосту?» тут некому:
    процесс без консоли просто повис бы навсегда, а вкладка — вместе с ним."""
    argv = server_admin._ssh_argv({"host": "h", "user": "root"})
    assert "BatchMode=yes" in argv
    #accept-new, а НЕ no: первый ключ хоста принимаем, подмену — отвергаем. Полное `no`
    #приняло бы и подменённый ключ, то есть ровно ту атаку, от которой он защищает.
    assert "StrictHostKeyChecking=accept-new" in argv
    assert "StrictHostKeyChecking=no" not in argv


def test_missing_host_is_refused():
    import pytest
    with pytest.raises(RuntimeError):
        server_admin._ssh_argv({"user": "root"})


# ── Разбор ответа сервера ────────────────────────────────────────────────────────────
_SAMPLE = """###HOST
cv7600409.novalocal
Linux 5.15.0-101-generic
###UPTIME
843201.55
###LOAD
0.08 0.12 0.09
###CPU
1
###MEM
MemTotal:         983040 kB
MemAvailable:     201234 kB
SwapTotal:       2097152 kB
SwapFree:        1800000 kB
###DISK
/dev/sda1 10508660736 7301444608 2667220992 74% /
###SERVICES
gradebook=active
caddy=active
###DIRS
734003200\t/root/gb-deploy
1073741824\t/root/gb-backups
###DB
54525952 /root/gb-deploy/server/gradebook.db
###BACKUP
predeploy-20260731_150000
###END
"""


def test_metrics_are_parsed(monkeypatch):
    monkeypatch.setattr(server_admin, "run",
                        lambda server, cmd, timeout=0: {"ok": True, "out": _SAMPLE,
                                                        "err": "", "code": 0})
    m = server_admin.metrics({"host": "h", "user": "root"})
    assert m["ok"] is True
    assert m["host"] == "cv7600409.novalocal"
    assert m["cpu_count"] == 1
    assert m["services"] == {"gradebook": "active", "caddy": "active"}
    assert m["disk"]["total"] == 10508660736
    assert m["disk"]["free"] == 2667220992
    #MemAvailable, а не MemFree: под кэш ядро отдаёт почти всю память, и по MemFree
    #на живом сервере всегда кажется, что памяти нет.
    assert m["memory"]["total"] == 983040 * 1024
    assert m["memory"]["used"] == (983040 - 201234) * 1024
    assert m["memory"]["swap_used"] == (2097152 - 1800000) * 1024
    assert m["database"]["size"] == 54525952
    assert m["latest_backup"] == "predeploy-20260731_150000"
    assert {d["path"] for d in m["dirs"]} == {"/root/gb-deploy", "/root/gb-backups"}


def test_unreachable_server_reports_the_reason(monkeypatch):
    """Пустая карточка без объяснения читается как «всё сломалось». Причина обязана
    доехать до человека — по ней он и поймёт, что дело в ключе, а не в сервере."""
    monkeypatch.setattr(server_admin, "run",
                        lambda server, cmd, timeout=0: {
                            "ok": False, "out": "", "code": 255,
                            "err": "Permission denied (publickey)."})
    m = server_admin.metrics({"host": "h", "user": "root"})
    assert m["ok"] is False
    assert "publickey" in m["error"]


def test_partial_output_does_not_crash(monkeypatch):
    """Сервер мог оборвать вывод на середине (упало соединение, кончилась память).
    Разбор обязан отдать то, что успело приехать, а не исключение на всю страницу."""
    monkeypatch.setattr(server_admin, "run",
                        lambda server, cmd, timeout=0: {
                            "ok": True, "code": 0, "err": "",
                            "out": "###HOST\nhost1\n###MEM\nMemTotal: мусор\n###DISK\nх"})
    m = server_admin.metrics({"host": "h", "user": "root"})
    assert m["ok"] is True and m["host"] == "host1"
    assert m["disk"] == {} and m["memory"]["total"] == 0


# ── Перенос ──────────────────────────────────────────────────────────────────────────
def test_migration_plan_warns_about_downtime():
    plan = server_admin.migration_plan({"host": "old", "user": "root"},
                                       {"host": "new", "user": "root"})
    assert [s["id"] for s in plan["steps"]] == [sid for sid, _ in server_admin.MIGRATION_STEPS]
    #Человек обязан узнать про простой ДО запуска, а не по звонку из деканата.
    assert "остановлен" in plan["warning"].lower()


def test_migration_order_puts_backup_before_stop():
    """Порядок шагов — не украшение. Копия снимается ДО остановки и ДО копирования:
    иначе единственный откат появляется уже после того, как что-то пошло не так."""
    ids = [sid for sid, _ in server_admin.MIGRATION_STEPS]
    assert ids.index("backup_source") < ids.index("stop_source") < ids.index("copy_data")
    assert ids.index("check_space") < ids.index("copy_data")
    assert ids[-1] == "verify"


def test_unknown_step_is_refused():
    out = server_admin.migrate_step("выдуманный", {"host": "a"}, {"host": "b"})
    assert out["ok"] is False and "Неизвестный шаг" in out["hint"]


# ── Пароль SSH: хранение и границы ───────────────────────────────────────────────────
def test_password_is_stored_protected_and_round_trips():
    """Пароль шифруется DPAPI (§4.7): украденный файл настроек бесполезен на другом
    компьютере. Совсем не хранить нельзя — тогда его вводили бы на каждую команду, и он
    оказался бы в блокноте на рабочем столе."""
    blob = server_admin._protect("тайна-123")
    assert blob and blob != "тайна-123", "пароль не должен лежать открытым текстом"
    assert server_admin._password({"pw": blob}) == "тайна-123"


def test_password_never_reaches_the_page():
    """Страницу рисует браузерный движок: всё, что ей отдали, попадает в память процесса
    и в инструменты разработчика. Наружу уходит только признак наличия пароля."""
    public = server_admin._public({"id": "a", "host": "h", "pw": "зашифровано"})
    assert "pw" not in public
    assert public["has_password"] is True
    assert server_admin._public({"id": "a"})["has_password"] is False


def test_empty_password_means_absent_not_broken():
    assert server_admin._protect("") == ""
    assert server_admin._password({}) == ""
    assert server_admin._password({"pw": "не-base64-и-не-dpapi"}) == ""


def test_password_login_takes_the_paramiko_path(monkeypatch):
    """Системный ssh запущен с BatchMode и пароль ввести не может — при сохранённом
    пароле обязан выбираться другой транспорт, иначе человек видел бы «Permission
    denied» вместо подключения."""
    called = {}

    def fake(server, command, timeout):
        called["args"] = (command, timeout)
        return {"ok": True, "code": 0, "out": "", "err": ""}

    monkeypatch.setattr(server_admin, "_run_with_password", fake)
    server = {"host": "h", "user": "root", "pw": server_admin._protect("p")}
    server_admin.run(server, "uptime")
    assert called["args"][0] == "uptime"


def test_key_login_does_not_touch_paramiko(monkeypatch):
    """И обратное: без пароля paramiko не нужен вовсе — он и не должен подключаться."""
    def boom(*a, **k):
        raise AssertionError("парольный путь вызван без пароля")

    monkeypatch.setattr(server_admin, "_run_with_password", boom)
    monkeypatch.setattr(server_admin.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": b"ok",
                                                       "stderr": b""})())
    res = server_admin.run({"host": "h", "user": "root", "key": ""}, "uptime")
    assert res["ok"] is True


# ── Управление службами ──────────────────────────────────────────────────────────────
def test_only_our_services_can_be_controlled():
    """`systemctl` умеет останавливать что угодно, включая ssh, — и тогда до сервера
    больше нечем достучаться. Кнопка обязана быть безопасной по построению, а не по
    внимательности того, кто её нажимает."""
    for name in ("sshd", "ssh", "systemd-networkd", "../gradebook", ""):
        out = server_admin.service_action({"host": "h"}, name, "stop")
        assert out["ok"] is False and "нельзя" in out["hint"]


def test_only_three_actions_are_allowed():
    for action in ("mask", "disable", "kill", ""):
        out = server_admin.service_action({"host": "h"}, "gradebook", action)
        assert out["ok"] is False


def test_stopping_reports_it_took_the_site_down(monkeypatch):
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {"ok": True, "code": 0,
                                                 "out": "inactive\n", "err": ""})
    out = server_admin.service_action({"host": "h"}, "gradebook", "stop")
    assert out["ok"] is True and out["state"] == "inactive"
    assert "недоступны" in out["hint"], "человек обязан узнать, что сайт сейчас лежит"


def test_failed_start_points_at_the_log(monkeypatch):
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {"ok": False, "code": 1,
                                                 "out": "failed\n", "err": ""})
    out = server_admin.service_action({"host": "h"}, "gradebook", "start")
    assert out["ok"] is False and "journalctl" in out["hint"]


# ── Резервные копии ──────────────────────────────────────────────────────────────────
def test_backup_reports_the_created_file(monkeypatch):
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {
                            "ok": True, "code": 0, "err": "",
                            "out": "-rw-r--r-- 1 root root 5242880 backup-20260731_170000.tar.gz\n"
                                   "СОЗДАНО:backup-20260731_170000.tar.gz\n"})
    out = server_admin.make_backup({"host": "h"})
    assert out["ok"] is True
    assert out["name"] == "backup-20260731_170000.tar.gz"
    # Архив содержит ключ шифрования базы — про это обязаны предупредить прямо здесь.
    assert "облако" in out["hint"]


def test_backup_refuses_when_disk_is_full(monkeypatch):
    """Оборвавшийся tar оставляет архив, который выглядит как настоящий. Узнать о его
    непригодности при восстановлении — худший из возможных моментов."""
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {"ok": False, "code": 28, "out": "",
                                                 "err": "МАЛО МЕСТА: нужно 300 МБ"})
    out = server_admin.make_backup({"host": "h"})
    assert out["ok"] is False and "места" in out["hint"]


def test_backup_without_marker_is_a_failure(monkeypatch):
    """Нет строки «СОЗДАНО» — значит файла нет, каким бы ни был код возврата. Считать
    такое успехом означало бы показать «копия создана» там, где её нет."""
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {"ok": True, "code": 0, "out": "", "err": ""})
    assert server_admin.make_backup({"host": "h"})["ok"] is False


def test_backup_listing_is_parsed(monkeypatch):
    monkeypatch.setattr(server_admin, "run",
                        lambda s, c, timeout=0: {
                            "ok": True, "code": 0, "err": "",
                            "out": "###SIZES\n"
                                   "5242880\t2026-07-31 17:00\tbackup-a.tar.gz\n"
                                   "1048576\t2026-07-30 09:15\tbackup-b.tar.gz\n"
                                   "###FREE\n2667220992\n"})
    out = server_admin.list_backups({"host": "h"})
    assert [i["name"] for i in out["items"]] == ["backup-a.tar.gz", "backup-b.tar.gz"]
    assert out["total_size"] == 5242880 + 1048576
    assert out["free"] == 2667220992
    assert out["latest"] == "2026-07-31 17:00"


def test_download_refuses_a_path_outside_the_backup_dir():
    """Имя файла приходит со страницы. Без проверки `../../etc/shadow` уехал бы на
    компьютер администратора обычной кнопкой «скачать»."""
    for bad in ("../../etc/shadow", "a/b.tar.gz", "..\\win.ini", ""):
        assert server_admin.download_backup({"host": "h"}, bad)["ok"] is False


# ── Установка ключа ──────────────────────────────────────────────────────────────────
def test_install_key_explains_what_to_do_without_a_key(monkeypatch, tmp_path):
    """Без открытого ключа кнопка обязана сказать, ЧТО сделать, а не просто не сработать."""
    monkeypatch.setattr(server_admin.os.path, "expanduser", lambda p: str(tmp_path))
    out = server_admin.install_key({"host": "h", "key": str(tmp_path / "нет")})
    assert out["ok"] is False and "ssh-keygen" in out["hint"]


def test_install_key_is_idempotent(monkeypatch, tmp_path):
    """Повторное нажатие не должно плодить одинаковые строки в authorized_keys."""
    pub = tmp_path / "id_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAAC3Nz test@pc", encoding="utf-8")
    sent = {}

    def fake(server, command, timeout=0):
        sent["cmd"] = command
        return {"ok": True, "code": 0, "out": "ключ-на-месте\n", "err": ""}

    monkeypatch.setattr(server_admin, "run", fake)
    out = server_admin.install_key({"host": "h", "key": str(tmp_path / "id_ed25519")})
    assert out["ok"] is True
    assert "grep -qxF" in sent["cmd"], "дозапись без проверки задваивала бы ключ"
    assert "убрать пароль" in out["hint"]


def test_suggested_host_comes_from_the_configured_server():
    """Адрес в форме подставляется тот, на который программа и так синхронизируется:
    это ровно та машина, состояние которой человек и пришёл смотреть."""
    host = server_admin.suggested_host()
    assert "://" not in host and "/" not in host, host
