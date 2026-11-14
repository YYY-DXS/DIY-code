"""程序图标：不依赖任何图形库，用纯 Python 生成 PNG / ICO。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

ACCENT = (34, 211, 238)     # 青
VIOLET = (139, 92, 246)     # 紫
INK = (10, 14, 20)          # 深墨


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _dist_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _rounded_alpha(x: float, y: float, size: float, radius: float) -> float:
    """圆角矩形内部的软边遮罩（0=外，1=内）。"""

    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    inside_box = -min(x, y, size - x, size - y)
    signed = d - radius if (x < radius or x > size - radius or y < radius or y > size - radius) else inside_box
    return max(0.0, min(1.0, 0.5 - signed))


def render(size: int, samples: int = 2) -> list[list[tuple[int, int, int, int]]]:
    """渲染 RGBA 像素矩阵。"""

    s = float(size)
    radius = s * 0.235
    stroke = s * 0.048
    half_h = s * 0.155
    chev_w = s * 0.105
    gap = s * 0.165
    apex_x = s * 0.345
    cy = s / 2

    rows: list[list[tuple[int, int, int, int]]] = []
    step = 1.0 / samples
    for py in range(size):
        row: list[tuple[int, int, int, int]] = []
        for px in range(size):
            accum = [0.0, 0.0, 0.0, 0.0]
            for i in range(samples):
                for j in range(samples):
                    x = px + (i + 0.5) * step
                    y = py + (j + 0.5) * step
                    mask = _rounded_alpha(x, y, s, radius)
                    if mask <= 0:
                        continue
                    t = (x / s * 0.42 + y / s * 0.58)
                    base = _lerp(ACCENT, VIOLET, t)
                    # 左上微微提亮，右下压暗，做出玻璃感
                    depth = (x + y) / (2 * s)
                    shade = 1.0 + 0.10 * (1 - depth) - 0.22 * depth
                    base = tuple(min(255, max(0, int(v * shade))) for v in base)

                    glyph = 1.0
                    for k in range(2):
                        x0 = apex_x + k * gap
                        d1 = _dist_to_segment(x, y, x0, cy - half_h, x0 + chev_w, cy)
                        d2 = _dist_to_segment(x, y, x0 + chev_w, cy, x0, cy + half_h)
                        d = min(d1, d2)
                        cover = max(0.0, min(1.0, (stroke - d) / 1.6 + 0.5))
                        glyph = min(glyph, 1.0 - cover)
                    color = _lerp(base, INK, (1.0 - glyph) * 0.94)

                    accum[0] += color[0] * mask
                    accum[1] += color[1] * mask
                    accum[2] += color[2] * mask
                    accum[3] += 255 * mask
            total = samples * samples
            r, g, b = (int(round(accum[k] / max(accum[3] / 255, 1e-6))) for k in range(3))
            alpha = int(round(accum[3] / total))
            row.append((min(255, r), min(255, g), min(255, b), alpha))
        rows.append(row)
    return rows


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def to_png(rows: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(rows)
    width = len(rows[0])
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for r, g, b, a in row:
            raw.extend((r, g, b, a))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def to_ico(sizes: list[tuple[int, bytes]]) -> bytes:
    count = len(sizes)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blobs = b""
    for size, png in sizes:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    return header + entries + blobs


def ensure_assets(force: bool = False) -> dict[str, Path]:
    """生成 assets/lumen.png 与 assets/lumen.ico（已存在则跳过）。"""

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    png_path = ASSETS_DIR / "lumen.png"
    ico_path = ASSETS_DIR / "lumen.ico"
    if force or not png_path.exists():
        png_path.write_bytes(to_png(render(256)))
    if force or not ico_path.exists():
        sizes = [(s, to_png(render(s, samples=3))) for s in (16, 32, 48, 64, 256)]
        ico_path.write_bytes(to_ico(sizes))
    return {"png": png_path, "ico": ico_path}


if __name__ == "__main__":
    paths = ensure_assets(force=True)
    for name, path in paths.items():
        print(f"{name}: {path}")
