"""Pure-Python ISO/IEC 18004 QR Code matrix & QPixmap generator (Versions 1–6, EC Level L, Byte Mode)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


# Version -> (total_data_codewords, ec_codewords_per_block, num_blocks, alignment_centers)
_VERSION_SPECS: dict[int, tuple[int, int, int, list[int]]] = {
    1: (19, 7, 1, []),
    2: (34, 10, 1, [6, 18]),
    3: (55, 15, 1, [6, 22]),
    4: (80, 20, 1, [6, 26]),
    5: (108, 26, 1, [6, 30]),
    6: (136, 18, 2, [6, 34]),
}

# Galois Field GF(256) with primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        root = _GF_EXP[i]
        for j, coeff in enumerate(poly):
            next_poly[j] ^= coeff
            next_poly[j + 1] ^= _gf_mul(coeff, root)
        poly = next_poly
    return poly


def _rs_encode(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator_poly(ec_len)
    rem = [0] * ec_len
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        if factor != 0:
            for j in range(ec_len):
                rem[j] ^= _gf_mul(gen[j + 1], factor)
    return rem


def _format_bits(ec_level_bits: int, mask_pattern: int) -> int:
    data = (ec_level_bits << 3) | mask_pattern
    rem = data << 10
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= 0x537 << (i - 10)
    return ((data << 10) | rem) ^ 0x5412


def encode_qr_matrix(text: str) -> list[list[bool]]:
    """Encodes a UTF-8 string (up to 134 bytes) into a 2D boolean QR Code matrix (EC Level L)."""
    payload = text.encode("utf-8")
    ver = 1
    for v, (cap, _, _, _) in _VERSION_SPECS.items():
        if len(payload) + 2 <= cap:
            ver = v
            break
    else:
        raise ValueError("QR payload exceeds 134 UTF-8 bytes; refusing to truncate credentials")

    total_data_cw, ec_cw_per_block, num_blocks, align_centers = _VERSION_SPECS[ver]

    # Build bit stream: Byte Mode (0100) + 8-bit char count + payload + terminator + pad
    bits: list[int] = [0, 1, 0, 0]
    for i in range(7, -1, -1):
        bits.append((len(payload) >> i) & 1)
    for b in payload:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    max_bits = total_data_cw * 8
    for _ in range(min(4, max_bits - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = [
        sum(bits[i + k] << (7 - k) for k in range(8))
        for i in range(0, len(bits), 8)
    ]
    pad_seq = [0xEC, 0x11]
    pad_idx = 0
    while len(data_bytes) < total_data_cw:
        data_bytes.append(pad_seq[pad_idx % 2])
        pad_idx += 1

    # Split into blocks and compute Reed-Solomon EC codewords
    block_size = total_data_cw // num_blocks
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    for b_idx in range(num_blocks):
        blk = data_bytes[b_idx * block_size : (b_idx + 1) * block_size]
        data_blocks.append(blk)
        ec_blocks.append(_rs_encode(blk, ec_cw_per_block))

    interleaved: list[int] = []
    for i in range(block_size):
        for b_idx in range(num_blocks):
            interleaved.append(data_blocks[b_idx][i])
    for i in range(ec_cw_per_block):
        for b_idx in range(num_blocks):
            interleaved.append(ec_blocks[b_idx][i])

    final_bits: list[int] = []
    for cw in interleaved:
        for i in range(7, -1, -1):
            final_bits.append((cw >> i) & 1)
    if ver in (2, 3, 4, 5, 6):
        final_bits.extend([0] * 7)

    size = 17 + 4 * ver
    grid: list[list[bool | None]] = [[None] * size for _ in range(size)]
    reserved: list[list[bool]] = [[False] * size for _ in range(size)]

    def _set_func(r: int, c: int, val: bool) -> None:
        if 0 <= r < size and 0 <= c < size:
            grid[r][c] = val
            reserved[r][c] = True

    def _place_finder(top_r: int, left_c: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top_r + dr, left_c + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = (0 <= dr <= 6 and (dc in (0, 6))) or (0 <= dc <= 6 and (dr in (0, 6)))
                    in_inner = 2 <= dr <= 4 and 2 <= dc <= 4
                    _set_func(r, c, in_outer or in_inner)

    _place_finder(0, 0)
    _place_finder(0, size - 7)
    _place_finder(size - 7, 0)

    # Alignment patterns
    for ar in align_centers:
        for ac in align_centers:
            if (ar == 6 and ac == 6) or (ar == 6 and ac == size - 7) or (ar == size - 7 and ac == 6):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = max(abs(dr), abs(dc)) in (0, 2)
                    _set_func(ar + dr, ac + dc, val)

    # Timing patterns
    for i in range(8, size - 8):
        if not reserved[6][i]:
            _set_func(6, i, i % 2 == 0)
        if not reserved[i][6]:
            _set_func(i, 6, i % 2 == 0)

    # Dark module & format info reservation
    _set_func(4 * ver + 9, 8, True)
    for i in range(9):
        if i != 6:
            reserved[8][i] = True
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # Place data bits in upward/downward 2-column zig-zag
    bit_idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if upward else range(size)
        for r in row_iter:
            for dc in (0, -1):
                c = col + dc
                if not reserved[r][c]:
                    grid[r][c] = bool(final_bits[bit_idx]) if bit_idx < len(final_bits) else False
                    bit_idx += 1
        upward = not upward
        col -= 2

    # Apply mask pattern 0 ((r + c) % 2 == 0) and write format info (EC Level L = 0b01)
    mask_id = 0
    out: list[list[bool]] = [[False] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            val = bool(grid[r][c])
            if not reserved[r][c] and ((r + c) % 2 == 0):
                val = not val
            out[r][c] = val

    fmt = _format_bits(0b01, mask_id)
    fmt_bits = [(fmt >> i) & 1 == 1 for i in range(15)]

    # Top-left format info
    tl_coords_r = [8, 8, 8, 8, 8, 8, 8, 8, 7, 5, 4, 3, 2, 1, 0]
    tl_coords_c = [0, 1, 2, 3, 4, 5, 7, 8, 8, 8, 8, 8, 8, 8, 8]
    for idx in range(15):
        out[tl_coords_r[idx]][tl_coords_c[idx]] = fmt_bits[14 - idx]

    # Bottom-left & top-right format info
    for idx in range(7):
        out[size - 1 - idx][8] = fmt_bits[14 - idx]
    for idx in range(7, 15):
        out[8][size - 15 + idx] = fmt_bits[14 - idx]

    return out


def render_qr_pixmap(text: str, module_px: int = 6, border_modules: int = 3) -> QPixmap:
    """Renders a crisp black-on-white QR code QPixmap for the given URL/string."""
    matrix = encode_qr_matrix(text)
    n = len(matrix)
    total_modules = n + border_modules * 2
    img_px = total_modules * module_px

    img = QImage(img_px, img_px, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))

    painter = QPainter(img)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0f172a"))
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                painter.drawRect(
                    (c + border_modules) * module_px,
                    (r + border_modules) * module_px,
                    module_px,
                    module_px,
                )
    painter.end()
    return QPixmap.fromImage(img)
