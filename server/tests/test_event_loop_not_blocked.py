"""
test_event_loop_not_blocked.py — ни один `async def` сервера не имеет права звать
блокирующий код напрямую (3.7.7, заход по скорости).

━━ ЗАЧЕМ ЭТО СВОЙСТВО, А НЕ ОДИН ТЕСТ ━━
Боевая машина — ОДНО ядро, и uvicorn работает одним процессом (это не лень, а
требование: реестр веб-сокетов и ход активностей живут в памяти процесса, см. §13).
Значит цикл событий ровно один на весь колледж. Синхронный вызов внутри `async def`
не замедляет свой запрос — он ОСТАНАВЛИВАЕТ ВСЁ: мессенджер, веб-сокеты, `/health`.

Так и было: `vector_stt` звал `stt_service.transcribe_bytes` напрямую, а это Whisper —
секунды на маленькой модели и десятки секунд на `large-v3`. Один человек, надиктовавший
оценку, замораживал сервер всем остальным. Снаружи это неотличимо от «сайт лёг».

⚠️ Почему соседние 150 ручек мессенджера при этом безопасны: они объявлены ОБЫЧНЫМ
`def`, и FastAPI сам уводит такие обработчики в пул потоков. Опасна ровно та форма, где
`async def` выбран вынужденно — ради `await file.read()` или веб-сокета, — и внутрь
попал синхронный тяжёлый вызов. Поймать это глазами нельзя: код выглядит правильным.

⚠️ Тест намеренно УЗКИЙ — поимённый список тяжёлых вызовов, а не «любой не-await».
Сторож, ругающийся на каждую вторую функцию, перестают читать (то же правило, что у
порога риска отчисления и у сторожа вёрстки). Появится новый тяжёлый сервис — его имя
дописывают СЮДА, и это дешевле, чем расследовать «сайт иногда замирает».

Обратный ход ПРОВЕРЕН: возврат `res = stt_service.transcribe_bytes(...)` без
`run_in_threadpool` — тест краснеет и называет файл, функцию и строку.
"""
import ast
import io
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#Тяжёлые синхронные вызовы, каждый из которых способен держать цикл событий секундами.
#Имена, а не модули: ИИ-сервисы импортируются лениво внутри функций (`from ... import
#stt_service`), и по имени модуля их не поймать.
BLOCKING_CALLS = {
    "transcribe_bytes",          # распознавание речи (Whisper) — до десятков секунд
    "synthesize",                # синтез речи (Silero)
    "summarize",                 # сводка переписки через LLM
    "expand_query",              # расширение поискового запроса через LLM
    "complete", "voice", "free_chat",   # примитивы vector_llm
    "translate_text",            # переводчик (сеть, до 8 с)
    "inspect_zip", "import_zip",  # архив импорта: распаковка и тысячи записей в базу
}
#Модули, любой вызов которых блокирует: сетевые клиенты и сон.
BLOCKING_MODULES = {"requests", "httpx", "urllib", "subprocess"}


def _own_nodes(fn):
    """Узлы функции без вложенных def/lambda: чужой await к ней не относится."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "api_route", "head", "options"}


def _is_route(fn) -> bool:
    for deco in fn.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute) and target.attr in _ROUTE_METHODS:
            return True
    return False


def _routes_without_await(source: str, name: str) -> list[str]:
    """Ручки, объявленные `async def`, в теле которых нет ни одного await.

    Такая ручка выполняется на цикле событий ЦЕЛИКОМ, со всем своим синхронным кодом, —
    а объявленная обычным `def` ушла бы в пул потоков. `async` без `await` не даёт ничего
    и отнимает главное. Список тяжёлых вызовов выше этого не видит: чтение файла и разбор
    zip в нём не значатся, а перечислить весь файловый ввод-вывод по именам нельзя."""
    out = []
    for fn in [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef)]:
        if not _is_route(fn):
            continue
        if not any(isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for n in _own_nodes(fn)):
            out.append(f"{name}:{fn.lineno} async def {fn.name}() — ни одного await")
    return out


def test_routes_without_await_are_plain_def():
    """🔥 Нашёл разбор узких мест 07.10.2026: четыре ручки обновления приложения читали
    файлы и zip на цикле событий — пока телефоны качали выпуск, сервер был глух."""
    found = []
    for path in sorted(APP.rglob("*.py")):
        found += _routes_without_await(io.open(path, encoding="utf-8").read(),
                                       str(path.relative_to(APP)))
    assert not found, "Ручка `async def` без await — объяви обычным `def`:\n" + "\n".join(found)


def test_the_await_check_sees_the_original_defect():
    """Обратный ход на дословной форме дефекта — и на формах, которые трогать нельзя."""
    bad = (
        "@router.get('/files/{version}/{path:path}')\n"
        "async def bundle_file(version: str, path: str):\n"
        "    with zipfile.ZipFile(zip_path) as z:\n"
        "        body = z.read(path)\n"
        "    return Response(content=body)\n")
    assert _routes_without_await(bad, "x.py") == ["x.py:2 async def bundle_file() — ни одного await"]
    #Настоящая асинхронная ручка, обычная ручка и не-ручка (lifespan) — не нарушения.
    fine = (
        "@router.post('/stt')\n"
        "async def stt(file: UploadFile):\n"
        "    raw = await file.read()\n"
        "    return raw\n"
        "@router.get('/x')\n"
        "def plain():\n"
        "    return open('f').read()\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    yield\n")
    assert _routes_without_await(fine, "x.py") == []
    #await во ВЛОЖЕННОЙ функции ручку не оправдывает: её собственное тело синхронное.
    nested = (
        "@router.get('/y')\n"
        "async def outer():\n"
        "    async def inner():\n"
        "        await something()\n"
        "    return open('f').read()\n")
    assert len(_routes_without_await(nested, "x.py")) == 1


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError:                     # noqa: PERF203 — файл не наш, пропускаем
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
            #Вызовы под `await` безопасны по построению: их результат ждут, не блокируя
            #цикл (это либо корутина, либо уже обёртка вроде run_in_threadpool).
            awaited = {id(a.value) for a in ast.walk(fn) if isinstance(a, ast.Await)}
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call) or id(call) in awaited:
                    continue
                f = call.func
                name = getattr(f, "attr", None) or getattr(f, "id", None)
                base = getattr(getattr(f, "value", None), "id", None)
                if name in BLOCKING_CALLS or base in BLOCKING_MODULES:
                    rel = path.relative_to(APP.parent)
                    found.append(f"{rel}:{call.lineno} — async {fn.name}() зовёт {name}()")
    return found


def test_no_blocking_call_inside_any_async_endpoint():
    bad = _offenders()
    assert not bad, (
        "Блокирующий вызов внутри async-функции останавливает ВЕСЬ сервер "
        "(одно ядро, один процесс, один цикл событий).\n"
        "Оберни в `await run_in_threadpool(...)` либо объяви обработчик обычным `def` — "
        "тогда FastAPI сам уведёт его в пул потоков:\n  " + "\n  ".join(bad)
    )


def test_the_guard_itself_can_still_see_such_a_call():
    """Обратный тест: сторож обязан срабатывать на дословной форме, вызвавшей дефект.

    Без него правило «не звать блокирующее» зелено при ЛЮБОМ коде — например если
    разбор молча сломается на новой версии Python и `_offenders` начнёт возвращать
    пустой список. Такой сторож неотличим от исправного кода и хуже отсутствия сторожа.
    """
    sample = (
        "async def vector_stt(file):\n"
        "    data = await file.read()\n"
        "    res = stt_service.transcribe_bytes(data)\n"
        "    return res\n"
    )
    tree = ast.parse(sample)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
    awaited = {id(a.value) for a in ast.walk(fn) if isinstance(a, ast.Await)}
    hits = [c for c in ast.walk(fn)
            if isinstance(c, ast.Call) and id(c) not in awaited
            and (getattr(c.func, "attr", None) in BLOCKING_CALLS)]
    assert hits, "сторож не увидел бы исходный дефект — значит он ничего не проверяет"

    fixed = sample.replace("res = stt_service.transcribe_bytes(data)",
                           "res = await run_in_threadpool(stt_service.transcribe_bytes, data)")
    tree2 = ast.parse(fixed)
    fn2 = next(n for n in ast.walk(tree2) if isinstance(n, ast.AsyncFunctionDef))
    awaited2 = {id(a.value) for a in ast.walk(fn2) if isinstance(a, ast.Await)}
    hits2 = [c for c in ast.walk(fn2)
             if isinstance(c, ast.Call) and id(c) not in awaited2
             and (getattr(c.func, "attr", None) in BLOCKING_CALLS)]
    assert not hits2, "починенная форма не должна считаться нарушением"
