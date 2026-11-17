"""按钮等简单控件。"""
from __future__ import annotations

import pygame

from . import theme as T


class Button:
    def __init__(self, rect, label: str, size: int = 18, enabled: bool = True, color=None, key: str | None = None,
                 tooltip: str = ""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.size = size
        self.enabled = enabled
        self.color = color or T.PANEL_LIGHT
        self.key = key          # 可选的标识，方便一组按钮里区分
        self.tooltip = tooltip
        self.hover = False
        self.selected = False

    def handle(self, ev: pygame.event.Event) -> bool:
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.enabled and self.rect.collidepoint(ev.pos):
                return True
        return False

    def draw(self, surf: pygame.Surface) -> None:
        if not self.enabled:
            col, fg = (50, 48, 56), T.TEXT_DIM
        elif self.selected:
            col, fg = (110, 95, 60), T.HILITE
        elif self.hover:
            col, fg = tuple(min(255, c + 25) for c in self.color), T.HILITE
        else:
            col, fg = self.color, T.TEXT
        T.panel(surf, self.rect, col, T.BORDER if self.enabled else (80, 75, 85), radius=5)
        T.text(surf, self.label, self.rect.center, self.size, fg, align="center")


class Tooltip:
    """鼠标悬停提示，画在最上层。"""

    @staticmethod
    def draw(surf: pygame.Surface, s: str, pos: tuple[int, int], size: int = 15, width: int = 320) -> None:
        if not s:
            return
        lines = T.wrap(s, size, width - 16)
        w = min(width, max(T.font(size).size(l)[0] for l in lines) + 16)
        h = len(lines) * (size + 4) + 10
        x, y = pos[0] + 14, pos[1] + 14
        if x + w > surf.get_width():
            x = surf.get_width() - w - 4
        if y + h > surf.get_height():
            y = pos[1] - h - 6
        T.panel(surf, pygame.Rect(x, y, w, h), (30, 28, 36), T.GOLD, radius=4, width=1)
        for i, l in enumerate(lines):
            T.text(surf, l, (x + 8, y + 5 + i * (size + 4)), size)
