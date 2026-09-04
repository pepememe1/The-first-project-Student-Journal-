"""
Сторож `app/hostcaps` — единственного места, отвечающего «что потянет эта машина».

━━ ПОЧЕМУ ЭТО НАДО СТЕРЕЧЬ ━━
От него зависит размер кеша боевой базы. Ошибка здесь ТИХАЯ в обе стороны: занизишь —
никто не заметит, кроме замедлившейся базы; завысишь на слабой машине — она уйдёт в
своп, и это будет выглядеть как «сервер стал тормозить», а не как правка настройки.

━━ ГЛАВНОЕ ТРЕБОВАНИЕ: ПЕРЕЕЗД НЕ ИМЕЕТ ПРАВА ПЕРЕДЕЛАТЬ ПРОВЕРЕННОЕ ━━
На нынешнем бою кеш — 4 МБ, и это правильное число, выведенное из размера базы и объёма
памяти. Заготовка под машину ВСГУТУ обязана оставить слабую машину В ТОЧНОСТИ такой, как
была: иначе «подготовка к переезду» молча меняет поведение прода, который никто не
переезжал.

⚠️ Все тесты подменяют железо, а не читают настоящее. Тест, зависящий от того, чья это
машина, у нас уже был дважды (`config.IS_PROD` и фикстура переводчика) — и оба раза
«зелено у одного, красно у другого» находилось не сразу.
"""
import pytest

from app import hostcaps

GB = 1024 ** 3


@pytest.fixture
def machine(monkeypatch):
    """Подменяет железо: memory/cpu_count/видеокарту и переменную окружения."""
    def _set(ram_gb, cpus, gpu_present=False, env=None):
        monkeypatch.setattr(hostcaps.hostinfo, "memory",
                            lambda: ({"total": int(ram_gb * GB),
                                      "available": int(ram_gb * GB * 0.7)}
                                     if ram_gb else {}))
        monkeypatch.setattr(hostcaps.hostinfo, "cpu_count", lambda: cpus)
        monkeypatch.setattr(hostcaps, "gpu",
                            lambda: {"present": gpu_present, "name": "test", "vram_mb": 0})
        if env is None:
            monkeypatch.delenv(hostcaps._ENV_TIER, raising=False)
        else:
            monkeypatch.setenv(hostcaps._ENV_TIER, env)
    return _set


# ─────────────────────────────────────────────────────────────────────────────────
# КЛАСС МАШИНЫ
# ─────────────────────────────────────────────────────────────────────────────────

def test_the_production_vps_is_recognised_as_weak(machine):
    """Нынешний бой: 960 МБ и одно ядро."""
    machine(0.94, 1)
    assert hostcaps.profile()["tier"] == "vps"
    assert not hostcaps.is_workstation()


@pytest.mark.parametrize("ram_gb,cpus", [(32, 8), (32, 16), (64, 16), (64, 32), (12, 8)])
def test_every_machine_in_the_target_range_is_recognised(machine, ram_gb, cpus):
    """Весь ЦЕЛЕВОЙ ДИАПАЗОН, а не одна машина.

    ⚠️ Требование Ярослава: «у заготовки не должно быть привязки к железу, мы пока
    оринтириуемся на Ryzen 7/9 / Xeon + 12/16 гб памяти + 32/64 DDR4/DDR5». Машина ещё
    не выбрана, поэтому проверяем КЛАСС: любая разумная конфигурация из этого диапазона
    обязана опознаться как мощная. Тест на одну конкретную сборку был бы снимком
    значения — тем самым, из-за которого у нас краснели сторожа на законных правках.
    """
    machine(ram_gb, cpus, gpu_present=True)
    prof = hostcaps.profile()
    assert prof["tier"] == "workstation"
    assert prof["gpu"]["present"] is True


def test_lots_of_memory_but_one_core_is_still_weak(machine):
    """Памяти много, ядро одно — считать такую машину мощной нельзя.

    На одном ядре счёт модели останавливает журнал всему колледжу: это не про объём
    памяти, а про то, что блокирующая работа некуда деться. Порог смотрит на ОБА
    признака именно поэтому.
    """
    machine(32, 1)
    assert hostcaps.profile()["tier"] == "vps"


def test_unknown_memory_falls_back_to_weak(machine):
    """Память не прочиталась (необычный контейнер) — считаем машину слабой.

    Ошибка в эту сторону означает «не включили лишнего», в обратную — «положили журнал».
    """
    machine(0, 8)
    prof = hostcaps.profile()
    assert prof["tier"] == "vps"
    assert "определить не удалось" in prof["why"]


@pytest.mark.parametrize("forced,expected", [("workstation", "workstation"),
                                             ("vps", "vps"),
                                             ("WORKSTATION", "workstation")])
def test_env_override_wins(machine, forced, expected):
    """Явное указание перебивает автоопределение — для машины, которую не предусмотрели."""
    machine(0.94, 1, env=forced)
    assert hostcaps.profile()["tier"] == expected


def test_garbage_in_env_does_not_break_detection(machine):
    """Мусор в переменной игнорируется, а не роняет сервер и не включает лишнее."""
    machine(32, 16, env="да-включи-всё")
    assert hostcaps.profile()["tier"] == "workstation"
    machine(0.94, 1, env="да-включи-всё")
    assert hostcaps.profile()["tier"] == "vps"


# ─────────────────────────────────────────────────────────────────────────────────
# РАЗМЕР КЕША БАЗЫ
# ─────────────────────────────────────────────────────────────────────────────────

def test_weak_machine_keeps_exactly_the_value_proven_in_production(machine):
    """🔒 ОБРАТНЫЙ ХОД ПО СМЫСЛУ: на слабой машине число обязано остаться прежним.

    4 МБ — не «поменьше на всякий случай», а выведенное значение: боевой файл базы около
    3 МБ, то есть кеш вмещает его целиком вместе с индексами, а лишнее ушло бы в своп.
    Если этот тест покраснел — значит подготовка к переезду задела прод, который никуда
    не переезжал.
    """
    machine(0.94, 1)
    assert hostcaps.sqlite_cache_kib() == 4_000


def test_workstation_gets_a_bigger_cache(machine):
    """На машине с 32 ГБ жаться под 960 МБ незачем."""
    machine(32, 16)
    assert hostcaps.sqlite_cache_kib() == 64_000


def test_cache_value_is_a_positive_integer_of_kilobytes(machine):
    """Значение уходит прямо в текст PRAGMA — дробь или строка там сломали бы запрос."""
    for ram, cpus in ((0.94, 1), (32, 16), (0, 4)):
        machine(ram, cpus)
        val = hostcaps.sqlite_cache_kib()
        assert isinstance(val, int) and val > 0


# ─────────────────────────────────────────────────────────────────────────────────
# ВИДЕОКАРТА
# ─────────────────────────────────────────────────────────────────────────────────

def test_missing_nvidia_smi_is_not_an_error(monkeypatch):
    """Нет `nvidia-smi` — «карта не найдена», а не падение.

    ⚠️ И это НЕ означает «карты нет»: на машине без драйверов она может стоять. Поэтому
    ответ этой функции влияет только на подсказку человеку, но никогда — на то,
    включится ли функция продукта.
    """
    monkeypatch.setattr(hostcaps.shutil, "which", lambda _name: None)
    assert hostcaps.gpu() == {"present": False, "name": "", "vram_mb": 0}


def test_broken_nvidia_smi_is_not_an_error(monkeypatch):
    """Утилита есть, но падает или отвечает мусором — тоже не повод ронять сервер."""
    monkeypatch.setattr(hostcaps.shutil, "which", lambda _name: "nvidia-smi")

    def _boom(*_a, **_kw):
        raise OSError("нет доступа")
    monkeypatch.setattr(hostcaps.subprocess, "run", _boom)
    assert hostcaps.gpu()["present"] is False


def test_gpu_is_parsed_from_real_output(monkeypatch):
    """Разбор ответа проверяем на ДОСЛОВНОЙ строке живой утилиты, а не на выдумке."""
    monkeypatch.setattr(hostcaps.shutil, "which", lambda _name: "nvidia-smi")

    class _Res:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 4080, 16376\n"
    monkeypatch.setattr(hostcaps.subprocess, "run", lambda *a, **kw: _Res())
    card = hostcaps.gpu()
    assert card["present"] is True
    assert card["name"] == "NVIDIA GeForce RTX 4080"
    assert card["vram_mb"] == 16376
