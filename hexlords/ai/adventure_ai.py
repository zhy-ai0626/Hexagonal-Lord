"""冒险地图 AI（电脑玩家）。

每回合：
1. 城镇：按优先级建一座建筑，用多余的钱招兵。
2. 钱够且英雄少就雇英雄。
3. 每个英雄：给地图上的所有目标打分 = 价值 / (1 + 距离/日移动力)，
   先用"我的战力 > 守军价值 × 安全系数"过滤掉打不过的，然后去最高分的目标；
   没有目标就去探索未知区域。
"""
from __future__ import annotations

from typing import Callable

from ..core.data import get_data
from ..core.game import BattleEvent, Choice, EnterTown, Event, Exchange, Game, LevelUp
from ..core.hero import Hero
from ..core.player import Player
from ..core.town import Town
from ..core.world import ObjKind

BUILD_PRIORITY = [
    "dwell1", "town_hall", "dwell2", "fort", "market", "dwell3", "mage_guild_1", "citadel", "dwell4",
    "city_hall", "dwell5", "SPECIAL", "castle", "dwell6", "mage_guild_2", "tavern", "capitol", "dwell7",
    "mage_guild_3", "mage_guild_4",
]
SAFETY = 1.4            # 需要 战力 > 守军价值 × SAFETY 才会去打（野怪、守卫）
PLAYER_SAFETY = 2.0     # 打其他玩家的英雄/城镇时要求更高的优势
AGGRESSION_DAY = 10     # 第 10 天前电脑不主动进攻其他玩家，让开局有发展空间
GOLD_RESERVE = 1500


class AdventureAI:
    def __init__(self, game: Game, player: Player, on_battle: Callable[[BattleEvent], list[Event]]):
        """on_battle：把战斗交给调用方（自动结算或让人类玩家打），返回战斗后的事件。"""
        self.game = game
        self.player = player
        self.on_battle = on_battle
        self.data = get_data()

    # ---------- 回合 ----------
    def play_turn(self) -> None:
        g, p = self.game, self.player
        if not p.alive:
            return
        self.manage_towns()
        self.hire_heroes()
        for hero in list(p.heroes):
            if hero not in p.heroes:
                continue
            self.move_hero(hero)
        self.manage_towns()

    # ---------- 事件处理 ----------
    def handle(self, events: list[Event]) -> None:
        g = self.game
        for ev in events:
            if isinstance(ev, Choice):
                idx = self._choose(ev)
                self.handle(ev.callback(idx))
            elif isinstance(ev, LevelUp):
                skill = self._pick_skill(ev.hero, ev.offer["skills"])
                self.handle(g.apply_levelup(ev.hero, ev.offer, skill))
            elif isinstance(ev, BattleEvent):
                self.handle(self.on_battle(ev))
            elif isinstance(ev, EnterTown):
                self._enter_town(ev.hero, ev.town)
            elif isinstance(ev, Exchange):
                self._exchange(ev.hero, ev.other)

    def _choose(self, ev: Choice) -> int:
        if ev.title == "宝箱":
            return 1 if (self.player.resources["gold"] > 6000 or ev.options[0].startswith("1000")) else 0
        return 0

    def _pick_skill(self, hero: Hero, options: list[str]) -> str | None:
        if not options:
            return None
        w = hero.cls.skill_weights
        return max(options, key=lambda s: w.get(s, 1) + (hero.skill_level(s) * 2))

    def _enter_town(self, hero: Hero, town: Town) -> None:
        town.garrison.merge_into(hero.army)
        self._recruit_into(town, hero.army)

    def _exchange(self, hero: Hero, other: Hero) -> None:
        """弱的把兵全给强的。"""
        a, b = (hero, other) if hero.strength() >= other.strength() else (other, hero)
        b.army.merge_into(a.army)

    # ---------- 城镇 ----------
    def manage_towns(self) -> None:
        g, p = self.game, self.player
        for town in list(p.towns):
            built = False
            for bid in BUILD_PRIORITY:
                if bid == "SPECIAL":
                    bid = self.data.factions[town.faction].special_building["id"]
                ok, _ = g.build(p, town, bid)
                if ok:
                    built = True
                    break
            if not built and not town.built_today:
                self._buy_missing(town)
            hero = g.heroes.get(town.visiting_hero) if town.visiting_hero else None
            self._recruit_into(town, hero.army if hero else town.garrison)

    def _buy_missing(self, town: Town) -> None:
        """钱多但缺木/矿/稀有资源时，去市场买齐第一座"只差资源"的建筑所需，然后建造。"""
        g, p = self.game, self.player
        if p.market_count() == 0 or p.resources["gold"] < 6000:
            return
        for bid in BUILD_PRIORITY:
            if bid == "SPECIAL":
                bid = self.data.factions[town.faction].special_building["id"]
            b = self.data.buildings[bid]
            if town.has(bid, self.data) or any(not town.has(r, self.data) for r in b.requires):
                continue
            cost = self.data.building_cost(bid, town.faction)
            missing = {r: n - p.resources.get(r, 0) for r, n in cost.items() if r != "gold" and p.resources.get(r, 0) < n}
            if not missing:
                return
            spend = sum(p.trade_rate("gold", r) * n for r, n in missing.items())
            if p.resources["gold"] - spend < cost.get("gold", 0) + GOLD_RESERVE:
                return
            for r, n in missing.items():
                g.trade(p, "gold", r, n)
            g.build(p, town, bid)
            return

    def _recruit_into(self, town: Town, army) -> None:
        g, p = self.game, self.player
        for tier in range(7, 0, -1):
            if not town.dwelling_built(tier):
                continue
            # 留一点钱给建筑
            budget = dict(p.resources)
            budget["gold"] = max(0, budget["gold"] - GOLD_RESERVE)
            n = town.max_recruit(tier, budget, self.data)
            if n > 0:
                g.recruit(p, town, tier, n, army)

    def hire_heroes(self) -> None:
        g, p = self.game, self.player
        need_gold = 2500 if not p.heroes else 5000
        if len(p.heroes) >= 3 or p.resources["gold"] < need_gold:
            return
        for town in p.towns:
            if "tavern" in town.buildings and town.visiting_hero is None and p.hero_pool:
                ok, _ = g.hire_hero(p, town, p.hero_pool[0])
                if ok:
                    hero = g.heroes[town.visiting_hero]
                    town.garrison.merge_into(hero.army)
                    return

    # ---------- 英雄 ----------
    def move_hero(self, hero: Hero) -> None:
        g = self.game
        for _ in range(12):
            if hero not in self.player.heroes or hero.move_points <= 0:
                return
            target = self._best_target(hero)
            if target is None:
                target = self._explore_target(hero)
            if target is None:
                return
            path = g.path_for(hero, target)
            if not path:
                return
            before = (hero.x, hero.y, hero.move_points)
            events = g.move_along(hero, path)
            self.handle(events)
            if hero not in self.player.heroes:
                return
            if (hero.x, hero.y, hero.move_points) == before and not events:
                return

    def _strength(self, hero: Hero) -> float:
        return hero.strength()

    def _beatable(self, hero: Hero, enemy_value: float) -> bool:
        return self._strength(hero) > enemy_value * SAFETY

    def _can_attack_player(self, hero: Hero, enemy_value: float) -> bool:
        return self.game.day >= AGGRESSION_DAY and self._strength(hero) > enemy_value * PLAYER_SAFETY

    def _best_target(self, hero: Hero) -> tuple[int, int] | None:
        g, p, w = self.game, self.player, self.game.world
        own_pos = {(h.x, h.y) for h in p.heroes if h is not hero}
        dists = w.reachable_costs((hero.x, hero.y), hero.max_move * 5,
                                  int(hero.skill_value("pathfinding")), blockers=own_pos)
        best, best_score = None, 0.0
        for obj in w.objects.values():
            d = dists.get(obj.pos)
            if d is None or obj.pos == (hero.x, hero.y):
                continue
            v = self._object_value(hero, obj)
            if v <= 0:
                continue
            # 物件上站着敌方英雄：走上去等于开战，必须按"打玩家"的标准判断
            occupant = g.hero_at(*obj.pos)
            if occupant is not None and occupant.owner != p.idx and not self._can_attack_player(hero, occupant.strength()):
                continue
            score = v / (1 + d / max(1, hero.max_move))
            if score > best_score:
                best, best_score = obj.pos, score
        for other in g.heroes.values():
            if other.owner == p.idx:
                continue
            d = dists.get((other.x, other.y))
            if d is None:
                continue
            if g.players[other.owner].alive and self._can_attack_player(hero, other.strength()):
                v = 1500 + other.army.total_value() * 0.3
                score = v / (1 + d / max(1, hero.max_move))
                if score > best_score:
                    best, best_score = (other.x, other.y), score
        return best

    def _object_value(self, hero: Hero, obj) -> float:
        g, p = self.game, self.player
        k = obj.kind
        guard_v = obj.guard.total_value() if obj.guard is not None and not obj.guard.is_empty() else 0.0
        if guard_v and not self._beatable(hero, guard_v):
            return 0.0
        if k == ObjKind.RESOURCE:
            res, amt = obj.data["resource"], obj.data["amount"]
            return amt / 2 if res == "gold" else amt * (180 if res in ("crystal", "stardust", "mithril") else 120)
        if k == ObjKind.CAMPFIRE:
            return 700
        if k == ObjKind.CHEST:
            return 800
        if k == ObjKind.ARTIFACT:
            return 500 * self.data.artifacts[obj.data["artifact"]].grade
        if k == ObjKind.MINE:
            if obj.owner == p.idx:
                return 0
            res = obj.data["resource"]
            base = {"gold": 2500, "wood": 1200, "ore": 1200}.get(res, 1800)
            return base + (500 if obj.owner is not None else 0)
        if k == ObjKind.DWELLING:
            ct = self.data.creatures[obj.data["creature"]]
            if obj.data["available"] > 0 and p.resources["gold"] >= ct.cost.get("gold", 0) * 3 and hero.army.can_add(ct):
                return 400
            return 0
        if k == ObjKind.SHRINE:
            sp = self.data.spells[obj.data["spell"]]
            return 300 if sp.id not in hero.spells and hero.can_learn(sp.level) else 0
        if k == ObjKind.WELL:
            return 300 if hero.mana < hero.max_mana / 2 and hero.spells else 0
        if k == ObjKind.STABLE:
            return 150 if obj.id not in hero.visited_once else 0
        if k == ObjKind.TREE:
            return 900 if obj.id not in hero.visited_once and p.resources["gold"] >= 4000 else 0
        if k == ObjKind.MONSTER:
            return guard_v * 0.6
        if k == ObjKind.TOWN:
            town = g.towns[obj.data["town_id"]]
            if town.owner == p.idx:
                # 回城补兵：城里有兵可招（钱够）或守军可带走
                avail = sum(town.available.get(t, 0) for t in range(1, 8) if town.dwelling_built(t))
                if town.garrison.total_value() > 0 or (avail > 0 and p.resources["gold"] > 2000):
                    return 500 + town.garrison.total_value() * 0.5
                return 0
            defender = town.garrison.total_value()
            if town.visiting_hero and town.visiting_hero in g.heroes:
                defender += g.heroes[town.visiting_hero].strength()
            defender *= 1 + 0.15 * town.fort_level(self.data)
            if town.owner is None:
                if not self._beatable(hero, defender):
                    return 0
            elif not self._can_attack_player(hero, defender):
                return 0
            return 4000 + (2000 if town.owner is not None else 0)
        return 0

    def _explore_target(self, hero: Hero) -> tuple[int, int] | None:
        g, p, w = self.game, self.player, self.game.world
        own_pos = {(h.x, h.y) for h in p.heroes if h is not hero}
        all_heroes = g.hero_positions(hero)
        dists = w.reachable_costs((hero.x, hero.y), hero.move_points, int(hero.skill_value("pathfinding")), blockers=all_heroes)
        best, best_score = None, 0.0
        for pos, d in dists.items():
            if d == 0 or pos in w.obj_at or pos in all_heroes:
                continue
            unexplored = sum(1 for t in w.tiles_in_radius(pos[0], pos[1], hero.sight_radius()) if t not in p.explored)
            score = unexplored + d / 1000
            if score > best_score:
                best, best_score = pos, score
        return best
