"""无窗口渲染每个画面并存成 PNG，用来检查界面有没有报错 / 排版问题。
运行：SDL_VIDEODRIVER=dummy python tests/ui_smoke.py  （截图在 tests/shots/）"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from hexlords.core.data import get_data  # noqa: E402
from hexlords.core.game import Game, BattleEvent  # noqa: E402
from hexlords.ui.adventure_scene import AdventureScene  # noqa: E402
from hexlords.ui.app import App  # noqa: E402
from hexlords.ui.battle_scene import BattleScene  # noqa: E402
from hexlords.ui.dialogs import LevelUpDialog, NumberDialog  # noqa: E402
from hexlords.ui.hero_scene import ExchangeScene, HeroScene  # noqa: E402
from hexlords.ui.main import MenuScene  # noqa: E402
from hexlords.ui.town_scene import TownScene  # noqa: E402

OUT = ROOT / "tests" / "shots"
OUT.mkdir(exist_ok=True)


def shot(app: App, name: str) -> None:
    start = len(app.stack) - 1
    while start > 0 and app.stack[start].overlay:
        start -= 1
    for sc in app.stack[start:]:
        sc.draw(app.screen)
    pygame.image.save(app.screen, str(OUT / f"{name}.png"))
    print("saved", name)


def main() -> None:
    app = App()
    d = get_data()
    app.push(MenuScene(app))
    shot(app, "01_menu")
    specs = [{"name": "玩家", "faction": "dawnhold", "is_ai": False},
             {"name": "电脑甲", "faction": "ashreach", "is_ai": True}]
    g = Game(specs, seed=42, size=(44, 44))
    app.game = g
    adv = AdventureScene(app, g)
    app.push(adv)
    shot(app, "02_adventure")
    # 规划一条路径
    hero = g.players[0].heroes[0]
    goal = None
    for obj in g.world.objects.values():
        if obj.pos in g.players[0].explored and obj.kind == "resource":
            goal = obj.pos
            break
    if goal:
        adv.sel = hero
        adv.path = g.path_for(hero, goal)
        adv.path_goal = goal
        shot(app, "03_adventure_path")
    town = g.players[0].towns[0]
    town.visiting_hero = hero.id
    hero.x, hero.y = town.x, town.y
    app.push(TownScene(app, town))
    shot(app, "04_town")
    app.pop()
    hero.spells |= {"arcane_bolt", "haste"}
    hero.equip(d.artifacts["iron_sabre"])
    hero.backpack.append(d.artifacts["lucky_coin"])
    app.push(HeroScene(app, hero))
    shot(app, "05_hero")
    app.pop()
    app.push(LevelUpDialog(app, hero, hero.roll_levelup(random.Random(1))))
    shot(app, "06_levelup")
    app.pop()
    app.push(NumberDialog(app, "招募民兵（每个 金币 60）", 14))
    shot(app, "07_number")
    app.pop()
    # 战斗画面：找一个有守卫的物件打
    from hexlords.core.army import Army
    enemy = Army()
    enemy.add(d.creatures["wolf"], 12)
    enemy.add(d.creatures["bandit"], 6)
    from hexlords.core.battle import Battle
    b = Battle(hero, hero.army, None, enemy, random.Random(5), data=d)
    bs = BattleScene(app, b, {0})
    app.push(bs)
    bs.hover = b.alive_stacks(1)[0].pos
    shot(app, "08_battle")
    bs._open_book(0)
    shot(app, "09_battle_spellbook")
    bs.spell_mode = None
    # 让 AI 打几步
    from hexlords.ai.battle_ai import auto_resolve
    auto_resolve(b)
    shot(app, "10_battle_result")
    app.pop()
    # 军队交换
    town.visiting_hero = None; hero.x, hero.y = town.x + 1, town.y + 1
    ok, why = g.hire_hero(g.players[0], town, g.players[0].hero_pool[0])
    assert ok, why
    other = g.players[0].heroes[1]
    app.push(ExchangeScene(app, hero, other))
    shot(app, "11_exchange")
    app.pop()
    # AI 回合 + 一天后的地图
    adv.end_turn = lambda: None
    evs = g.end_turn()
    from hexlords.ai.adventure_ai import AdventureAI
    AdventureAI(g, g.players[1], app.run_battle).play_turn()
    g.end_turn()
    shot(app, "12_adventure_day2")
    print("ui smoke ok")


if __name__ == "__main__":
    main()
