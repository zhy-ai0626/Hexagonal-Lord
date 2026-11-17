"""无界面测试：规则层 + AI 自动跑若干天。运行：python -m pytest tests/ 或 python tests/test_core.py"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hexlords.ai.adventure_ai import AdventureAI
from hexlords.ai.battle_ai import auto_resolve
from hexlords.core.army import Army
from hexlords.core.battle import ATTACKER, Battle
from hexlords.core.data import get_data
from hexlords.core.game import BattleEvent, Game, GameOver
from hexlords.core.hero import Hero, xp_for_level
from hexlords.core.world import ObjKind


def test_data_loads():
    d = get_data()
    assert len(d.factions) == 3
    for f in d.factions.values():
        assert [c.tier for c in f.creatures] == list(range(1, 8))
        assert len(f.dwelling_names) == 7
    assert len(d.spells) == 16
    assert len(d.skills) == 12
    assert "dwell7" in d.buildings
    # 价值应随等级递增
    for f in d.factions.values():
        vals = [c.value for c in f.creatures]
        assert vals == sorted(vals), (f.id, vals)


def test_xp_table():
    assert xp_for_level(1) == 0 and xp_for_level(2) == 1000 and xp_for_level(3) == 2200


def test_battle_basic():
    d = get_data()
    rng = random.Random(1)
    a, b = Army(), Army()
    a.add(d.creatures["militia"], 30)
    a.add(d.creatures["hunter"], 10)
    b.add(d.creatures["wolf"], 20)
    hero = Hero(d.hero_defs["aldric"], 0, 0, 0, d)
    bt = Battle(hero, a, None, b, rng, data=d)
    auto_resolve(bt)
    assert bt.over and bt.result is not None
    assert bt.winner == ATTACKER
    assert a.total_count() > 0 and b.is_empty()
    assert bt.result.xp[0] > 0


def test_spells():
    d = get_data()
    rng = random.Random(2)
    a, b = Army(), Army()
    a.add(d.creatures["militia"], 10)
    b.add(d.creatures["bandit"], 10)
    hero = Hero(d.hero_defs["lioren"], 0, 0, 0, d)
    hero.spells |= {"arcane_bolt", "haste", "fireball", "blind"}
    hero.power = 5
    hero.mana = 100
    bt = Battle(hero, a, None, b, rng, data=d, obstacles=0)
    target = bt.alive_stacks(1)[0]
    before = target.total_hp
    bt.cast(0, d.spells["arcane_bolt"], target.pos)
    assert target.total_hp == before - 60
    assert bt.spell_cast[0]
    bt._new_round()
    bt.cast(0, d.spells["haste"], bt.alive_stacks(0)[0].pos)
    assert bt.alive_stacks(0)[0].speed() == 7
    bt._new_round()
    bt.cast(0, d.spells["blind"], target.pos)
    assert target.blind


def run_game(seed: int, days: int = 30, verbose: bool = False) -> Game:
    specs = [{"name": "红", "faction": "dawnhold", "is_ai": True},
             {"name": "蓝", "faction": "ashreach", "is_ai": True},
             {"name": "绿", "faction": "mossveil", "is_ai": True}]
    g = Game(specs, seed=seed, size=(44, 44))

    def on_battle(ev: BattleEvent):
        auto_resolve(ev.battle)
        return g.finish_battle(ev)

    for _ in range(days * len(specs)):
        if g.winner is not None:
            break
        p = g.current_player()
        ai = AdventureAI(g, p, on_battle)
        ai.play_turn()
        evs = g.end_turn()
        if any(isinstance(e, GameOver) for e in evs):
            break
    if verbose:
        for p in g.players:
            print(p.name, "alive" if p.alive else "dead", "gold", p.resources["gold"],
                  "towns", len(p.towns), "heroes", [(h.name, h.level, h.army.describe()) for h in p.heroes])
        mines = sum(1 for o in g.world.objects.values() if o.kind == ObjKind.MINE and o.owner is not None)
        print("day", g.day, "owned mines", mines, "objects left", len(g.world.objects))
    return g


def test_ai_game_runs():
    g = run_game(seed=7, days=20)
    assert g.day >= 15
    # AI 应该有所作为：至少占了矿或升了级
    mines = sum(1 for o in g.world.objects.values() if o.kind == ObjKind.MINE and o.owner is not None)
    levels = [h.level for p in g.players for h in p.heroes]
    assert mines > 0 or (levels and max(levels) > 1)


def test_save_load(tmp_path):
    g = run_game(seed=3, days=3)
    path = tmp_path / "s.sav"
    g.save(str(path))
    g2 = Game.load(str(path))
    assert g2.day == g.day and len(g2.heroes) == len(g.heroes)


if __name__ == "__main__":
    test_data_loads()
    test_xp_table()
    test_battle_basic()
    test_spells()
    for seed in (1, 2, 3):
        print("=== seed", seed)
        run_game(seed, days=30, verbose=True)
    print("all ok")
