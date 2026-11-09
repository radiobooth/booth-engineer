"""A small QR code maker for Booth's page: the phone page's address as a QR code, made on this computer so
the page loads nothing from the internet. Byte mode, error correction level M, versions 1 to 10 (up to 213
bytes), which is plenty for a web address. The algorithm follows ISO/IEC 18004."""

from functools import lru_cache

# Error correction level M, versions 1 to 10: (codewords of error correction per block, number of blocks).
_ECC_M = [(10, 1), (16, 1), (26, 1), (18, 2), (24, 2), (16, 4), (18, 4), (22, 4), (22, 5), (26, 5)]
_FORMAT_M = 0  # the two format bits for level M
MAX_VERSION = len(_ECC_M)


def _raw_modules(ver: int) -> int:
    """How many modules a version has for data and error correction (everything but the fixed patterns)."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        result -= (25 * align - 10) * align - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int) -> int:
    ecc, blocks = _ECC_M[ver - 1]
    return _raw_modules(ver) // 8 - ecc * blocks


def _alignment(ver: int) -> list[int]:
    if ver == 1:
        return []
    size, count = ver * 4 + 17, ver // 7 + 2
    step = (ver * 8 + count * 3 + 5) // (count * 4 - 4) * 2
    return [6] + sorted(size - 7 - i * step for i in range(count - 1))


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _codewords(data: bytes) -> tuple[int, list[int]]:
    """The smallest version that holds `data`, and its codewords with error correction, interleaved."""
    for ver in range(1, MAX_VERSION + 1):
        count_bits = 8 if ver < 10 else 16
        if 4 + count_bits + 8 * len(data) <= _data_codewords(ver) * 8:
            break
    else:
        raise ValueError(f"too long for a QR code here ({len(data)} bytes)")
    capacity = _data_codewords(ver) * 8
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11

    ecc_len, blocks_n = _ECC_M[ver - 1]
    raw = _raw_modules(ver) // 8
    short_n = blocks_n - raw % blocks_n
    short_len = raw // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(blocks_n):
        dat = words[k : k + short_len - ecc_len + (0 if i < short_n else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, divisor)
        if i < short_n:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_n:
                out.append(block[i])
    return ver, out


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def _penalty(m: list[list[bool]]) -> int:
    """A rough score of how hard the code is to scan (runs, 2x2 blocks, dark/light balance): lower wins."""
    size, score = len(m), 0
    for lines in (m, list(zip(*m, strict=True))):
        for line in lines:
            run = 1
            for a, b in zip(line, line[1:], strict=False):
                run = run + 1 if a == b else 1
                score += 3 if run == 5 else 1 if run > 5 else 0
    for y in range(size - 1):
        for x in range(size - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(map(sum, m))
    return score + abs(dark * 20 - size * size * 10) // (size * size) * 10


def matrix(text: str) -> list[list[bool]]:
    """The QR code for `text` as rows of modules (True is dark), without the quiet zone around it."""
    ver, words = _codewords(text.encode())
    size = ver * 4 + 17
    m = [[False] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def put(x: int, y: int, dark: bool) -> None:
        m[y][x] = dark
        fixed[y][x] = True

    for i in range(size):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if 0 <= cx + dx < size and 0 <= cy + dy < size:
                    put(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    align = _alignment(ver)
    last = len(align) - 1
    for i, ax in enumerate(align):
        for j, ay in enumerate(align):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def put_format(mask: int) -> None:
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = [(bits >> i) & 1 == 1 for i in range(15)]
        for i in range(6):
            put(8, i, bit[i])
        put(8, 7, bit[6])
        put(8, 8, bit[7])
        put(7, 8, bit[8])
        for i in range(9, 15):
            put(14 - i, 8, bit[i])
        for i in range(8):
            put(size - 1 - i, 8, bit[i])
        for i in range(8, 15):
            put(8, size - 15 + i, bit[i])
        put(8, size - 8, True)

    put_format(0)  # reserves the format areas; the real bits go in once the mask is chosen
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = ver << 12 | rem
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            put(a, b, (bits >> i) & 1 == 1)
            put(b, a, (bits >> i) & 1 == 1)

    i, right = 0, size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fixed[y][x] and i < len(words) * 8:
                    m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
        right -= 2

    data_m = [row[:] for row in m]
    best = None
    for mask, rule in enumerate(_MASKS):
        m[:] = [[data_m[y][x] != (not fixed[y][x] and rule(x, y)) for x in range(size)] for y in range(size)]
        put_format(mask)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, [row[:] for row in m])
    return best[1]


@lru_cache(maxsize=4)
def svg(text: str, dark: str = "#1C1B1D", light: str = "#EFEAE1") -> str:
    """The QR code for `text` as a small SVG, with the usual four-module quiet zone."""
    m = matrix(text)
    size = len(m) + 8
    path = "".join(
        f"M{x + 4} {y + 4}h1v1h-1z" for y, row in enumerate(m) for x, dark_ in enumerate(row) if dark_
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="{light}"/><path d="{path}" fill="{dark}"/></svg>'
    )
