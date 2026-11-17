"""主菜单与新游戏设置。"""
from __future__ import annotations

import os
import random

import pygame

from ..core.data import get_data
from ..core.game import Game
from . import theme as T
from .adventure_scene import SAVE_PATH, AdventureScene
from .app import App, Scene
from .widgets import Button

MAP_SIZES = [("小 36×36", (36, 36)), ("中 44×44", (44, 44)), ("大 56×56", (56, 56))]


class MenuScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.data = get_data()
        self.faction_ids = list(self.data.factions)
        self.faction = 0
        self.opponents = 1
        self.size = 1
        cx = T.SCREEN_W // 2
        self.fbtns = [Button((cx - 330 + i * 225, 300, 210, 44), self.data.factions[f].name, 18, key=f) for i, f in enumerate(self.faction_ids)]
        self.obtns = [Button((cx - 330 + i * 225, 420, 210, 40), f"{i + 1} 个电脑对手", 16, key=str(i + 1)) for i in range(3)]
        self.sbtns = [Button((cx - 330 + i * 225, 500, 210, 40), n, 16, key=str(i)) for i, (n, _) in enumerate(MAP_SIZES)]
        self.start = Button((cx - 160, 600, 320, 50), "开始游戏", 22, color=(90, 70, 40))
        self.load = Button((cx - 160, 660, 150, 40), "读取存档", 16)
        self.quit = Button((cx + 10, 660, 150, 40), "退出", 16)

    def handle(self, ev):
        for i, b in enumerate(self.fbtns):
            if b.handle(ev):
                self.faction = i
        for i, b in enumerate(self.obtns):
            if b.handle(ev):
                self.opponents = i + 1
        for i, b in enumerate(self.sbtns):
            if b.handle(ev):
                self.size = i
        if self.start.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN):
            self.new_game()
        elif self.load.handle(ev):
            if os.path.exists(SAVE_PATH):
                g = Game.load(SAVE_PATH)
                self.app.game = g
                self.app.run_modal(AdventureScene(self.app, g))
            else:
                self.app.message("没有找到存档 saves/quick.sav。")
        elif self.quit.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
            self.app.running = False

    def new_game(self):
        rng = random.Random()
        my = self.faction_ids[self.faction]
        specs = [{"name": "玩家", "faction": my, "is_ai": False}]
        names = ["电脑甲", "电脑乙", "电脑丙"]
        for i in range(self.opponents):
            specs.append({"name": names[i], "faction": rng.choice(self.faction_ids), "is_ai": True})
        g = Game(specs, size=MAP_SIZES[self.size][1])
        self.app.game = g
        self.app.human = 0
        self.app.message(f"你是{self.data.factions[my].name}。左键点格子规划路线、再点一次出发；右键查看信息；"
                         f"E 结束回合，H 英雄界面，T 城镇，N 下一英雄，F5/F9 存读档。目标：消灭所有对手。", "六角领主")
        self.app.run_modal(AdventureScene(self.app, g))

    def draw(self, surf):
        surf.fill(T.BG)
        cx = T.SCREEN_W // 2
        T.text(surf, "六角领主", (cx, 120), 64, T.GOLD, align="center", bold=True, shadow=True)
        T.text(surf, "Hexlords — 一个致敬《英雄无敌 3》的回合制策略游戏", (cx, 185), 20, T.TEXT_DIM, align="center")
        T.text(surf, "选择种族", (cx, 270), 18, T.TEXT, align="center")
        for i, b in enumerate(self.fbtns):
            b.selected = i == self.faction
            b.draw(surf)
        f = self.data.factions[self.faction_ids[self.faction]]
        T.text(surf, f.desc, (cx, 365), 15, T.TEXT_DIM, align="center")
        for i, b in enumerate(self.obtns):
            b.selected = i + 1 == self.opponents
            b.draw(surf)
        for i, b in enumerate(self.sbtns):
            b.selected = i == self.size
            b.draw(surf)
        for b in (self.start, self.load, self.quit):
            b.draw(surf)


def main() -> None:
    app = App()
    app.push(MenuScene(app))
    app.run()
