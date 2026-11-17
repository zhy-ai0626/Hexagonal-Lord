"""界面公共部分：中文字体、配色、画文字和面板的小工具。"""
from __future__ import annotations

import os

import pygame

SCREEN_W, SCREEN_H = 1280, 800

# 配色
BG = (24, 22, 30)
PANEL = (44, 40, 52)
PANEL_LIGHT = (62, 57, 72)
BORDER = (120, 105, 80)
GOLD = (236, 200, 90)
TEXT = (235, 230, 220)
TEXT_DIM = (160, 152, 140)
GREEN = (90, 200, 110)
RED = (230, 80, 70)
BLUE = (90, 140, 240)
HILITE = (255, 240, 150)
SHADOW = (0, 0, 0, 120)

TERRAIN_COLORS = {
    0: (96, 150, 70),     # 草地
    1: (150, 130, 90),    # 荒原
    2: (80, 110, 80),     # 沼泽
    3: (210, 215, 225),   # 雪地
    4: (170, 150, 110),   # 道路
    5: (40, 90, 45),      # 树林
    6: (110, 100, 100),   # 山脉
    7: (50, 90, 170),     # 水域
}
RESOURCE_COLORS = {
    "gold": (240, 200, 60), "wood": (150, 100, 50), "ore": (140, 140, 150),
    "crystal": (120, 200, 240), "stardust": (240, 240, 150), "mithril": (190, 120, 230),
}

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
_font_path: str | None = None
_fonts: dict[tuple[int, bool], pygame.font.Font] = {}


def font(size: int, bold: bool = False) -> pygame.font.Font:
    global _font_path
    key = (size, bold)
    if key in _fonts:
        return _fonts[key]
    if _font_path is None:
        for p in _FONT_CANDIDATES:
            if os.path.exists(p):
                _font_path = p
                break
        if _font_path is None:
            _font_path = pygame.font.match_font("notosanscjksc,wqymicrohei,arialunicode") or ""
    f = pygame.font.Font(_font_path or None, size)
    f.set_bold(bold)
    _fonts[key] = f
    return f


def text(surf: pygame.Surface, s: str, pos: tuple[int, int], size: int = 18, color=TEXT,
         align: str = "left", bold: bool = False, shadow: bool = False) -> pygame.Rect:
    img = font(size, bold).render(s, True, color)
    r = img.get_rect()
    if align == "left":
        r.topleft = pos
    elif align == "center":
        r.center = pos
    elif align == "right":
        r.topright = pos
    elif align == "midleft":
        r.midleft = pos
    if shadow:
        sh = font(size, bold).render(s, True, (0, 0, 0))
        surf.blit(sh, r.move(1, 1))
    surf.blit(img, r)
    return r


def wrap(s: str, size: int, width: int) -> list[str]:
    """按像素宽度把中文/英文混排文本折行（中文按字折，英文按词折）。"""
    f = font(size)
    lines: list[str] = []
    for para in s.split("\n"):
        cur = ""
        for ch in para:
            if f.size(cur + ch)[0] > width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def text_block(surf: pygame.Surface, s: str, rect: pygame.Rect, size: int = 18, color=TEXT, line_gap: int = 4) -> int:
    """在 rect 内折行画文字，返回用掉的高度。"""
    y = rect.y
    for line in wrap(s, size, rect.w):
        text(surf, line, (rect.x, y), size, color)
        y += size + line_gap
    return y - rect.y


def panel(surf: pygame.Surface, rect: pygame.Rect, color=PANEL, border=BORDER, radius: int = 6, width: int = 2) -> None:
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, rect, width, border_radius=radius)


def dim(surf: pygame.Surface, alpha: int = 140) -> None:
    s = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    s.fill((0, 0, 0, alpha))
    surf.blit(s, (0, 0))


def icon_circle(surf: pygame.Surface, center: tuple[int, int], radius: int, color, label: str = "",
                size: int = 14, border=(20, 20, 20)) -> None:
    pygame.draw.circle(surf, color, center, radius)
    pygame.draw.circle(surf, border, center, radius, 2)
    if label:
        text(surf, label, center, size, (15, 15, 15), align="center", bold=True)


def resource_name(res: str) -> str:
    from ..core.data import get_data
    return get_data().resource_names.get(res, res)


def cost_text(cost: dict) -> str:
    return "，".join(f"{resource_name(r)} {n}" for r, n in cost.items() if n) or "免费"
