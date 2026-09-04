# -*- coding: utf-8 -*-
"""test_qr.py — сторож самодельного QR-кода.

━━ ПОЧЕМУ ЗДЕСЬ ДЕКОДЕР, А НЕ ПРОВЕРКА ОТДЕЛЬНЫХ КУСКОВ ━━━━━━━━━━━━━━━━━━━━━━━━━
У QR-кода отказ ТИХИЙ и полный: картинка рисуется, выглядит как настоящий код,
занимает своё место на странице — и не читается ни одним телефоном. Проверять
такое по частям («поисковые узоры на месте», «размер сошёлся») бесполезно: любая
из этих проверок останется зелёной при перепутанном порядке модулей.

Поэтому сторож ЧИТАЕТ КОД ОБРАТНО. Декодер написан здесь заново, по описанию
стандарта, и намеренно НЕ пользуется функциями кодировщика для того, что можно
восстановить самому: своя карта служебных модулей, свои таблицы поля Галуа, свой
обход. Совпадение двух независимых реализаций — это и есть проверка.

⚠️ Отдельно считаются СИНДРОМЫ Рида–Соломона: у целого кода они все нулевые. Это
единственный способ поймать ошибку в проверочных байтах, потому что сами данные
читаются и без коррекции — то есть тест «строка совпала» прошёл бы и с полностью
испорченной коррекцией, а телефон такой код не возьмёт.

⚠️ И сверка с ЧУЖИМИ неизменяемыми числами: биты формата и сведения о версии
взяты из опубликованных таблиц стандарта, а не пересчитаны нашим же кодом.
"""

import pytest

from app import qr


# ─────────────────────────────────────────────────────────────────────────────────
# Независимый декодер
# ─────────────────────────────────────────────────────────────────────────────────

def _gf():
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf()


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _function_map(size: int, version: int):
    """Карта служебных модулей, собранная заново по описанию стандарта."""
    fixed = [[False] * size for _ in range(size)]

    def mark(r0, c0, h, w):
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                if 0 <= r < size and 0 <= c < size:
                    fixed[r][c] = True

    mark(0, 0, 9, 9)                      # поисковый узор + отступ + область формата
    mark(0, size - 8, 9, 8)
    mark(size - 8, 0, 8, 9)
    for i in range(size):                 # синхрополосы
        fixed[6][i] = True
        fixed[i][6] = True
    centers = qr._ALIGN[version]
    last = centers[-1] if centers else 0
    for r in centers:
        for c in centers:
            if (r == 6 and c == 6) or (r == 6 and c == last) or (r == last and c == 6):
                continue
            mark(r - 2, c - 2, 5, 5)
    if version >= 7:                      # сведения о версии
        mark(0, size - 11, 6, 3)
        mark(size - 11, 0, 3, 6)
    return fixed


def _read_format(m):
    """Первая копия сведений о формате: уровень коррекции и номер маски."""
    order = ([(i, 8) for i in range(6)] + [(7, 8), (8, 8), (8, 7)]
             + [(8, 14 - i) for i in range(9, 15)])
    bits = 0
    for i, (r, c) in enumerate(order):
        if m[r][c]:
            bits |= 1 << i
    data = (bits ^ 0x5412) >> 10
    return data >> 3, data & 7


def decode(m) -> str:
    """Прочитать матрицу обратно в строку. Бросает, если код испорчен."""
    size = len(m)
    version = (size - 17) // 4
    ecl, mask = _read_format(m)
    assert ecl == qr.ECL_BITS_M, f"уровень коррекции не M, а {ecl:02b}"
    fixed = _function_map(size, version)
    rule = qr.MASKS[mask]
    grid = [[m[r][c] != (rule(c, r) and not fixed[r][c]) for c in range(size)]
            for r in range(size)]

    bits = []
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vert in range(size):
            for j in range(2):
                col = right - j
                upward = ((right + 1) & 2) == 0
                row = (size - 1 - vert) if upward else vert
                if not fixed[row][col]:
                    bits.append(1 if grid[row][col] else 0)

    words = [int("".join(map(str, bits[i:i + 8])), 2)
             for i in range(0, len(bits) // 8 * 8, 8)]
    total = qr.total_codewords(version)
    assert len(words) >= total, (
        f"в коде {len(words)} слов вместо {total} — часть площади не заполнена данными")
    words = words[:total]

    ec_count, groups = qr._ECC_M[version]
    sizes = [d for n, d in groups for _ in range(n)]
    blocks = [[] for _ in sizes]
    pos = 0
    for i in range(max(sizes)):
        for b, need in enumerate(sizes):
            if i < need:
                blocks[b].append(words[pos])
                pos += 1
    eccs = [[] for _ in sizes]
    for _ in range(ec_count):
        for b in range(len(sizes)):
            eccs[b].append(words[pos])
            pos += 1
    assert pos == len(words), "перемешивание блоков не сошлось по длине"

    for i, (block, ecc) in enumerate(zip(blocks, eccs)):
        for k in range(ec_count):
            syndrome = 0
            for coef in block + ecc:
                syndrome = _mul(syndrome, _EXP[k]) ^ coef
            assert syndrome == 0, (
                f"блок {i}: синдром {k} равен {syndrome}, а у целого кода он нулевой — "
                "проверочные байты посчитаны неверно, и телефон такой код не возьмёт")

    stream = "".join(f"{w:08b}" for block in blocks for w in block)
    assert stream[:4] == "0100", "режим не байтовый"
    cb = qr.count_bits(version)
    length = int(stream[4:4 + cb], 2)
    body = stream[4 + cb:4 + cb + length * 8]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────────
# Сами проверки
# ─────────────────────────────────────────────────────────────────────────────────

OTPAUTH = ("otpauth://totp/GradeBookAI%3Aadmin?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
           "&issuer=GradeBookAI&algorithm=SHA1&digits=6&period=30")


def test_real_otpauth_uri_reads_back():
    """Главный случай: ровно та строка, которую снимает телефон с экрана."""
    assert decode(qr.matrix(OTPAUTH)) == OTPAUTH


@pytest.mark.parametrize("length", [1, 14, 15, 26, 27, 42, 43, 62, 84, 106,
                                    122, 123, 152, 180, 181, 213])
def test_every_version_boundary_reads_back(length):
    """Границы версий: на каждой из них меняется раскладка блоков.

    Длины подобраны по краям таблицы вместимости — 14/15, 122/123, 180/181 это
    переходы версия→версия, и именно там ошибка в таблице блоков или в длине поля
    «сколько байт» (8 бит до версии 9, 16 дальше) даёт испорченный код.
    """
    text = "A" * length
    assert decode(qr.matrix(text)) == text


def test_utf8_survives():
    """Кириллица в подписи записи аутентификатора не должна ломать байтовый режим."""
    text = "otpauth://totp/GradeBookAI:Иванов?secret=JBSWY3DPEHPK3PXP&issuer=GradeBookAI"
    assert decode(qr.matrix(text)) == text


def test_format_bits_match_the_published_table():
    """Биты формата — ЧУЖИЕ неизменяемые числа из приложения C стандарта.

    Пересчитать их нашим же кодом и сравнить с ним же — значит не проверить ничего.
    """
    published = ["101010000010010", "101000100100101", "101111001111100",
                 "101101101001011", "100010111111001", "100000011001110",
                 "100111110010111", "100101010100000"]
    for mask, expected in enumerate(published):
        canvas = qr._Canvas(1)
        canvas.draw_function_patterns()
        canvas.draw_format(mask)
        # Читаем обратно ровно те 15 модулей, куда положили.
        order = ([(i, 8) for i in range(6)] + [(7, 8), (8, 8), (8, 7)]
                 + [(8, 14 - i) for i in range(9, 15)])
        bits = 0
        for i, (r, c) in enumerate(order):
            if canvas.m[r][c]:
                bits |= 1 << i
        assert format(bits, "015b") == expected, f"маска {mask}"


def test_version_information_matches_the_published_table():
    """Сведения о версии (приложение D) — тоже чужие числа, для версий 7 и старше."""
    published = {7: "000111110010010100", 8: "001000010110111100",
                 9: "001001101010011001", 10: "001010010011010011"}
    for version, expected in published.items():
        canvas = qr._Canvas(version)
        canvas.draw_function_patterns()
        size = canvas.size
        bits = 0
        for i in range(18):
            if canvas.m[i // 3][size - 11 + i % 3]:
                bits |= 1 << i
        assert format(bits, "018b") == expected, f"версия {version}"


def test_quiet_zone_is_not_optional():
    """Поле вокруг кода обязано быть: без него камера не находит границу.

    Отказ здесь особенно неприятный — код «просто не читается», и виноватым
    выглядит телефон.
    """
    size, path = qr.svg_path(OTPAUTH)
    modules = len(qr.matrix(OTPAUTH))
    assert size == modules + 2 * qr.QUIET_ZONE
    assert qr.QUIET_ZONE >= 4, "стандарт требует четыре модуля поля"
    # Ни один прямоугольник не начинается раньше поля.
    assert "M0 " not in path and "M1 " not in path


def test_path_draws_exactly_the_dark_modules():
    """`d` для <path> обязан описывать РОВНО тёмные модули матрицы.

    Иначе получится код, который проверен тестом выше и при этом нарисован
    неправильно, — а видит это только камера.
    """
    m = qr.matrix(OTPAUTH)
    _, path = qr.svg_path(m and OTPAUTH)
    painted = set()
    for part in path.split("z"):
        if not part:
            continue
        head, rest = part[1:].split("h", 1)
        x, y = head.split(" ")
        width = int(rest.split("v")[0])
        for dx in range(width):
            painted.add((int(y) - qr.QUIET_ZONE, int(x) + dx - qr.QUIET_ZONE))
    expected = {(r, c) for r, row in enumerate(m) for c, dark in enumerate(row) if dark}
    assert painted == expected


def test_too_long_input_fails_loudly():
    """Не влезло — исключение, а не обрезанная строка.

    Обрезка дала бы код, который читается, но ведёт НЕ ТУДА: аутентификатор завёл
    бы запись с урезанным секретом, и человек узнал бы об этом при первом входе,
    когда исправить уже нечем.
    """
    with pytest.raises(ValueError):
        qr.matrix("A" * 300)


def test_reverse_a_broken_column_walk_is_caught():
    """Обратный ход: сторож обязан покраснеть от той самой ошибки, что тут была.

    В первой версии обход колонок сдвигался только на паре, попавшей на
    синхрополосу (`right == 6` вместо `right <= 6`): колонки левее шли внахлёст,
    нулевая не заполнялась вовсе. Код при этом рисовался целиком и выглядел
    настоящим. Проверяем, что декодер такое ловит, — иначе весь файл выше
    зелёный при нечитаемом коде.
    """
    words = qr._interleave(qr._bitstream(OTPAUTH.encode(), 8), 8)
    canvas = qr._Canvas(8)
    canvas.draw_function_patterns()
    # Дословно сломанный обход.
    size, i, total = canvas.size, 0, len(words) * 8
    for right in range(size - 1, 0, -2):
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                col = right - j
                upward = ((right + 1) & 2) == 0
                row = (size - 1 - vert) if upward else vert
                if not canvas.fixed[row][col] and i < total:
                    canvas.m[row][col] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
    canvas.apply_mask(0)
    canvas.draw_format(0)
    with pytest.raises(AssertionError):
        decode(canvas.m)
