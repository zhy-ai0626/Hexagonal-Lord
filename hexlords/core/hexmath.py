"""战场六角格几何。

战场是 15 列 × 11 行的"odd-r"偏移坐标（奇数行向右错开半格），和英雄无敌 3 一样。
(col, row) 叫 offset 坐标；算距离时转成 cube 坐标 (x, y, z)，x+y+z=0。
"""
from __future__ import annotations

BATTLE_W = 15
BATTLE_H = 11

# odd-r 偏移坐标的 6 个邻居方向：偶数行和奇数行不同
_EVEN = [(+1, 0), (0, -1), (-1, -1), (-1, 0), (-1, +1), (0, +1)]
_ODD = [(+1, 0), (+1, -1), (0, -1), (-1, 0), (0, +1), (+1, +1)]


def in_bounds(c: int, r: int) -> bool:
    return 0 <= c < BATTLE_W and 0 <= r < BATTLE_H


def neighbors(c: int, r: int) -> list[tuple[int, int]]:
    dirs = _ODD if r % 2 else _EVEN
    out = []
    for dc, dr in dirs:
        nc, nr = c + dc, r + dr
        if in_bounds(nc, nr):
            out.append((nc, nr))
    return out


def to_cube(c: int, r: int) -> tuple[int, int, int]:
    x = c - (r - (r & 1)) // 2
    z = r
    y = -x - z
    return x, y, z


def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    ax, ay, az = to_cube(*a)
    bx, by, bz = to_cube(*b)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def area(center: tuple[int, int], radius: int = 1) -> list[tuple[int, int]]:
    """以 center 为中心、半径 radius 内（含中心）的所有格子。"""
    out = []
    for r in range(BATTLE_H):
        for c in range(BATTLE_W):
            if distance(center, (c, r)) <= radius:
                out.append((c, r))
    return out


def hex_to_pixel(c: int, r: int, size: float) -> tuple[float, float]:
    """尖顶六角形（pointy-top）的中心像素坐标，size 是外接圆半径。"""
    import math
    w = math.sqrt(3) * size
    x = w * (c + 0.5 * (r & 1))
    y = 1.5 * size * r
    return x, y


def pixel_to_hex(px: float, py: float, size: float) -> tuple[int, int]:
    """像素坐标 → 最近的 offset 坐标（按 hex_to_pixel 的布局反推）。"""
    import math
    q = (math.sqrt(3) / 3 * px - 1.0 / 3 * py) / size
    rr = (2.0 / 3 * py) / size
    # cube round
    x, z = q, rr
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    col = rx + (rz - (rz & 1)) // 2
    return int(col), int(rz)
