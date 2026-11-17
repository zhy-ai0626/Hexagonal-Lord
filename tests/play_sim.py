"""模拟玩家点击：规划路径、走路、拜访物件、结束回合、电脑回合，连续跑若干天。
对话框全部自动应答（消息=关闭，选择=第一项，确认=是，数量=最大），战斗自动打。
运行：SDL_VIDEODRIVER=dummy python tests/play_sim.py"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from hexlords.ai.battle_ai import auto_resolve  # noqa: E402
from hexlords.core.game import Game  # noqa: E402
from hexlords.ui.adventure_scene import TILE, AdventureScene  # noqa: E402
from hexlords.ui.app import App  # noqa: E402
from hexlords.ui.battle_scene import BattleScene  # noqa: E402
from hexlords.ui.dialogs import LevelUpDialog  # noqa: E402
from hexlords.ui.town_scene import TownScene  # noqa: E402


class SimApp(App):
    """把所有模态对话框换成自动应答。"""
    def message(self, text, title=""):
        print("  [消息]", title, text[:60].replace("\n", " "))

    def choice(self, text, options, title=""):
        print("  [选择]", text[:50].replace("\n", " "), "->", options[0])
        return 0

    def confirm(self, text, title=""):
        return True

    def number(self, text, maxn, default=None):
        return maxn

    def run_modal(self, scene):
        if isinstance(scene, BattleScene):
            b = scene.b
            desc = lambda a: a.describe()
            before = (desc(b.armies[0]), desc(b.armies[1]))
            auto_resolve(b)
            print(f"  [战斗] {before[0]} vs {before[1]} -> {'进攻方胜' if b.winner == 0 else '防守方胜'}，{b.round} 回合")
            scene.draw(self.screen)
            return None
        if isinstance(scene, LevelUpDialog):
            return scene.skills[0] if scene.skills else None
        if isinstance(scene, TownScene):
            scene.draw(self.screen)
            return None
        scene.draw(self.screen)
        return None


def click(scene, pos, button=1):
    scene.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))


def main(days: int = 8) -> None:
    app = SimApp()
    specs = [{"name": "玩家", "faction": "mossveil", "is_ai": False},
             {"name": "电脑甲", "faction": "dawnhold", "is_ai": True},
             {"name": "电脑乙", "faction": "ashreach", "is_ai": True}]
    g = Game(specs, seed=11, size=(44, 44))
    app.game = g
    adv = AdventureScene(app, g)
    app.push(adv)
    me = g.players[0]
    for day in range(days):
        print(f"== 第 {g.day} 天 金 {me.resources['gold']} 英雄 {[(h.name, h.level, h.army.total_count()) for h in me.heroes]}")
        for hero in list(me.heroes):
            adv.sel, adv.path = hero, None
            adv.center_on_selected()
            tries = 0
            while hero in me.heroes and hero.move_points > 0 and tries < 6:
                tries += 1
                # 选一个已探索且有物件的目标
                cands = [o for o in g.world.objects.values() if o.pos in me.explored and o.pos != (hero.x, hero.y)
                         and not (o.guard and o.guard.total_value() > hero.strength() * 0.7)]
                if not cands:
                    break
                cands.sort(key=lambda o: abs(o.x - hero.x) + abs(o.y - hero.y))
                goal = cands[0].pos
                sx, sy = adv.screen_pos(*goal)
                pos = (sx + TILE // 2, sy + TILE // 2)
                if not (0 <= pos[0] < 960 and 0 <= pos[1] < 800):
                    adv.center_on(*goal)
                    sx, sy = adv.screen_pos(*goal)
                    pos = (sx + TILE // 2, sy + TILE // 2)
                click(adv, pos)            # 规划
                if adv.path is None:
                    g.world.remove_object(cands[0]) if cands[0].kind == "monster" else None
                    break
                click(adv, pos)            # 出发
                steps = 0
                while adv.moving and steps < 200:
                    adv.update(0.1)
                    steps += 1
                print(f"   {hero.name} -> {goal} 剩余移动 {hero.move_points}")
        # 进城建造
        for t in me.towns:
            for bid in ("dwell1", "town_hall", "dwell2", "fort", "market", "dwell3", "mage_guild_1"):
                ok, _ = g.build(me, t, bid)
                if ok:
                    print("   建造", bid, "于", t.name)
                    break
        adv.end_turn()
        adv.draw(app.screen)
        if adv.done:
            print("游戏结束 / 玩家出局")
            break
    pygame.image.save(app.screen, str(ROOT / "tests" / "shots" / "13_play_sim.png"))
    print("play sim ok; day", g.day)


if __name__ == "__main__":
    main()
