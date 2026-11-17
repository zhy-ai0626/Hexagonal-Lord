"""游戏主逻辑：回合、每日结算、英雄移动与拜访、战斗收尾、胜负判定、存档。

界面和 AI 都只通过这里的方法操作游戏。会改变状态的方法返回"事件"列表，
由调用方（界面或 AI）处理：显示消息、做选择、打一场仗、升级选技能……
"""
from __future__ import annotations

import pickle
import random
from dataclasses import dataclass, field
from typing import Callable

from .army import Army
from .battle import ATTACKER, DEFENDER, Battle
from .data import GameData, get_data
from .hero import Hero
from .mapgen import MapGenerator
from .player import Player
from .town import Town
from .world import MINE_NAME, ObjKind, World


# ---------- 事件 ----------
class Event:
    pass


@dataclass
class Message(Event):
    text: str
    title: str = ""


@dataclass
class Choice(Event):
    text: str
    options: list[str]
    callback: Callable[[int], list]      # 传入所选序号，返回后续事件
    title: str = ""


@dataclass
class BattleEvent(Event):
    battle: Battle
    ctx: dict = field(default_factory=dict)


@dataclass
class LevelUp(Event):
    hero: Hero
    offer: dict          # {"stat": 主属性, "skills": [技能 id...]}


@dataclass
class Exchange(Event):
    hero: Hero
    other: Hero


@dataclass
class EnterTown(Event):
    hero: Hero
    town: Town


@dataclass
class GameOver(Event):
    winner: int | None
    text: str = ""


class Game:
    def __init__(self, specs: list[dict], seed: int | None = None, size: tuple[int, int] = (44, 44),
                 data: GameData | None = None):
        """specs: [{"name":..., "faction":..., "is_ai":...}, ...]，第一个是本机玩家。"""
        self.data = data or get_data()
        self.seed = seed if seed is not None else random.randrange(10 ** 9)
        self.rng = random.Random(self.seed)
        self.players: list[Player] = [Player(i, s["name"], s["faction"], s["is_ai"]) for i, s in enumerate(specs)]
        gen = MapGenerator(self.data, self.rng, *size)
        towns, heroes = gen.generate(self.players)
        self.world: World = gen.world
        self.towns: dict[int, Town] = {t.id: t for t in towns}
        self.heroes: dict[int, Hero] = {h.id: h for h in heroes}
        self.day = 1
        self.cur = 0
        self.winner: int | None = None
        self.log: list[str] = []
        for p in self.players:
            for h in p.heroes:
                self.reveal(p, h.x, h.y, h.sight_radius())
            for t in p.towns:
                self.reveal(p, t.x, t.y, 6)

    # ---------- 查询 ----------
    @property
    def week(self) -> int:
        return (self.day - 1) // 7 + 1

    @property
    def day_of_week(self) -> int:
        return (self.day - 1) % 7 + 1

    @property
    def month(self) -> int:
        return (self.day - 1) // 28 + 1

    def date_text(self) -> str:
        return f"第 {self.month} 月 第 {(self.week - 1) % 4 + 1} 周 第 {self.day_of_week} 天（总第 {self.day} 天）"

    def current_player(self) -> Player:
        return self.players[self.cur]

    def hero_at(self, x: int, y: int) -> Hero | None:
        for h in self.heroes.values():
            if h.x == x and h.y == y:
                return h
        return None

    def town_at(self, x: int, y: int) -> Town | None:
        obj = self.world.object_at(x, y)
        if obj and obj.kind == ObjKind.TOWN:
            return self.towns[obj.data["town_id"]]
        return None

    def town_of_hero(self, hero: Hero) -> Town | None:
        return self.town_at(hero.x, hero.y)

    def hero_positions(self, exclude: Hero | None = None) -> set[tuple[int, int]]:
        return {(h.x, h.y) for h in self.heroes.values() if h is not exclude}

    def path_for(self, hero: Hero, goal: tuple[int, int]):
        return self.world.find_path((hero.x, hero.y), goal, blockers=self.hero_positions(hero),
                                    pathfinding=int(hero.skill_value("pathfinding")))

    def reveal(self, player: Player, x: int, y: int, r: int) -> None:
        player.explored.update(self.world.tiles_in_radius(x, y, r))

    # ---------- 移动 ----------
    def step_hero(self, hero: Hero, nxt: tuple[int, int]) -> tuple[bool, list[Event]]:
        """英雄走一格。返回 (是否真的移动了, 事件)。战斗、拜访等事件在这里产生。"""
        x, y = hero.x, hero.y
        nx, ny = nxt
        if abs(nx - x) > 1 or abs(ny - y) > 1 or not self.world.passable(nx, ny):
            return False, []
        cost = self.world.step_cost(x, y, nx, ny, int(hero.skill_value("pathfinding")))
        if hero.move_points < cost:
            return False, []
        player = self.players[hero.owner]
        other = self.hero_at(nx, ny)
        if other is not None:
            hero.move_points -= cost
            if other.owner == hero.owner:
                return False, [Exchange(hero, other)]
            return False, [self._attack_hero(hero, other)]
        obj = self.world.object_at(nx, ny)
        if obj is not None:
            if obj.kind == ObjKind.TOWN:
                town = self.towns[obj.data["town_id"]]
                if town.owner != hero.owner:
                    hero.move_points -= cost
                    return False, [self._attack_town(hero, town)]
            elif obj.guard is not None and not obj.guard.is_empty():
                hero.move_points -= cost
                return False, [self._attack_guard(hero, obj)]
            elif obj.kind == ObjKind.MONSTER:
                self.world.remove_object(obj)
        # 真正移动
        hero.move_points -= cost
        self._leave_town(hero)
        hero.x, hero.y = nx, ny
        self.reveal(player, nx, ny, hero.sight_radius())
        events: list[Event] = []
        obj = self.world.object_at(nx, ny)
        if obj is not None:
            events.extend(self.visit(hero, obj))
        return True, events

    def move_along(self, hero: Hero, path: list) -> list[Event]:
        """沿路径一直走，直到走完、移动力用尽或发生事件。给 AI 用。"""
        for (x, y, _) in path:
            moved, events = self.step_hero(hero, (x, y))
            if events:
                return events
            if not moved:
                break
        return []

    def _leave_town(self, hero: Hero) -> None:
        t = self.town_of_hero(hero)
        if t and t.visiting_hero == hero.id:
            t.visiting_hero = None

    # ---------- 拜访物件 ----------
    def visit(self, hero: Hero, obj) -> list[Event]:
        player = self.players[hero.owner]
        d = self.data
        k = obj.kind
        if k == ObjKind.TOWN:
            town = self.towns[obj.data["town_id"]]
            town.visiting_hero = hero.id
            if town.guild_level():
                self.learn_from_guild(hero, town)
            return [EnterTown(hero, town)]
        if k == ObjKind.RESOURCE:
            res, amt = obj.data["resource"], obj.data["amount"]
            player.gain({res: amt})
            self.world.remove_object(obj)
            return [Message(f"捡到 {d.resource_names[res]} {amt}。")]
        if k == ObjKind.CAMPFIRE:
            res, amt, gold = obj.data["resource"], obj.data["amount"], obj.data["gold"]
            player.gain({res: amt, "gold": gold})
            self.world.remove_object(obj)
            return [Message(f"营火旁找到 金币 {gold} 和 {d.resource_names[res]} {amt}。")]
        if k == ObjKind.CHEST:
            self.world.remove_object(obj)
            gold = self.rng.choice([1000, 1500, 2000])
            xp = gold - 500

            def choose(i: int, hero=hero, gold=gold, xp=xp):
                if i == 0:
                    self.players[hero.owner].gain({"gold": gold})
                    return []
                return self.give_xp(hero, xp)
            return [Choice(f"宝箱里有财宝。要 {gold} 金币，还是把它分给百姓换取 {xp} 点经验？",
                           [f"{gold} 金币", f"{xp} 经验"], choose, title="宝箱")]
        if k == ObjKind.ARTIFACT:
            art = d.artifacts[obj.data["artifact"]]
            hero.equip(art)
            self.world.remove_object(obj)
            return [Message(f"获得宝物「{art.name}」：{art.desc}", title="宝物")]
        if k == ObjKind.MINE:
            if obj.owner == hero.owner:
                return []
            obj.owner = hero.owner
            res = obj.data["resource"]
            return [Message(f"占领了{MINE_NAME[res]}，每天 +{obj.data['amount']} {d.resource_names[res]}。")]
        if k == ObjKind.DWELLING:
            ct = d.creatures[obj.data["creature"]]
            n_avail = obj.data["available"]
            cost_each = ct.cost.get("gold", 0)
            n = min(n_avail, player.resources["gold"] // max(1, cost_each)) if cost_each else n_avail
            if n <= 0 or not hero.army.can_add(ct):
                return [Message(f"这里是{ct.name}的巢穴，有 {n_avail} 个可招募（每个 {cost_each} 金），但你现在招不了。")]

            def choose(i: int, hero=hero, obj=obj, ct=ct, n=n, cost_each=cost_each):
                if i == 0:
                    self.players[hero.owner].pay({"gold": cost_each * n})
                    hero.army.add(ct, n)
                    obj.data["available"] -= n
                    return [Message(f"招募了 {n} 个{ct.name}。")]
                return []
            return [Choice(f"{ct.name}的巢穴：有 {n_avail} 个可招募，每个 {cost_each} 金。招募 {n} 个？",
                           [f"招募 {n} 个（{cost_each * n} 金）", "不了"], choose, title="野外兵营")]
        if k == ObjKind.SHRINE:
            sp = d.spells[obj.data["spell"]]
            if sp.id in hero.spells:
                return [Message(f"神殿里的法术「{sp.name}」你已经会了。")]
            if not hero.can_learn(sp.level):
                return [Message(f"神殿传授「{sp.name}」（{sp.level} 级），但你的智慧不够，学不会。")]
            hero.spells.add(sp.id)
            return [Message(f"学会了法术「{sp.name}」：{sp.desc}", title="法术神殿")]
        if k == ObjKind.WELL:
            hero.mana = hero.max_mana
            return [Message("泉水让你的法力完全恢复。")]
        if k == ObjKind.STABLE:
            if obj.id in hero.visited_once:
                return [Message("马厩的马今天已经换过了。")]
            hero.visited_once.add(obj.id)
            hero.move_points += 400
            return [Message("换上了好马，移动力 +400。")]
        if k == ObjKind.TREE:
            if obj.id in hero.visited_once:
                return [Message("知识之树已经把能教的都教给你了。")]
            if player.resources["gold"] < 2000:
                return [Message("知识之树愿意传授知识，但要 2000 金币作为献礼。")]

            def choose(i: int, hero=hero, obj=obj):
                if i == 0:
                    self.players[hero.owner].pay({"gold": 2000})
                    hero.visited_once.add(obj.id)
                    from .hero import xp_for_level
                    need = xp_for_level(hero.level + hero.pending_levelups + 1) - hero.xp
                    return self.give_xp(hero, max(1, need))
                return []
            return [Choice("知识之树：献上 2000 金币即可升一级。", ["献礼（2000 金）", "不了"], choose, title="知识之树")]
        return []

    def give_xp(self, hero: Hero, xp: int) -> list[Event]:
        n = hero.add_xp(xp)
        events: list[Event] = [Message(f"{hero.name} 获得 {xp} 点经验。")]
        if n:
            events.append(LevelUp(hero, hero.roll_levelup(self.rng, self.data)))
        return events

    def apply_levelup(self, hero: Hero, offer: dict, skill: str | None) -> list[Event]:
        hero.apply_levelup(offer["stat"], skill)
        if hero.pending_levelups > 0:
            return [LevelUp(hero, hero.roll_levelup(self.rng, self.data))]
        return []

    # ---------- 战斗 ----------
    def _make_battle(self, att: Hero, def_hero: Hero | None, def_army: Army, town: Town | None = None) -> Battle:
        fort = town.fort_level(self.data) if town else 0
        tavern = bool(town and "tavern" in town.buildings)
        return Battle(att, att.army, def_hero, def_army, self.rng, fort_level=fort, def_tavern=tavern, data=self.data)

    def _attack_guard(self, hero: Hero, obj) -> BattleEvent:
        return BattleEvent(self._make_battle(hero, None, obj.guard), {"kind": "guard", "obj": obj})

    def _attack_hero(self, hero: Hero, other: Hero) -> BattleEvent:
        town = self.town_of_hero(other)
        return BattleEvent(self._make_battle(hero, other, other.army, town), {"kind": "hero", "other": other, "town": town})

    def _attack_town(self, hero: Hero, town: Town) -> BattleEvent:
        if town.visiting_hero and town.visiting_hero in self.heroes:
            other = self.heroes[town.visiting_hero]
            return BattleEvent(self._make_battle(hero, other, other.army, town),
                               {"kind": "town_hero", "other": other, "town": town})
        if town.garrison.is_empty():
            # 无人防守：直接占领
            b = Battle(hero, hero.army, None, Army(), self.rng, data=self.data)
            return BattleEvent(b, {"kind": "town", "town": town})
        return BattleEvent(self._make_battle(hero, None, town.garrison, town), {"kind": "town", "town": town})

    def finish_battle(self, ev: BattleEvent) -> list[Event]:
        b, ctx = ev.battle, ev.ctx
        res = b.result
        assert res is not None
        att = b.heroes[ATTACKER]
        defn = b.heroes[DEFENDER]
        events: list[Event] = []
        kind = ctx["kind"]
        att_won = res.winner == ATTACKER
        cas = lambda side: "，".join(f"{k}×{v}" for k, v in res.casualties[side].items()) or "无"
        if att_won:
            events.append(Message(f"{att.name} 胜利！己方损失：{cas(0)}；敌方损失：{cas(1)}。", title="战斗胜利"))
            events.extend(self.give_xp(att, res.xp[0]))
            if kind == "guard":
                obj = ctx["obj"]
                obj.guard = None
                if obj.kind == ObjKind.MONSTER:
                    self.world.remove_object(obj)
                else:
                    events.extend(self.visit(att, obj))
            elif kind in ("hero", "town_hero"):
                other = ctx["other"]
                for a in other.all_artifacts():
                    att.equip(a)
                self._remove_hero(other)
                town = ctx.get("town")
                if town is not None and town.owner != att.owner:
                    if town.garrison.is_empty():
                        self._capture_town(att, town)
                        events.append(Message(f"占领了 {town.name}！", title="占领城镇"))
                    else:
                        events.append(Message("守将已败，但城中仍有驻军。"))
                        events.append(BattleEvent(self._make_battle(att, None, town.garrison, town), {"kind": "town", "town": town}))
            elif kind == "town":
                town = ctx["town"]
                self._capture_town(att, town)
                events.append(Message(f"占领了 {town.name}！", title="占领城镇"))
        else:
            events.append(Message(f"{att.name} 战败。敌方损失：{cas(1)}。", title="战斗失败"))
            if defn is not None:
                events.extend(self.give_xp(defn, res.xp[1]))
                for a in att.all_artifacts():
                    defn.equip(a)
            self._remove_hero(att)
        events.extend(self._check_elimination())
        return events

    def _capture_town(self, hero: Hero, town: Town) -> None:
        if town.owner is not None:
            old = self.players[town.owner]
            if town in old.towns:
                old.towns.remove(town)
        town.owner = hero.owner
        self.players[hero.owner].towns.append(town)
        town.garrison.clear()
        obj = self.world.object_at(town.x, town.y)
        if obj:
            obj.owner = hero.owner
        self._leave_town(hero)
        hero.x, hero.y = town.x, town.y
        town.visiting_hero = hero.id
        self.reveal(self.players[hero.owner], town.x, town.y, 6)
        if town.guild_level():
            self.learn_from_guild(hero, town)

    def _remove_hero(self, hero: Hero) -> None:
        self.heroes.pop(hero.id, None)
        p = self.players[hero.owner]
        if hero in p.heroes:
            p.heroes.remove(hero)
        self._leave_town(hero)
        if hero.def_id not in p.hero_pool:
            p.hero_pool.append(hero.def_id)

    def _check_elimination(self) -> list[Event]:
        events: list[Event] = []
        for p in self.players:
            if p.alive and not p.towns and not p.heroes:
                p.alive = False
                for obj in self.world.objects.values():
                    if obj.owner == p.idx:
                        obj.owner = None
                events.append(Message(f"{p.name} 被消灭了。"))
        alive = [p for p in self.players if p.alive]
        if len(alive) == 1 and self.winner is None:
            self.winner = alive[0].idx
            events.append(GameOver(self.winner, f"{alive[0].name} 统一了六角大陆！"))
        elif not alive and self.winner is None:
            self.winner = -1
            events.append(GameOver(None, "所有人都灭亡了。"))
        return events

    # ---------- 城镇操作 ----------
    def build(self, player: Player, town: Town, bid: str) -> tuple[bool, str]:
        ok, why = town.can_build(bid, player.resources, self.data, player.has_capitol())
        if not ok:
            return False, why
        player.pay(self.data.building_cost(bid, town.faction))
        town.build(bid, self.rng, self.data)
        if town.visiting_hero in self.heroes and town.guild_level():
            self.learn_from_guild(self.heroes[town.visiting_hero], town)
        return True, ""

    def recruit(self, player: Player, town: Town, tier: int, n: int, army: Army) -> tuple[bool, str]:
        n = min(n, town.max_recruit(tier, player.resources, self.data))
        if n <= 0:
            return False, "招不了"
        cost = town.recruit_cost(tier, n, self.data)
        if not town.recruit(tier, n, army, self.data):
            return False, "军队槽位已满"
        player.pay(cost)
        return True, ""

    def hire_hero(self, player: Player, town: Town, def_id: str) -> tuple[bool, str]:
        if "tavern" not in town.buildings:
            return False, "没有酒馆"
        if len(player.heroes) >= 8:
            return False, "英雄太多了"
        if player.resources["gold"] < 2500:
            return False, "金币不足（需要 2500）"
        if town.visiting_hero is not None:
            return False, "城里已经有英雄"
        if def_id not in player.hero_pool:
            return False, "无此英雄"
        player.pay({"gold": 2500})
        player.hero_pool.remove(def_id)
        hero = Hero(self.data.hero_defs[def_id], player.idx, town.x, town.y, self.data)
        hero.army.add(self.data.faction_creature(hero.faction, 1), 5)
        hero.new_day()
        self.heroes[hero.id] = hero
        player.heroes.append(hero)
        town.visiting_hero = hero.id
        if town.guild_level():
            self.learn_from_guild(hero, town)
        self.reveal(player, hero.x, hero.y, hero.sight_radius())
        return True, ""

    def tavern_offers(self, player: Player) -> list[str]:
        return player.hero_pool[:2]

    def learn_from_guild(self, hero: Hero, town: Town) -> list[str]:
        learned = []
        for lvl, ids in town.guild_spells.items():
            if hero.can_learn(lvl):
                for sid in ids:
                    if sid not in hero.spells:
                        hero.spells.add(sid)
                        learned.append(sid)
        return learned

    def trade(self, player: Player, give: str, get: str, qty: int = 1) -> tuple[bool, str]:
        """市场交易：qty 是想得到的 get 数量。"""
        if player.market_count() == 0:
            return False, "没有市场"
        if give == get:
            return False, "同种资源"
        if get == "gold":
            rate = player.gold_per_resource(give)
            need = qty
            if player.resources.get(give, 0) < need:
                return False, "资源不足"
            player.pay({give: need})
            player.gain({"gold": rate * qty})
            return True, ""
        rate = player.trade_rate(give, get)
        need = rate * qty
        if player.resources.get(give, 0) < need:
            return False, "资源不足"
        player.pay({give: need})
        player.gain({get: qty})
        return True, ""

    # ---------- 回合 ----------
    def end_turn(self) -> list[Event]:
        """当前玩家结束回合。返回给"下一个玩家"看的事件（新的一天提示等）。"""
        events: list[Event] = []
        n = len(self.players)
        for _ in range(n):
            self.cur = (self.cur + 1) % n
            if self.cur == 0:
                events.extend(self._new_day())
            if self.players[self.cur].alive:
                break
        return events

    def _new_day(self) -> list[Event]:
        self.day += 1
        events: list[Event] = []
        new_week = self.day_of_week == 1
        for p in self.players:
            if not p.alive:
                continue
            # 收入
            income = {"gold": 0}
            for t in p.towns:
                income["gold"] += t.income(self.data)
                t.new_day()
                if new_week:
                    t.new_week(self.data)
            for obj in self.world.objects.values():
                if obj.kind == ObjKind.MINE and obj.owner == p.idx:
                    r = obj.data["resource"]
                    income[r] = income.get(r, 0) + obj.data["amount"]
            for h in p.heroes:
                income["gold"] += h.daily_gold()
            p.gain(income)
            for h in p.heroes:
                t = self.town_of_hero(h)
                h.new_day(in_town_with_guild=bool(t and t.guild_level()))
            if not p.towns:
                p.days_without_town += 1
                if p.days_without_town >= 7:
                    for h in list(p.heroes):
                        self._remove_hero(h)
            else:
                p.days_without_town = 0
        if new_week:
            for obj in self.world.objects.values():
                if obj.kind == ObjKind.DWELLING:
                    ct = self.data.creatures[obj.data["creature"]]
                    obj.data["available"] += ct.growth
                elif obj.kind == ObjKind.MONSTER and obj.guard is not None and self.week % 2 == 0:
                    for s in obj.guard.stacks():
                        s.count += max(1, s.count // 10)
            events.append(Message(f"新的一周开始了（{self.date_text()}）。各城镇兵源已补充。", title="新的一周"))
        events.extend(self._check_elimination())
        return events

    # ---------- 存档 ----------
    def save(self, path: str) -> None:
        state = self.__dict__.copy()
        state.pop("data", None)
        with open(path, "wb") as f:
            pickle.dump(state, f)

    @classmethod
    def load(cls, path: str) -> "Game":
        with open(path, "rb") as f:
            state = pickle.load(f)
        g = cls.__new__(cls)
        g.__dict__.update(state)
        g.data = get_data()
        Hero._next_id = max(g.heroes, default=0) + 1
        Town._next_id = max(g.towns, default=0) + 1
        return g
