"""Модуль двухфакторной аутентификации 2FA TOTP (RFC 6238) и генерации QR-кодов для Aliasarr.
Полностью автономен, не требует сторонних библиотек и сетевых запросов.
Совместим с Google Authenticator, Authy, Apple Passwords, 1Password, Bitwarden, YubiKey и др.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
from typing import Any, Optional


# =============================================================================
# RFC 6238 TOTP (Time-Based One-Time Password) Engine
# =============================================================================

BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_totp_secret(length: int = 32) -> str:
    """Генерирует криптографически стойкий случайный Base32 секретный ключ."""
    # Генерируем 20 байт (160 бит, стандарт для SHA-1)
    random_bytes = secrets.token_bytes(20)
    # Кодируем в base32 без символов padding (=)
    b32 = base64.b32encode(random_bytes).decode("ascii").rstrip("=")
    return b32[:length] if len(b32) >= length else b32


def _normalize_secret(secret: str) -> bytes:
    """Очищает секретный ключ и декодирует его из Base32."""
    clean = "".join(c for c in secret.upper() if c in BASE32_ALPHABET)
    # Добавляем padding при необходимости
    missing_padding = len(clean) % 8
    if missing_padding:
        clean += "=" * (8 - missing_padding)
    return base64.b32decode(clean.encode("ascii"))


def generate_totp_code(secret: str, timestamp: Optional[float] = None, period: int = 30, digits: int = 6) -> str:
    """Генерирует текущий 6-значный TOTP-код по секретному ключу."""
    key = _normalize_secret(secret)
    t = int(timestamp if timestamp is not None else time.time())
    counter = t // period
    counter_bytes = struct.pack(">Q", counter)

    digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    code = code_int % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp_code(secret: str, code: str, window: int = 1, period: int = 30, digits: int = 6) -> bool:
    """Проверяет валидность TOTP-кода с окном допуска (+- window шагов по 30 сек)."""
    if not secret or not code:
        return False
    # Очищаем код от пробелов, тире и нецифровых символов
    clean_code = "".join(c for c in code if c.isdigit())
    if len(clean_code) != digits:
        return False

    now = time.time()
    for w in range(-window, window + 1):
        test_time = now + (w * period)
        if secrets.compare_digest(generate_totp_code(secret, test_time, period, digits), clean_code):
            return True
    return False


def get_totp_auth_url(secret: str, username: str, issuer: str = "Aliasarr") -> str:
    """Формирует стандартный URI otpauth://totp для сканирования приложением-аутентификатором."""
    clean_secret = "".join(c for c in secret.upper() if c in BASE32_ALPHABET)
    label = f"{issuer}:{username}"
    # Стандартные параметры TOTP (совместимы со всеми мобильными сканерами и камерами)
    params = {
        "secret": clean_secret,
        "issuer": issuer,
    }
    query_str = urllib.parse.urlencode(params)
    return f"otpauth://totp/{urllib.parse.quote(label)}?{query_str}"


# =============================================================================
# Стандартный генератор QR-кодов ISO/IEC 18004 (Pure Python, без зависимостей)
# =============================================================================

# Поле Галуа GF(256) с образующим многочленом 0x11D (285)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x_val = 1
for _i in range(255):
    _GF_EXP[_i] = _x_val
    _GF_EXP[_i + 255] = _x_val
    _GF_LOG[_x_val] = _i
    _x_val = (_x_val << 1) ^ (0x11D if (_x_val & 0x80) else 0)


def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return _GF_EXP[_GF_LOG[x] + _GF_LOG[y]]


def _rs_generator_poly(ec_len: int) -> list[int]:
    poly = [1]
    for i in range(ec_len):
        factor = [1, _GF_EXP[i]]
        new_poly = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            new_poly[j] ^= c
            new_poly[j + 1] ^= _gf_mul(c, factor[1])
        poly = new_poly
    return poly


def _rs_encode(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator_poly(ec_len)
    res = list(data) + [0] * ec_len
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# Спецификации версий для уровней коррекции L и M:
# version -> (total_codewords, ec_codewords_per_block, [(num_blocks, data_codewords)])
_VERSION_SPECS_M = {
    1: (26, 10, [(1, 16)]),
    2: (44, 16, [(1, 28)]),
    3: (70, 26, [(1, 44)]),
    4: (100, 18, [(2, 32)]),
    5: (134, 24, [(2, 43)]),
    6: (172, 16, [(4, 27)]),
    7: (196, 18, [(4, 31)]),
    8: (242, 22, [(2, 38), (2, 39)]),
    9: (292, 22, [(3, 36), (2, 37)]),
    10: (346, 26, [(4, 43), (1, 44)]),
}

_VERSION_SPECS_L = {
    1: (26, 7, [(1, 19)]),
    2: (44, 10, [(1, 34)]),
    3: (70, 15, [(1, 55)]),
    4: (100, 20, [(1, 80)]),
    5: (134, 26, [(1, 108)]),
    6: (172, 18, [(2, 68)]),
    7: (196, 20, [(2, 78)]),
    8: (242, 24, [(2, 97)]),
    9: (292, 30, [(2, 116)]),
    10: (346, 18, [(2, 68), (2, 69)]),
}

_ALIGNMENT_LOCATIONS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

# 15-битные маски формата BCH(15,5) XOR 0x5412 для уровней L (01) и M (00)
_FORMAT_INFO_M = [
    0x5412, 0x5125, 0x5E7C, 0x5B4B,
    0x45F9, 0x40CE, 0x4F97, 0x4AA0,
]

_FORMAT_INFO_L = [
    0x77C4, 0x72F3, 0x7DAA, 0x789D,
    0x662F, 0x6318, 0x6C41, 0x6976,
]


def _encode_data_to_codewords(data_str: str, version: int, ec_level: str = "M") -> list[int]:
    data_bytes = data_str.encode("utf-8")
    specs = _VERSION_SPECS_M if ec_level == "M" else _VERSION_SPECS_L
    _, ec_per_block, block_specs = specs[version]
    total_data_codewords = sum(count * data_len for count, data_len in block_specs)

    # 1. Заголовок Byte Mode (0100) + счетчик символов
    bits = "0100"
    char_count_bits = 8 if version < 10 else 16
    bits += f"{len(data_bytes):0{char_count_bits}b}"

    # 2. Данные
    for b in data_bytes:
        bits += f"{b:08b}"

    # 3. Терминатор (до 4 нулей)
    max_data_bits = total_data_codewords * 8
    terminator_len = min(4, max_data_bits - len(bits))
    bits += "0" * terminator_len

    # 4. Выравнивание до байта
    if len(bits) % 8 != 0:
        bits += "0" * (8 - (len(bits) % 8))

    # 5. Заполнение байтами паддинга 0xEC, 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    data_codewords = [int(bits[i:i+8], 2) for i in range(0, len(bits), 8)]
    while len(data_codewords) < total_data_codewords:
        data_codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    # 6. Разбиение на блоки и подсчет Рида-Соломона
    blocks_data = []
    blocks_ec = []
    offset = 0
    for count, d_len in block_specs:
        for _ in range(count):
            block = data_codewords[offset:offset + d_len]
            offset += d_len
            blocks_data.append(block)
            blocks_ec.append(_rs_encode(block, ec_per_block))

    # 7. Чередование (Interleaving) данных
    final_codewords = []
    max_d_len = max(len(b) for b in blocks_data)
    for i in range(max_d_len):
        for block in blocks_data:
            if i < len(block):
                final_codewords.append(block[i])

    # 8. Чередование (Interleaving) кодов коррекции
    for i in range(ec_per_block):
        for block_ec in blocks_ec:
            final_codewords.append(block_ec[i])

    # 9. Битстрим + остаточные биты (Remainder bits)
    bit_stream = "".join(f"{b:08b}" for b in final_codewords)
    remainder_len = 7 if 2 <= version <= 6 else 0
    bit_stream += "0" * remainder_len
    return [int(bit) for bit in bit_stream]


def _evaluate_penalty(matrix: list[list[bool]]) -> int:
    """Вычисляет штрафной балл матрицы по 4 правилам ISO 18004."""
    size = len(matrix)
    penalty = 0

    # Правило 1: 5+ одинаковых подряд в строках и столбцах
    for r in range(size):
        run = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c-1]:
                run += 1
            else:
                if run >= 5:
                    penalty += 3 + (run - 5)
                run = 1
        if run >= 5:
            penalty += 3 + (run - 5)

    for c in range(size):
        run = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r-1][c]:
                run += 1
            else:
                if run >= 5:
                    penalty += 3 + (run - 5)
                run = 1
        if run >= 5:
            penalty += 3 + (run - 5)

    # Правило 2: блоки 2x2 одного цвета
    for r in range(size - 1):
        for c in range(size - 1):
            if matrix[r][c] == matrix[r+1][c] == matrix[r][c+1] == matrix[r+1][c+1]:
                penalty += 3

    # Правило 3: паттерны 1:1:3:1:1
    p1 = [False, False, False, False, True, False, True, True, True, False, True]
    p2 = [True, False, True, True, True, False, True, False, False, False, False]
    for r in range(size):
        for c in range(size - 10):
            window = [matrix[r][c+i] for i in range(11)]
            if window == p1 or window == p2:
                penalty += 40
    for c in range(size):
        for r in range(size - 10):
            window = [matrix[r+i][c] for i in range(11)]
            if window == p1 or window == p2:
                penalty += 40

    # Правило 4: баланс темных и светлых модулей
    dark_count = sum(sum(1 for cell in row if cell) for row in matrix)
    total_count = size * size
    pct = (dark_count * 100) // total_count
    penalty += (abs(pct - 50) // 5) * 10

    return penalty


def _build_matrix(version: int, bit_data: list[int], ec_level: str = "M") -> list[list[bool]]:
    size = 17 + 4 * version
    matrix = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(r: int, c: int, val: bool, is_reserved: bool = True):
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            if is_reserved:
                reserved[r][c] = True

    # 1. Шаблоны поиска (Finder Patterns 7x7 + 1px разделитель)
    def add_finder(r0: int, c0: int):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rf, cf = r0 + r, c0 + c
                if 0 <= rf < size and 0 <= cf < size:
                    if 0 <= r <= 6 and 0 <= c <= 6:
                        val = (r in (0, 6) or c in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4)
                        set_module(rf, cf, val)
                    else:
                        set_module(rf, cf, False)

    add_finder(0, 0)
    add_finder(0, size - 7)
    add_finder(size - 7, 0)

    # 2. Шаблоны синхронизации (Timing patterns)
    for i in range(size):
        if matrix[6][i] is None:
            set_module(6, i, i % 2 == 0)
        if matrix[i][6] is None:
            set_module(i, 6, i % 2 == 0)

    # 3. Шаблоны выравнивания (Alignment patterns для версии >= 2)
    locs = _ALIGNMENT_LOCATIONS.get(version, [])
    for r in locs:
        for c in locs:
            if (r <= 8 and c <= 8) or (r <= 8 and c >= size - 8) or (r >= size - 8 and c <= 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0))
                    set_module(r + dr, c + dc, val)

    # 4. Темный модуль
    set_module(size - 8, 8, True)

    # 5. Резервирование областей информации о формате
    for i in range(9):
        if i != 6:
            reserved[8][i] = True
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # 6. Маскирование данных
    mask_funcs = [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: (r // 2 + c // 3) % 2 == 0,
        lambda r, c: ((r * c) % 2) + ((r * c) % 3) == 0,
        lambda r, c: (((r * c) % 2) + ((r * c) % 3)) % 2 == 0,
        lambda r, c: (((r + c) % 2) + ((r * c) % 3)) % 2 == 0,
    ]

    best_mask = 0
    best_penalty = float("inf")
    best_matrix = None

    for mask_idx in range(8):
        mask_fn = mask_funcs[mask_idx]
        cur_matrix = [row[:] for row in matrix]
        data_idx = 0
        c = size - 1
        going_up = True

        while c > 0:
            if c == 6:
                c -= 1
            cols = [c, c - 1]
            rows = range(size - 1, -1, -1) if going_up else range(size)

            for r in rows:
                for col in cols:
                    if not reserved[r][col]:
                        bit_val = bool(bit_data[data_idx]) if data_idx < len(bit_data) else False
                        data_idx += 1
                        if mask_fn(r, col):
                            bit_val = not bit_val
                        cur_matrix[r][col] = bit_val

            going_up = not going_up
            c -= 2

        # Запись информации о формате (15 бит)
        fmt_bits = _FORMAT_INFO_M[mask_idx] if ec_level == "M" else _FORMAT_INFO_L[mask_idx]
        for i in range(15):
            bit = bool((fmt_bits >> (14 - i)) & 1)
            # Позиция 1 (вокруг верхнего левого шаблона поиска)
            if i <= 5:
                cur_matrix[8][i] = bit
            elif i == 6:
                cur_matrix[8][7] = bit
            elif i == 7:
                cur_matrix[8][8] = bit
            elif i == 8:
                cur_matrix[7][8] = bit
            else:
                cur_matrix[14 - i][8] = bit

            # Позиция 2 (разделена между нижним левым и верхним правым)
            if i < 7:
                cur_matrix[size - 1 - i][8] = bit
            else:
                cur_matrix[8][size - 15 + i] = bit

        score = _evaluate_penalty(cur_matrix)
        if score < best_penalty:
            best_penalty = score
            best_mask = mask_idx
            best_matrix = cur_matrix

    return [[bool(cell) for cell in row] for row in best_matrix]


def _generate_qr_matrix(text: str, ec_level: str = "M") -> list[list[bool]]:
    """Генерирует стандартную QR-матрицу ISO/IEC 18004."""
    data_len = len(text.encode("utf-8"))
    specs = _VERSION_SPECS_M if ec_level == "M" else _VERSION_SPECS_L
    chosen_version = None

    for v in range(1, 11):
        _, _, block_specs = specs[v]
        total_data = sum(count * d_len for count, d_len in block_specs)
        header_len = 2 if v < 10 else 3
        if data_len + header_len <= total_data:
            chosen_version = v
            break

    if chosen_version is None:
        chosen_version = 10

    bit_data = _encode_data_to_codewords(text, chosen_version, ec_level)
    return _build_matrix(chosen_version, bit_data, ec_level)


def generate_qr_code_svg(data: str, size: int = 220) -> str:
    """Генерирует высококонтрастный стандартный SVG Data-URL изображения QR-кода."""
    matrix = _generate_qr_matrix(data, ec_level="M")
    module_count = len(matrix)
    padding = 4  # Стандартная белая рамка (Quiet Zone) в 4 модуля
    total_size = module_count + (padding * 2)
    view_box = f"0 0 {total_size} {total_size}"

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" width="{size}" height="{size}" shape-rendering="crispEdges">',
        f'<rect width="{total_size}" height="{total_size}" fill="#ffffff"/>',
    ]

    path_data = []
    for r in range(module_count):
        for c in range(module_count):
            if matrix[r][c]:
                path_data.append(f"M{c + padding},{r + padding}h1v1h-1z")

    svg_parts.append(f'<path d="{" ".join(path_data)}" fill="#000000"/>')
    svg_parts.append("</svg>")

    svg_xml = "".join(svg_parts)
    encoded = urllib.parse.quote(svg_xml)
    return f"data:image/svg+xml;utf8,{encoded}"

