"""
test_done_docs.py — КАТАЛОГ «СДЕЛАНО» ОБЯЗАН ГОВОРИТЬ ПРАВДУ.

`docs/done/` заведён 10.09.2026, чтобы на вопрос «это уже реализовано или ещё нет»
отвечал состав папки, а не память. Но папка с названием «сделано» — это ровно тот вид
документа, который в нашем проекте уже трижды начинал врать: «Playwright стоит с 18.08»
(не стоял), «47 маркетинг-скиллов» (был один), «на бою PostgreSQL» (не было никогда).
Каждый раз намерение записывали как факт, и по факту потом строили планы.

Поэтому у каждого перенесённого плана в `docs/done/README.md` названо ДОКАЗАТЕЛЬСТВО —
файл продукта, без которого плана бы не существовало, — и этот прогон проверяет, что
файл на месте. Удалят `canary.py`, а `PLAN-HONEYPOT.md` оставят в «сделано» — покраснеет.

⚠️ ЧЕСТНАЯ ГРАНИЦА, и её надо назвать вслух. Проверяется НАЛИЧИЕ файла, а не то, что
он делает. Это сторож против «предмет плана удалили, а документ остался», а НЕ
доказательство, что план выполнен целиком: последнее машиной не проверяется вовсе и
держится на разборе человеком. Делать вид, что прогон закрывает и это, нельзя — иначе
сторож сам станет источником ложной уверенности, против которой заведён.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DONE = os.path.join(ROOT, "docs", "done")
README = os.path.join(DONE, "README.md")

#Пути в README пишутся прозой вперемешку с текстом, поэтому доказательства перечислены
#здесь отдельным списком: разбор прозы регулярками — ровно тот приём, из-за которого
#`validate-agents.py` три недели «проверял» и не проверял ничего.
#🔥 КАТАЛОГИ ПРОПУСКАЕМ ПО ИМЕНИ, А НЕ ПО ПОДСТРОКЕ ПУТИ (нашёл Полковник 22.09.2026).
#Прежде оба обхода ниже сравнивали «.git», «dist» с АБСОЛЮТНЫМ путём: «.git» совпадал
#с «.github» — ci.yml не проверялся никогда, а клон в папке с «dist» в пути (C:\distr\…)
#отбросил бы ВСЕ каталоги, и тест зеленел бы, не прочитав ни одного файла.
_SKIP_DIR_NAMES = {"node_modules", "graphify-out", ".git", "dist", "__pycache__",
                   #локальные сборки и кэши — исходников в них нет, а nuitka_out весит
                   #полтора гигабайта и растягивал проверку ссылок до 15 секунд
                   "nuitka_out", ".gradle", "ota_bundles", ".mypy_cache", ".pytest_cache",
                   ".ruff_cache", ".venv", "venv"}


def _walk_docs_tree(root):
    """os.walk по репозиторию без служебных каталогов и без docs/done (снимки прошлого)."""
    done = os.path.normcase(os.path.normpath(os.path.join(root, "docs", "done")))
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIR_NAMES and
                   os.path.normcase(os.path.normpath(os.path.join(base, d))) != done]
        yield base, files


EVIDENCE = {
    "PLAN-2.10.md": ["server/app/routers/web/curator.py"],
    "PLAN-3.1.md": ["server/app/routers/parent.py"],
    "PLAN-ACTIVITIES.md": ["server/app/routers/activities.py",
                           "server/app/activity_state.py",
                           "web/src/utils/wheelGeometry.js"],
    "PLAN-COURSE-ROLLOVER.md": ["server/app/course_rollover.py"],
    "PLAN-EASTER-EGGS.md": ["server/app/easter_eggs.py",
                            "web/src/config/achievements.js"],
    "PLAN-HONEYPOT.md": ["server/app/canary.py", "server/app/throttle.py"],
    "PLAN-PACKAGING.md": ["build_nuitka.sh"],
    "PLAN-ZET.md": ["study_hours.py"],
    "MESSENGER-PLAN.md": ["server/app/routers/messenger/_common.py"],
    "MESSENGER-PLAN-DISCORD-ADDONS.md": ["server/app/routers/messenger/messages.py"],
    "MESSENGER-ATTACHMENTS-PLAN.md": ["server/app/storage.py",
                                      "server/app/routers/messenger/attachments.py"],
    "PERF-MESSENGER.md": ["web/src/utils/livePolling.js"],
    "TTS-PLAN.md": ["server/app/tts_service.py", "web/src/stores/tts.js"],
    "PENTEST-3.7.8.md": ["server/app/storage.py"],
}


def _done_plans():
    """Планы, лежащие в docs/done (README сам планом не является)."""
    if not os.path.isdir(DONE):
        return []
    return sorted(f for f in os.listdir(DONE)
                  if f.endswith(".md") and f != "README.md")


@pytest.mark.parametrize("plan", _done_plans())
def test_every_done_plan_still_has_its_subject_in_the_product(plan):
    """У плана в «сделано» обязан существовать названный файл продукта."""
    assert plan in EVIDENCE, (
        "план %s лежит в docs/done, но доказательства для него не названо. "
        "Либо впишите файл продукта в EVIDENCE и в README, либо верните план в docs/ — "
        "«сделано» без доказательства это просто утверждение" % plan)
    for rel in EVIDENCE[plan]:
        assert os.path.exists(os.path.join(ROOT, rel)), (
            "%s числится сделанным, но названного доказательства нет: %s. "
            "Либо предмет плана удалили (тогда документ не «сделано»), либо файл "
            "переименовали и запись устарела" % (plan, rel))


def test_the_evidence_list_has_no_dead_entries():
    """И обратная половина: в EVIDENCE нет записей о планах, которых там уже нет.

    Список без мёртвых записей — правило проекта. Мёртвая строка выглядит как знание,
    а на деле описывает файл, который кто-то давно вернул в работу.
    """
    dead = sorted(set(EVIDENCE) - set(_done_plans()))
    assert not dead, ("EVIDENCE называет планы, которых в docs/done нет: %s" % dead)


def test_readme_mentions_every_plan_that_lies_there():
    """Каталог и его оглавление не имеют права разойтись.

    Разойдутся они молча: файл переносят одной командой, а таблицу в README дописать
    забывают — и «сделано» перестаёт быть списком, становясь просто папкой.
    """
    assert os.path.exists(README), "у docs/done нет README — каталог без оглавления"
    with open(README, encoding="utf-8") as f:
        text = f.read()
    missing = [p for p in _done_plans() if p not in text]
    assert not missing, ("в docs/done лежат планы, не названные в его README: %s"
                         % missing)


def test_no_stale_path_to_a_moved_plan_is_left_in_the_code():
    """🔒 ОБРАТНЫЙ ХОД переноса: старый путь `docs/<план>.md` не должен остаться нигде.

    Путь в докстринге — такая же поверхность отказа, как код: ссылка на прежнее место
    отправит следующего читателя искать несуществующий файл и решить, что план потеряли.
    Правило записано в CLAUDE.md («комментарий и докстринг — тоже поверхность отказа») и
    уже трижды покупалось настоящими ошибками.

    🔥 И этот сторож поймал настоящее в первый же прогон: массовая правка ссылок прошла
    только по файлам ПОД GIT, а `.claude/agents/gb-extract.md` и `.codex/CODEX.md` в git
    не лежат — там пути остались старыми и никто бы этого не заметил.
    ⚠️ Пример прежнего пути здесь НЕ приводится дословно намеренно: та же массовая
    замена переписала бы его вместе с настоящими ссылками, и объяснение превратилось бы
    в собственную противоположность. Это уже случилось при написании файла.
    """
    exts = (".py", ".js", ".mjs", ".vue", ".sh", ".md", ".txt", ".yml")
    #🔥 СНИМКИ ПРОШЛОГО ПРОПУСКАЕМ, и это не послабление сторожу.
    #`CLAUDE.md` и `docs/HISTORY.md` вне git и сливаются руками, поэтому рядом с ними
    #живут датированные копии: предок для следующего трёхстороннего слияния и «как было
    #до». Такая копия ОБЯЗАНА содержать прежние пути — она описывает состояние на свою
    #дату, и «починить» её значит подделать снимок, по которому потом сверяются.
    #Требовать от них актуальности — то же, что требовать её от git-истории.
    #⚠️ Узнаём их по ИМЕНИ (`.bak-`/`.base-` + дата), а не по расширению: обычный `.md`
    #в репозитории по-прежнему проверяется весь.
    snapshots = (".bak-", ".base-")
    bad = []
    for base, files in _walk_docs_tree(ROOT):
        for fn in files:
            if not fn.endswith(exts):
                continue
            if any(s in fn for s in snapshots):
                continue                       #датированный снимок — см. объяснение выше
            path = os.path.join(base, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for plan in _done_plans():
                #Ищем ровно «docs/<план>», не предварённое «done/».
                for m in re.finditer(r"docs/" + re.escape(plan), text):
                    if not text[max(0, m.start() - 5):m.start()].endswith("done/"):
                        bad.append("%s -> docs/%s" % (os.path.relpath(path, ROOT), plan))
                        break
    assert not bad, ("остались ссылки на прежнее место перенесённых планов:\n  "
                     + "\n  ".join(sorted(set(bad))))


# ─────────────────────────────────────────────────────────────────────────────────
# 🗄 docs/done/outdated/ — УСТАРЕВШИЕ СНИМКИ (21.09.2026)
# ─────────────────────────────────────────────────────────────────────────────────
# 🔥 Перенос 20.09.2026 (Release 3.9.5.1) был сделан НАПОЛОВИНУ: копии в `outdated/`
# закоммитили, а удаление оригиналов в коммит не попало. Сутки в репозитории жили
# восемь побайтных пар — и `docs/PLAN-AI-SERVER.md` на прежнем месте продолжал выглядеть
# живым планом (PostgreSQL на бою, пакет `vector/`), на который ссылались
# `PRICING-AND-PITCH.md` и `README.md`. А README самой папки уверял, что старые ссылки
# «держит test_done_docs.py», — этот файл про `outdated/` не знал НИЧЕГО.
#
# Прежнее место каждого снимка названо здесь отдельным списком, а не выведено из прозы
# README (тот же довод, что у EVIDENCE выше).
OUTDATED = os.path.join(DONE, "outdated")
OUTDATED_ORIGIN = {
    "NOT-DONE-3.8.6.md": "docs/NOT-DONE-3.8.6.md",
    "PLAN-AI-SERVER.md": "docs/PLAN-AI-SERVER.md",
    "PLAN-PROD-2026-09.md": "docs/PLAN-PROD-2026-09.md",
    "TECH-DEBT-PLAN.md": "docs/TECH-DEBT-PLAN.md",
    "AUTO-UPDATE-PLAN.md": "web/AUTO-UPDATE-PLAN.md",
    "MOBILE-APK-PLAN.md": "web/MOBILE-APK-PLAN.md",
    "ROADMAP-1TO1.md": "web/ROADMAP-1TO1.md",
    "QUICKSTART_TEST.md": "server/QUICKSTART_TEST.md",
    "SECURITY-AUDIT-2026-07.md": "SECURITY-AUDIT.md",
    "MESSENGER-ADDON-PLAN-GPT.md": "docs/MESSENGER-ADDON-PLAN-GPT.md",
    #Прежнее место занято НОВЫМ `web/README.md` — законно, поэтому ни существование
    #файла, ни ссылки на этот путь здесь не проверяются. Проверяется только, что на
    #месте не осталась та же самая копия.
    "WEB-README-2026-07.md": None,
}
_WEB_README = "web/README.md"


def _outdated_docs(root=ROOT):
    d = os.path.join(root, "docs", "done", "outdated")
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith(".md") and f != "README.md")


def _norm(path):
    with open(path, "rb") as fh:
        return fh.read().replace(b"\r\n", b"\n")


def _half_done_moves(root=ROOT):
    """Снимки, чей оригинал остался на прежнем месте (или копия — на месте нового файла)."""
    bad = []
    for name in _outdated_docs(root):
        snap = os.path.join(root, "docs", "done", "outdated", name)
        old = OUTDATED_ORIGIN.get(name)
        if old and os.path.exists(os.path.join(root, old)):
            bad.append("%s всё ещё лежит на прежнем месте (%s)" % (name, old))
        if old is None:
            here = os.path.join(root, _WEB_README)
            if os.path.exists(here) and _norm(here) == _norm(snap):
                bad.append("%s совпадает с %s побайтно — новый README не написан"
                           % (name, _WEB_README))
    return bad


def _stale_outdated_refs(root=ROOT):
    """Ссылки на прежние пути снимков. `docs/done/` и датированные копии не проверяются —
    по той же причине, что в сторожe выше: снимок обязан описывать своё время."""
    old_paths = [p for p in OUTDATED_ORIGIN.values() if p]
    exts = (".py", ".js", ".mjs", ".vue", ".sh", ".md", ".txt", ".yml")
    bad = []
    for base, files in _walk_docs_tree(root):
        for fn in files:
            if not fn.endswith(exts) or ".bak-" in fn or ".base-" in fn:
                continue
            path = os.path.join(base, fn)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue                    #этот файл называет прежние пути намеренно
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for old in old_paths:
                if old in text:
                    bad.append("%s -> %s" % (os.path.relpath(path, root), old))
    return bad


def test_every_outdated_snapshot_is_named_in_its_readme():
    with open(os.path.join(OUTDATED, "README.md"), encoding="utf-8") as f:
        text = f.read()
    missing = [n for n in _outdated_docs() if n not in text]
    assert not missing, "в docs/done/outdated лежат снимки, не названные в README: %s" % missing


def test_outdated_origin_list_matches_the_folder():
    """Список прежних мест без дыр и без мёртвых записей — иначе новый снимок, у которого
    место не названо, молча выпадет из двух проверок ниже."""
    folder, listed = set(_outdated_docs()), set(OUTDATED_ORIGIN)
    assert folder == listed, ("OUTDATED_ORIGIN разошёлся с папкой: не названы %s, мёртвые %s"
                              % (sorted(folder - listed), sorted(listed - folder)))


def test_no_outdated_snapshot_is_left_at_its_old_place():
    bad = _half_done_moves()
    assert not bad, ("перенос в docs/done/outdated сделан наполовину:\n  "
                     + "\n  ".join(bad)
                     + "\nУстаревший документ на прежнем месте читается как живой план.")


def test_no_link_points_at_the_old_place_of_a_snapshot():
    bad = _stale_outdated_refs()
    assert not bad, ("ссылки ведут на прежнее место устаревших снимков:\n  "
                     + "\n  ".join(sorted(set(bad))))


def test_the_outdated_guards_catch_the_exact_defect(tmp_path):
    """🔒 ОБРАТНЫЙ ХОД на синтетическом дереве — ровно в той форме, в какой дефект был:
    копия есть, оригинал не удалён, на оригинал ссылается живой документ, а новый README
    веба так и не написан."""
    root = str(tmp_path)
    snaps = os.path.join(root, "docs", "done", "outdated")
    os.makedirs(snaps)
    os.makedirs(os.path.join(root, "web"))
    body = "# План ИИ-сервера\nPostgreSQL на бою\n"
    for rel in ("docs/done/outdated/PLAN-AI-SERVER.md", "docs/PLAN-AI-SERVER.md"):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(body)
    readme_old = "# web\nдесктоп на PySide6\n"
    for rel in ("docs/done/outdated/WEB-README-2026-07.md", _WEB_README):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(readme_old)
    with open(os.path.join(root, "docs", "PRICING.md"), "w", encoding="utf-8") as f:
        f.write("переезд — см. `docs/PLAN-AI-SERVER.md`\n")

    assert len(_half_done_moves(root)) == 2, _half_done_moves(root)
    assert _stale_outdated_refs(root) == [
        "%s -> docs/PLAN-AI-SERVER.md" % os.path.join("docs", "PRICING.md")]

    #И починка обязана гасить сигнал, иначе сторож краснел бы всегда.
    os.remove(os.path.join(root, "docs", "PLAN-AI-SERVER.md"))
    with open(os.path.join(root, _WEB_README), "w", encoding="utf-8") as f:
        f.write("# web — новый README\n")
    with open(os.path.join(root, "docs", "PRICING.md"), "w", encoding="utf-8") as f:
        f.write("переезд — см. `docs/PLAN-SALE-AND-MIGRATION.txt`\n")
    assert _half_done_moves(root) == [] and _stale_outdated_refs(root) == []


def test_the_walk_does_not_go_blind_on_a_dist_path_or_skip_github(tmp_path):
    """🔒 ОБРАТНЫЙ ХОД к ошибке обхода: клон в папке с «dist» в пути обязан
    проверяться, а файл в `.github/` — читаться (там живёт ci.yml)."""
    root = str(tmp_path / "distr" / "repo")
    os.makedirs(os.path.join(root, ".github", "workflows"))
    os.makedirs(os.path.join(root, "docs"))
    with open(os.path.join(root, ".github", "workflows", "ci.yml"), "w",
              encoding="utf-8") as f:
        f.write("# см. docs/PLAN-AI-SERVER.md\n")
    with open(os.path.join(root, "docs", "a.md"), "w", encoding="utf-8") as f:
        f.write("см. web/ROADMAP-1TO1.md\n")
    found = sorted(_stale_outdated_refs(root))
    assert len(found) == 2, found


# ─────────────────────────────────────────────────────────────────────────────────
# 🗂 РАСКЛАДКА docs/ ПО ПАПКАМ (22.09.2026, решение Ярослава)
# ─────────────────────────────────────────────────────────────────────────────────
# В корне docs/ лежали 32 документа вперемешку: планы, замеры, цена и конкуренты, политики
# безопасности. Разложены по назначению: plans/, research/, business/, security/.
# Прежнее место каждого названо списком (тот же довод, что у EVIDENCE: разбор прозы
# регулярками — ровно тот приём, из-за которого проверка однажды не проверяла ничего).
# MESSENGER-ADDON-PLAN-GPT.md уехал в outdated/ — его держит OUTDATED_ORIGIN выше.
DOCS_MOVED = {}
for _dir, _names in {
    "docs/plans": ("PLAN-EXTERNAL-GIFS.md", "PLAN-HARDENING.txt", "PLAN-MAX-NOTIFICATIONS.md",
                   "PLAN-MOBILE-OFFLINE.md", "PLAN-MULTIWORKER.md", "PLAN-SALE-AND-MIGRATION.txt",
                   "PLAN-TG-MINIAPP.md", "PLAN-THREE-REVIEWS-2026-09-12.md",
                   "PLAN-YAROSLAV-2026-09.md", "QUEUE.md", "TODO-REVIEW-2026-09-18.md",
                   "MESSENGER-ADDON-PLAN-GPT-SMART.md", "ULYANA-CAMPUS-BROWSER-SPEC.md"),
    "docs/research": ("PERF-SCALE-2026.md", "RESEARCH-SERVER-SCALE-2026-09.txt",
                      "SYNC-RESEARCH-2026.md", "SLO.md"),
    "docs/business": ("PRICING-AND-PITCH.md", "MARKET-ANALOGUES-2026.md", "COMPETITOR-MMIS.md",
                      "CHRONOLOGY-EVIDENCE.md", "commission-onepager.html"),
    "docs/security": ("SECURITY-ARCHITECTURE.md", "INCIDENT-RESPONSE.md", "SUBPROCESSORS.md",
                      "DATA-RETENTION.md"),
    "docs/widget-preview": ("widget-preview.html",),
}.items():
    for _n in _names:
        DOCS_MOVED["docs/" + _n] = _dir + "/" + _n
#Из корня репозитория: установщик копирует его в поставку (deploy/make-installer.sh).
DOCS_MOVED["DEPLOY-VSGUTU-SECURE.md"] = "docs/security/DEPLOY-VSGUTU-SECURE.md"

#Что вправе лежать прямо в корне docs/, и почему. Остальное раскладывается по папкам.
_DOCS_ROOT_ALLOWED = {
    "HISTORY.md": "история заходов, вынесенная из CLAUDE.md (на неё ссылается CLAUDE.md)",
    "github-card.png": "генерирует tools/build_github_card.py именно сюда",
}
_DOCS_ROOT_ALLOWED_RE = re.compile(r"^CLAUDE-[\w.-]+\.md$")   #разрез CLAUDE.md, test_claude_md_split


def _old_path_rx(old):
    #Корневой файл упоминается голым именем — не предварённым «/», иначе совпадёт с новым путём.
    if old.startswith("docs/"):
        return re.compile(r"(?<![\w.-])" + re.escape(old))
    return re.compile(r"(?<![\w/.-])" + re.escape(old) + r"(?![\w-])")


def _misplaced_moves(root=ROOT):
    bad = []
    for old, new in DOCS_MOVED.items():
        if os.path.exists(os.path.join(root, old)):
            bad.append("%s снова лежит на прежнем месте (место — %s)" % (old, new))
        if not os.path.exists(os.path.join(root, new)):
            bad.append("%s не найден на новом месте %s" % (old, new))
    return bad


def _stale_moved_refs(root=ROOT):
    rxs = [(old, _old_path_rx(old)) for old in DOCS_MOVED]
    exts = (".py", ".js", ".mjs", ".vue", ".sh", ".ps1", ".md", ".txt", ".yml", ".json", ".html")
    bad = []
    for base, files in _walk_docs_tree(root):
        for fn in files:
            if not fn.endswith(exts) or ".bak-" in fn or ".base-" in fn:
                continue
            path = os.path.join(base, fn)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue                    #этот файл называет прежние пути намеренно
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for old, rx in rxs:
                #Подстрока — дешёвый отсев (C-код), регулярка — только для точной границы.
                if old in text and rx.search(text):
                    bad.append("%s -> %s" % (os.path.relpath(path, root), old))
    return bad


def _unsorted_in_docs_root(root=ROOT):
    d = os.path.join(root, "docs")
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if os.path.isfile(os.path.join(d, f)) and f not in _DOCS_ROOT_ALLOWED
                  and not _DOCS_ROOT_ALLOWED_RE.match(f) and ".bak-" not in f
                  and ".base-" not in f)


def test_moved_docs_live_only_at_their_new_place():
    bad = _misplaced_moves()
    assert not bad, "раскладка docs/ разошлась со списком DOCS_MOVED:\n  " + "\n  ".join(bad)


def test_no_link_points_at_the_old_place_of_a_moved_doc():
    bad = _stale_moved_refs()
    assert not bad, ("ссылки ведут на прежнее место разложенных документов:\n  "
                     + "\n  ".join(sorted(set(bad))))


def test_docs_root_holds_only_what_belongs_there():
    """Новый документ, брошенный в корень docs/, — ровно то, из-за чего там скопилось 32
    файла вперемешку. Кладите в plans/, research/, business/ или security/."""
    stray = _unsorted_in_docs_root()
    assert not stray, ("в корне docs/ лежат неразложенные файлы: %s. Место — plans/, "
                       "research/, business/ или security/; исключение — только в "
                       "_DOCS_ROOT_ALLOWED с причиной" % stray)


def test_the_layout_guards_catch_a_return_to_the_old_place(tmp_path):
    """🔒 ОБРАТНЫЙ ХОД: план вернулся в корень docs/, на него ссылается код, а корневой
    DEPLOY-VSGUTU-SECURE.md упомянут голым именем — всё это обязано краснеть."""
    root = str(tmp_path)
    for rel in ("docs/plans", "docs/security", "tools"):
        os.makedirs(os.path.join(root, rel))
    for rel in ("docs/QUEUE.md", "docs/security/DEPLOY-VSGUTU-SECURE.md"):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write("# x\n")
    with open(os.path.join(root, "tools", "a.py"), "w", encoding="utf-8") as f:
        f.write("# см. docs/QUEUE.md и DEPLOY-VSGUTU-SECURE.md\n")
    assert any("QUEUE.md снова лежит" in b for b in _misplaced_moves(root))
    refs = _stale_moved_refs(root)
    assert any(r.endswith("-> docs/QUEUE.md") for r in refs), refs
    assert any(r.endswith("-> DEPLOY-VSGUTU-SECURE.md") for r in refs), refs
    assert _unsorted_in_docs_root(root) == ["QUEUE.md"]
    #Новый путь и ссылка на него — не нарушение, иначе сторож краснел бы всегда.
    os.replace(os.path.join(root, "docs", "QUEUE.md"),
               os.path.join(root, "docs", "plans", "QUEUE.md"))
    with open(os.path.join(root, "tools", "a.py"), "w", encoding="utf-8") as f:
        f.write("# см. docs/plans/QUEUE.md и docs/security/DEPLOY-VSGUTU-SECURE.md\n")
    assert _stale_moved_refs(root) == [] and _unsorted_in_docs_root(root) == []


#🔥 ДВЕ ФОРМЫ, КОТОРЫХ ПОДСТРОКОЙ НЕ ВИДНО (нашёл Полковник 22.09.2026).
#(1) Глоб на прежнее место: `docs/MESSENGER-ADDON-PLAN-GPT*.md` жил в пяти комментариях кода,
#а оба файла разъехались по разным папкам — глоб не находил НИЧЕГО, сторож был зелёным.
#Проверяется свойство: глоб на docs/ обязан находить хотя бы один файл.
#(2) Относительная ссылка в markdown считается от папки ФАЙЛА. 74 ссылки ревью были написаны
#от корня репозитория и на GitHub вели в 404 ещё до переноса.
_DOCS_GLOB = re.compile(r"(?<![\w.-])docs/[\w./-]*\*[\w.*/-]*")
_MD_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")
_SORTED_DOC_DIRS = ("docs/plans", "docs/research", "docs/business", "docs/security")


def _dead_docs_globs(root=ROOT):
    import glob as _glob
    exts = (".py", ".js", ".mjs", ".vue", ".sh", ".ps1", ".md", ".txt", ".yml", ".json", ".html")
    bad = []
    for base, files in _walk_docs_tree(root):
        for fn in files:
            if not fn.endswith(exts) or ".bak-" in fn or ".base-" in fn:
                continue
            path = os.path.join(base, fn)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            if "docs/" not in text or "*" not in text:
                continue
            for m in set(_DOCS_GLOB.findall(text)):
                if not _glob.glob(os.path.join(root, m.rstrip(".")), recursive=True):
                    bad.append("%s -> %s" % (os.path.relpath(path, root), m))
    return bad


def _paths_in_git(root):
    """Файлы и каталоги из индекса git. 🔥 Ссылка на `CLAUDE.md` (он в .gitignore) была
    зелёной у разработчика и красной в CI — у клонировавшего репозиторий файла нет, ссылка
    мертва. Сверяем с ИНДЕКСОМ, а не с `check-ignore`: первая версия спрашивала, игнорирует ли
    git путь, и пропускала вторую форму того же дефекта — файл, который просто забыли `git add`
    (нашёл Полковник 22.09.2026). Копия без .git — None, предмета нет; упавший git при живом
    репозитории — отказ, и он громкий."""
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    import subprocess
    r = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True)
    assert r.returncode == 0, "git ls-files упал: %r" % r.stderr[:300]
    known = {"."}
    for p in r.stdout.decode("utf-8").split("\0"):
        while p and p not in known:
            known.add(p)
            p = p.rpartition("/")[0]
    return known


def _broken_links_in_sorted_docs(root=ROOT):
    bad = []
    existing = []
    for rel_dir in _SORTED_DOC_DIRS:
        d = os.path.join(root, rel_dir)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md"):
                continue
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                text = f.read()
            for m in _MD_LINK.finditer(text):
                tg = m.group(1)
                if re.match(r"^(https?:|mailto:|data:|/)", tg):
                    continue
                if not os.path.exists(os.path.join(d, tg)):
                    bad.append("%s/%s -> %s" % (rel_dir, fn, tg))
                else:
                    target = os.path.normpath(os.path.join(rel_dir, tg)).replace("\\", "/")
                    existing.append(("%s/%s -> %s" % (rel_dir, fn, tg), target))
    in_git = _paths_in_git(root)
    if in_git is not None:
        bad += ["%s (файла нет в git)" % where for where, t in existing if t not in in_git]
    return bad


def test_no_docs_glob_points_at_nothing():
    bad = _dead_docs_globs()
    assert not bad, "глоб на docs/ не находит ни одного файла:\n  " + "\n  ".join(sorted(set(bad)))


def test_relative_links_in_sorted_docs_resolve():
    bad = _broken_links_in_sorted_docs()
    assert not bad, ("относительные ссылки ведут в никуда (считаются от папки файла, а не от "
                     "корня репозитория):\n  " + "\n  ".join(bad[:20]))


def test_the_glob_and_link_guards_catch_their_defects(tmp_path):
    """🔒 ОБРАТНЫЙ ХОД на дословных формах обоих дефектов."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "docs", "plans"))
    os.makedirs(os.path.join(root, "src"))
    with open(os.path.join(root, "docs", "plans", "A-SMART.md"), "w", encoding="utf-8") as f:
        f.write("# план\n\nсм. [код](src/x.py)\n")
    with open(os.path.join(root, "src", "x.py"), "w", encoding="utf-8") as f:
        f.write("# из docs/A*.md\n")
    assert _dead_docs_globs(root) == [os.path.join("src", "x.py") + " -> docs/A*.md"]
    assert _broken_links_in_sorted_docs(root) == ["docs/plans/A-SMART.md -> src/x.py"]
    #Починка гасит оба сигнала.
    with open(os.path.join(root, "src", "x.py"), "w", encoding="utf-8") as f:
        f.write("# из docs/plans/A*.md\n")
    with open(os.path.join(root, "docs", "plans", "A-SMART.md"), "w", encoding="utf-8") as f:
        f.write("# план\n\nсм. [код](../../src/x.py)\n")
    assert _dead_docs_globs(root) == [] and _broken_links_in_sorted_docs(root) == []


def test_link_to_a_file_outside_git_is_broken(tmp_path):
    """🔒 ОБРАТНЫЙ ХОД на обеих формах дефекта CI 22.09.2026: файл на диске ЕСТЬ, но в git его
    нет — игнорируемый (`CLAUDE.md`) и забытый в `git add`. У клонировавшего обе ссылки мертвы."""
    import subprocess
    root = str(tmp_path)
    subprocess.run(["git", "init", "-q", root], check=True)
    os.makedirs(os.path.join(root, "docs", "plans"))
    os.makedirs(os.path.join(root, "docs", "research"))
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("CLAUDE.md\n")
    for rel in ("CLAUDE.md", os.path.join("docs", "research", "НОВЫЙ.md")):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write("# есть на диске\n")
    with open(os.path.join(root, "docs", "plans", "R.md"), "w", encoding="utf-8") as f:
        f.write("см. [CLAUDE.md](../../CLAUDE.md) и [замер](../research/НОВЫЙ.md), [корень](../../)\n")
    assert _broken_links_in_sorted_docs(root) == [
        "docs/plans/R.md -> ../../CLAUDE.md (файла нет в git)",
        "docs/plans/R.md -> ../research/НОВЫЙ.md (файла нет в git)"]
    #Оба файла попали в индекс — сигнал гаснет, то есть ловится именно «нет в git».
    subprocess.run(["git", "-C", root, "add", "-f", "CLAUDE.md", "docs/research/НОВЫЙ.md"],
                   check=True)
    assert _broken_links_in_sorted_docs(root) == []
