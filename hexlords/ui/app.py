"""pygame 应用框架：场景栈 + 模态循环 + 游戏事件的统一处理。

场景（Scene）就是一个"画面"：主菜单、冒险地图、城镇、英雄、战斗、对话框。
对话框和战斗用 run_modal 同步运行：调用处等它关掉再继续，逻辑写起来像普通函数。
"""
from __future__ import annotations

import pygame

from ..ai.battle_ai import auto_resolve
from ..core.battle import ATTACKER, DEFENDER
from ..core.game import (BattleEvent, Choice, EnterTown, Event, Exchange, Game, GameOver, LevelUp, Message)
from . import theme as T


class Scene:
    overlay = False         # True：画在上一个场景之上（对话框）

    def __init__(self, app: "App"):
        self.app = app
        self.done = False
        self.result = None

    def handle(self, ev: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, surf: pygame.Surface) -> None:
        pass


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("六角领主 Hexlords")
        self.screen = pygame.display.set_mode((T.SCREEN_W, T.SCREEN_H))
        self.clock = pygame.time.Clock()
        self.stack: list[Scene] = []
        self.game: Game | None = None
        self.human = 0
        self.running = True
        self.ai_delay = 0.35        # 战斗中电脑行动的间隔（秒）

    # ---------- 场景栈 ----------
    def push(self, scene: Scene) -> None:
        self.stack.append(scene)

    def pop(self) -> None:
        if self.stack:
            self.stack.pop()

    def run_modal(self, scene: Scene):
        self.push(scene)
        while self.running and not scene.done:
            self.frame()
        if self.stack and self.stack[-1] is scene:
            self.pop()
        return scene.result

    def run(self) -> None:
        while self.running and self.stack:
            self.frame()
        pygame.quit()

    def frame(self) -> None:
        dt = self.clock.tick(60) / 1000.0
        top = self.stack[-1] if self.stack else None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return
            if top:
                top.handle(ev)
        if top:
            top.update(dt)
        # 画：从最近一个非 overlay 场景开始往上画
        start = len(self.stack) - 1
        while start > 0 and self.stack[start].overlay:
            start -= 1
        for sc in self.stack[start:]:
            sc.draw(self.screen)
        pygame.display.flip()

    # ---------- 常用对话框 ----------
    def message(self, text: str, title: str = "") -> None:
        from .dialogs import MessageDialog
        self.run_modal(MessageDialog(self, text, title))

    def choice(self, text: str, options: list[str], title: str = "") -> int:
        from .dialogs import ChoiceDialog
        r = self.run_modal(ChoiceDialog(self, text, options, title))
        return 0 if r is None else r

    def confirm(self, text: str, title: str = "") -> bool:
        return self.choice(text, ["是", "否"], title) == 0

    def number(self, text: str, maxn: int, default: int | None = None) -> int:
        from .dialogs import NumberDialog
        r = self.run_modal(NumberDialog(self, text, maxn, default))
        return 0 if r is None else r

    # ---------- 游戏事件 ----------
    def resolve_events(self, events: list[Event]) -> None:
        """把 Game 返回的事件逐个处理（人类玩家视角）。"""
        g = self.game
        assert g is not None
        for ev in events:
            if not self.running:
                return
            if isinstance(ev, Message):
                self.message(ev.text, ev.title)
            elif isinstance(ev, Choice):
                idx = self.choice(ev.text, ev.options, ev.title)
                self.resolve_events(ev.callback(idx))
            elif isinstance(ev, LevelUp):
                from .dialogs import LevelUpDialog
                skill = self.run_modal(LevelUpDialog(self, ev.hero, ev.offer))
                self.resolve_events(g.apply_levelup(ev.hero, ev.offer, skill))
            elif isinstance(ev, BattleEvent):
                self.resolve_events(self.run_battle(ev))
            elif isinstance(ev, Exchange):
                from .hero_scene import ExchangeScene
                self.run_modal(ExchangeScene(self, ev.hero, ev.other))
            elif isinstance(ev, EnterTown):
                self.open_town(ev.town)
            elif isinstance(ev, GameOver):
                self.message(ev.text, "游戏结束")
                self.game_over = True

    def human_sides(self, ev: BattleEvent) -> set[int]:
        g = self.game
        b = ev.battle
        sides = set()
        for side in (ATTACKER, DEFENDER):
            h = b.heroes[side]
            if h is not None and h.owner == self.human and not g.players[self.human].is_ai:
                sides.add(side)
        town = ev.ctx.get("town")
        if town is not None and town.owner == self.human and b.heroes[DEFENDER] is None:
            sides.add(DEFENDER)
        return sides

    def run_battle(self, ev: BattleEvent) -> list[Event]:
        g = self.game
        assert g is not None
        sides = self.human_sides(ev)
        if sides and not ev.battle.over:
            from .battle_scene import BattleScene
            self.run_modal(BattleScene(self, ev.battle, sides))
        if not ev.battle.over:
            auto_resolve(ev.battle)
        return g.finish_battle(ev)

    def open_town(self, town) -> None:
        from .town_scene import TownScene
        self.run_modal(TownScene(self, town))

    def open_hero(self, hero) -> None:
        from .hero_scene import HeroScene
        self.run_modal(HeroScene(self, hero))
