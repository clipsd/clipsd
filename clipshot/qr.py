# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""QR code for "Photo from phone": a small encoder of our own, no new dependency.

Only what the address of the receiving page needs: byte mode, versions 1-10 (up to 213 bytes at level M),
error correction L/M/Q/H, the mask with the lowest penalty. The algorithm follows ISO/IEC 18004 in the
form Project Nayuki describes it (https://www.nayuki.io/page/qr-code-generator-library, MIT): the same
tables of error correction blocks, the Reed-Solomon divisor over GF(2^8) with 0x11D, the zigzag placement.
tests/phone_test.py checks the Reed-Solomon remainder and the format bits; the decoding of every version by an
independent reader (zxing-cpp) is checked when that reader is installed (not a dependency of ClipSD).

encode(text) -> list of rows of bool (True = dark), without the quiet zone (4 modules are added by the painter).
"""

ECL = {"L": 0, "M": 1, "Q": 2, "H": 3}
_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}
MAX_VERSION = 10
# index: version (0 unused); per level L, M, Q, H
_ECC_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28),
)
_NUM_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8),
)


class DataTooLong(ValueError):
    pass


def _raw_modules(ver: int) -> int:
    """Modules left for data and error correction after the function patterns."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def data_codewords(ver: int, ecl: str) -> int:
    e = ECL[ecl]
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[e][ver] * _NUM_BLOCKS[e][ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree: int) -> list:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data, divisor) -> list:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def format_bits(ecl: str, mask: int) -> int:
    """15 format bits (level, mask) with their BCH code, XOR 0x5412."""
    data = _FORMAT_BITS[ecl] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _version_bits(ver: int) -> int:
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return ver << 12 | rem


def _alignment_positions(ver: int) -> list:
    if ver == 1:
        return []
    n = ver // 7 + 2
    size = ver * 4 + 17
    step = (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    return [6] + [size - 7 - i * step for i in reversed(range(n - 1))]


def _bits(value: int, count: int):
    return [(value >> i) & 1 for i in reversed(range(count))]


def pick_version(n_bytes: int, ecl: str) -> int:
    for ver in range(1, MAX_VERSION + 1):
        count_bits = 8 if ver <= 9 else 16
        if 4 + count_bits + 8 * n_bytes <= data_codewords(ver, ecl) * 8:
            return ver
    raise DataTooLong(f"{n_bytes} bytes do not fit into version {MAX_VERSION} at level {ecl}")


def _codewords(data: bytes, ver: int, ecl: str) -> list:
    bits = [0, 1, 0, 0] + _bits(len(data), 8 if ver <= 9 else 16)
    for b in data:
        bits += _bits(b, 8)
    capacity = data_codewords(ver, ecl) * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    # error correction per block, then interleave
    e = ECL[ecl]
    num_blocks, ecc_len = _NUM_BLOCKS[e][ver], _ECC_PER_BLOCK[e][ver]
    raw = _raw_modules(ver) // 8
    num_short = num_blocks - raw % num_blocks
    short_len = raw // num_blocks
    divisor = rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(num_blocks):
        dat = words[k:k + short_len - ecc_len + (0 if i < num_short else 1)]
        k += len(dat)
        ecc = rs_remainder(dat, divisor)
        if i < num_short:
            dat = dat + [0]
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= num_short:
                result.append(blk[i])
    return result


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Matrix:
    def __init__(self, ver: int):
        self.ver = ver
        self.size = ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_f(self, x, y, dark):
        self.dark[y][x] = bool(dark)
        self.function[y][x] = True

    def draw_function_patterns(self):
        size = self.size
        for i in range(size):
            self.set_f(6, i, i % 2 == 0)
            self.set_f(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_f(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _alignment_positions(self.ver)
        last = len(pos) - 1
        for i, cx in enumerate(pos):
            for j, cy in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_f(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format("M", 0)   # reserve the areas; real bits after the mask is chosen
        if self.ver >= 7:
            bits = _version_bits(self.ver)
            for i in range(18):
                bit = (bits >> i) & 1
                a, b = size - 11 + i % 3, i // 3
                self.set_f(a, b, bit)
                self.set_f(b, a, bit)

    def draw_format(self, ecl: str, mask: int):
        bits = format_bits(ecl, mask)
        size = self.size
        bit = lambda i: (bits >> i) & 1   # noqa: E731
        for i in range(6):
            self.set_f(8, i, bit(i))
        self.set_f(8, 7, bit(6))
        self.set_f(8, 8, bit(7))
        self.set_f(7, 8, bit(8))
        for i in range(9, 15):
            self.set_f(14 - i, 8, bit(i))
        for i in range(8):
            self.set_f(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_f(8, size - 15 + i, bit(i))
        self.set_f(8, size - 8, True)   # the dark module

    def draw_codewords(self, words):
        size, i, total = self.size, 0, len(words) * 8
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.function[y][x] and i < total:
                        self.dark[y][x] = bool((words[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1
            right -= 2

    def apply_mask(self, mask: int):
        f = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.function[y][x] and f(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        size, rows = self.size, self.dark
        cols = [[rows[y][x] for y in range(size)] for x in range(size)]
        score = 0
        finder_a = [True, False, True, True, True, False, True, False, False, False, False]
        finder_b = finder_a[::-1]
        for line in rows + cols:
            run, color = 1, line[0]
            for v in line[1:]:
                if v == color:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run, color = 1, v
            if run >= 5:
                score += 3 + run - 5
            for i in range(size - 10):
                window = line[i:i + 11]
                if window == finder_a or window == finder_b:
                    score += 40
        for y in range(size - 1):
            for x in range(size - 1):
                c = rows[y][x]
                if c == rows[y][x + 1] == rows[y + 1][x] == rows[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(r) for r in rows)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        return score + k * 10


def encode(text, ecl: str = "M") -> list:
    """Matrix of the QR code for text (str is sent as UTF-8). Rows of bool, True = dark, no quiet zone."""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    ver = pick_version(len(data), ecl)
    words = _codewords(data, ver, ecl)
    best, best_score = None, None
    for mask in range(8):
        m = _Matrix(ver)
        m.draw_function_patterns()
        m.draw_codewords(words)
        m.apply_mask(mask)
        m.draw_format(ecl, mask)
        score = m.penalty()
        if best_score is None or score < best_score:
            best, best_score = m, score
    return best.dark
