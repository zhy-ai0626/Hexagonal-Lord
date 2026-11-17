"""对话框：消息、选择、升级、输入数量。都是 overlay 场景，用 run_modal 同步弹出。"""
from __future__ import annotations

import pygame

from ..core.data import get_data
from ..core.hero import PRIMARY_NAMES
from . import theme as T
from .app import Scene
from .widgets import Button


class MessageDialog(Scene):
    overlay = True

    def __init__(self, app, text: str, title: str = ""):
        super().__init__(app)
        self.text, self.title = text, title
        self.lines = T.wrap(text, 18, 520)
        h = 90 + len(self.lines) * 24 + 50
        self.rect = pygame.Rect(0, 0, 580, h)
        self.rect.center = (T.SCREEN_W // 2, T.SCREEN_H // 2)
        self.ok = Button((self.rect.centerx - 60, self.rect.bottom - 52, 120, 36), "确定")

    def handle(self, ev):
        if self.ok.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE)):
            self.done = True

    def draw(self, surf):
        T.dim(surf, 110)
        T.panel(surf, self.rect)
        y = self.rect.y + 16
        if self.title:
            T.text(surf, self.title, (self.rect.centerx, y + 10), 22, T.GOLD, align="center", bold=True)
            y += 40
        for l in self.lines:
            T.text(surf, l, (self.rect.x + 30, y), 18)
            y += 24
        self.ok.draw(surf)


class ChoiceDialog(Scene):
    overlay = True

    def __init__(self, app, text: str, options: list[str], title: str = ""):
        super().__init__(app)
        self.text, self.title = text, title
        self.lines = T.wrap(text, 18, 520)
        n = len(options)
        h = 90 + len(self.lines) * 24 + 40 + 44 * n
        self.rect = pygame.Rect(0, 0, 580, h)
        self.rect.center = (T.SCREEN_W // 2, T.SCREEN_H // 2)
        y0 = self.rect.y + 60 + len(self.lines) * 24 + (36 if title else 0)
        self.buttons = [Button((self.rect.x + 60, y0 + i * 44, 460, 36), o) for i, o in enumerate(options)]

    def handle(self, ev):
        for i, b in enumerate(self.buttons):
            if b.handle(ev):
                self.result = i
                self.done = True
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.result = len(self.buttons) - 1
                self.done = True
            elif pygame.K_1 <= ev.key <= pygame.K_9 and ev.key - pygame.K_1 < len(self.buttons):
                self.result = ev.key - pygame.K_1
                self.done = True

    def draw(self, surf):
        T.dim(surf, 110)
        T.panel(surf, self.rect)
        y = self.rect.y + 16
        if self.title:
            T.text(surf, self.title, (self.rect.centerx, y + 10), 22, T.GOLD, align="center", bold=True)
            y += 40
        for l in self.lines:
            T.text(surf, l, (self.rect.x + 30, y), 18)
            y += 24
        for b in self.buttons:
            b.draw(surf)


class LevelUpDialog(Scene):
    overlay = True

    def __init__(self, app, hero, offer: dict):
        super().__init__(app)
        self.hero, self.offer = hero, offer
        self.data = get_data()
        self.rect = pygame.Rect(0, 0, 620, 330)
        self.rect.center = (T.SCREEN_W // 2, T.SCREEN_H // 2)
        self.skills = offer["skills"]
        self.buttons = []
        n = max(1, len(self.skills))
        w = 240
        for i, sid in enumerate(self.skills):
            lvl = hero.skill_level(sid) + 1
            name = f"{self.data.skill_level_names[lvl - 1]}{self.data.skills[sid].name}"
            x = self.rect.centerx - (n * (w + 20) - 20) // 2 + i * (w + 20)
            self.buttons.append(Button((x, self.rect.y + 190, w, 44), name, key=sid))
        self.ok = Button((self.rect.centerx - 60, self.rect.bottom - 56, 120, 36), "确定（不学技能）")
        self.ok.rect.w = 200
        self.ok.rect.x = self.rect.centerx - 100

    def handle(self, ev):
        for b in self.buttons:
            if b.handle(ev):
                self.result = b.key
                self.done = True
        if not self.skills and (self.ok.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN)):
            self.done = True

    def draw(self, surf):
        T.dim(surf, 110)
        T.panel(surf, self.rect)
        h = self.hero
        T.text(surf, f"{h.name} 升到了 {h.level + 1} 级！", (self.rect.centerx, self.rect.y + 30), 24, T.GOLD, align="center", bold=True)
        stat = self.offer["stat"]
        T.text(surf, f"{PRIMARY_NAMES[stat]} +1（{getattr(h, stat)} → {getattr(h, stat) + 1}）",
               (self.rect.centerx, self.rect.y + 75), 20, align="center")
        if self.skills:
            T.text(surf, "选择一项副技能：", (self.rect.centerx, self.rect.y + 120), 18, T.TEXT_DIM, align="center")
            for b in self.buttons:
                b.draw(surf)
                sk = self.data.skills[b.key]
                lvl = h.skill_level(b.key) + 1
                T.text(surf, sk.describe(lvl), (b.rect.centerx, b.rect.bottom + 18), 15, T.TEXT_DIM, align="center")
        else:
            T.text(surf, "没有可学的副技能了。", (self.rect.centerx, self.rect.y + 140), 18, T.TEXT_DIM, align="center")
            self.ok.draw(surf)


class NumberDialog(Scene):
    """输入一个 0..maxn 的数量：拖滑块、点 +/-、或键盘输入。"""
    overlay = True

    def __init__(self, app, text: str, maxn: int, default: int | None = None):
        super().__init__(app)
        self.text = text
        self.maxn = max(0, maxn)
        self.value = self.maxn if default is None else max(0, min(self.maxn, default))
        self.rect = pygame.Rect(0, 0, 520, 230)
        self.rect.center = (T.SCREEN_W // 2, T.SCREEN_H // 2)
        self.slider = pygame.Rect(self.rect.x + 60, self.rect.y + 110, 400, 10)
        self.minus = Button((self.rect.x + 60, self.rect.y + 140, 60, 32), "−")
        self.plus = Button((self.rect.right - 120, self.rect.y + 140, 60, 32), "+")
        self.allb = Button((self.rect.centerx - 60, self.rect.y + 140, 120, 32), "全部")
        self.ok = Button((self.rect.centerx - 130, self.rect.bottom - 48, 120, 34), "确定")
        self.cancel = Button((self.rect.centerx + 10, self.rect.bottom - 48, 120, 34), "取消")
        self.dragging = False
        self.typed = ""

    def _set_from_mouse(self, x: int):
        t = (x - self.slider.x) / self.slider.w
        self.value = max(0, min(self.maxn, round(t * self.maxn)))

    def handle(self, ev):
        if self.minus.handle(ev):
            self.value = max(0, self.value - 1)
        elif self.plus.handle(ev):
            self.value = min(self.maxn, self.value + 1)
        elif self.allb.handle(ev):
            self.value = self.maxn
        elif self.ok.handle(ev):
            self.result, self.done = self.value, True
        elif self.cancel.handle(ev):
            self.result, self.done = 0, True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.slider.inflate(0, 20).collidepoint(ev.pos):
            self.dragging = True
            self._set_from_mouse(ev.pos[0])
        elif ev.type == pygame.MOUSEBUTTONUP:
            self.dragging = False
        elif ev.type == pygame.MOUSEMOTION and self.dragging:
            self._set_from_mouse(ev.pos[0])
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                self.result, self.done = self.value, True
            elif ev.key == pygame.K_ESCAPE:
                self.result, self.done = 0, True
            elif ev.key == pygame.K_BACKSPACE:
                self.typed = self.typed[:-1]
                self.value = min(self.maxn, int(self.typed or 0))
            elif ev.unicode.isdigit():
                self.typed = (self.typed + ev.unicode)[-6:]
                self.value = min(self.maxn, int(self.typed))
            elif ev.key == pygame.K_LEFT:
                self.value = max(0, self.value - 1)
            elif ev.key == pygame.K_RIGHT:
                self.value = min(self.maxn, self.value + 1)

    def draw(self, surf):
        T.dim(surf, 110)
        T.panel(surf, self.rect)
        T.text(surf, self.text, (self.rect.centerx, self.rect.y + 28), 18, align="center")
        T.text(surf, f"{self.value} / {self.maxn}", (self.rect.centerx, self.rect.y + 70), 26, T.GOLD, align="center", bold=True)
        pygame.draw.rect(surf, (30, 28, 36), self.slider, border_radius=5)
        if self.maxn:
            kx = self.slider.x + int(self.slider.w * self.value / self.maxn)
            pygame.draw.circle(surf, T.GOLD, (kx, self.slider.centery), 9)
        for b in (self.minus, self.plus, self.allb, self.ok, self.cancel):
            b.draw(surf)
