"""城镇：建筑树、兵种产量与招募、法师塔、驻军。"""
from __future__ import annotations

import random

from .army import Army
from .data import GameData, get_data

TOWN_NAMES = {
    "dawnhold": ["晨曦堡", "白鹭城", "金穗镇", "圣钟城", "霞光港"],
    "mossveil": ["苔泽", "古橡谷", "鹿鸣林", "藤影镇", "青萝坞"],
    "ashreach": ["余烬城", "黑岩堡", "熔火港", "灰骨镇", "幽焰窟"],
}


class Town:
    _next_id = 1

    def __init__(self, name: str, faction: str, x: int, y: int, owner: int | None = None):
        self.id = Town._next_id
        Town._next_id += 1
        self.name = name
        self.faction = faction
        self.x, self.y = x, y
        self.owner = owner
        self.buildings: set[str] = {"village_hall"}
        self.built_today = False
        self.available: dict[int, int] = {}          # tier -> 可招募数量
        self.garrison = Army()
        self.guild_spells: dict[int, list[str]] = {}  # 法师塔每级提供的法术
        self.visiting_hero: int | None = None         # 在城里的英雄 id

    # ---------- 建筑查询 ----------
    def has(self, bid: str, data: GameData | None = None) -> bool:
        """是否拥有某建筑（被更高级建筑替代也算有，如有了镇公所就算有村公所）。"""
        if bid in self.buildings:
            return True
        data = data or get_data()
        for b in self.buildings:
            cur = data.buildings.get(b)
            while cur is not None and cur.replaces:
                if cur.replaces == bid:
                    return True
                cur = data.buildings.get(cur.replaces)
        return False

    def income(self, data: GameData | None = None) -> int:
        data = data or get_data()
        return max((data.buildings[b].income for b in self.buildings if b in data.buildings), default=0)

    def fort_level(self, data: GameData | None = None) -> int:
        data = data or get_data()
        return max((data.buildings[b].fort_level for b in self.buildings if b in data.buildings), default=0)

    def guild_level(self, data: GameData | None = None) -> int:
        data = data or get_data()
        return max((data.buildings[b].guild_level for b in self.buildings if b in data.buildings), default=0)

    def hall_name(self, data: GameData | None = None) -> str:
        data = data or get_data()
        best = max((data.buildings[b] for b in self.buildings if b in data.buildings and data.buildings[b].income),
                   key=lambda b: b.income, default=None)
        return best.name if best else "无"

    def dwelling_built(self, tier: int) -> bool:
        return f"dwell{tier}" in self.buildings

    def growth(self, tier: int, data: GameData | None = None) -> int:
        """该级兵种每周产量：基础 × 城防加成 + 特色建筑加成。"""
        data = data or get_data()
        if not self.dwelling_built(tier):
            return 0
        base = data.faction_creature(self.faction, tier).growth
        fl = self.fort_level(data)
        mult = 1.0 + (0.5 if fl >= 2 else 0) + (0.5 if fl >= 3 else 0)
        g = int(base * mult)
        sb = data.factions[self.faction].special_building
        if sb["id"] in self.buildings and sb["growth_bonus"]["tier"] == tier:
            g += sb["growth_bonus"]["amount"]
        return g

    def all_spells(self) -> list[str]:
        out = []
        for lvl in sorted(self.guild_spells):
            out.extend(self.guild_spells[lvl])
        return out

    # ---------- 建造 ----------
    def can_build(self, bid: str, resources: dict, data: GameData | None = None,
                  player_has_capitol: bool = False) -> tuple[bool, str]:
        data = data or get_data()
        b = data.buildings.get(bid)
        if b is None:
            return False, "没有这种建筑"
        if bid not in self.buildable_ids(data):
            return False, "不属于本城"
        if self.has(bid, data):
            return False, "已建造"
        if self.built_today:
            return False, "今天已经建过了"
        for req in b.requires:
            if not self.has(req, data):
                return False, f"需要先建 {data.buildings[req].name}"
        if bid == "capitol" and player_has_capitol:
            return False, "已有王城"
        cost = data.building_cost(bid, self.faction)
        for r, n in cost.items():
            if resources.get(r, 0) < n:
                return False, f"{data.resource_names[r]}不足"
        return True, ""

    def buildable_ids(self, data: GameData | None = None) -> list[str]:
        data = data or get_data()
        ids = [b for b in data.buildings if b not in {f["special_building"]["id"] for f in [
            {"special_building": fac.special_building} for fac in data.factions.values()]}]
        ids.append(data.factions[self.faction].special_building["id"])
        return ids

    def build(self, bid: str, rng: random.Random, data: GameData | None = None) -> None:
        """执行建造（不检查资源，调用方先 can_build 并扣钱）。"""
        data = data or get_data()
        b = data.buildings[bid]
        if b.replaces and b.replaces in self.buildings:
            self.buildings.discard(b.replaces)
        self.buildings.add(bid)
        self.built_today = True
        if b.tier:
            self.available[b.tier] = self.growth(b.tier, data)
        if b.guild_level:
            self._roll_guild_spells(b.guild_level, rng, data)

    def _roll_guild_spells(self, level: int, rng: random.Random, data: GameData) -> None:
        pool = [s.id for s in data.spells_of_level(level)]
        n = {1: 4, 2: 3, 3: 3, 4: 2}[level]
        self.guild_spells[level] = rng.sample(pool, min(n, len(pool)))

    # ---------- 招募 ----------
    def recruit_cost(self, tier: int, n: int, data: GameData | None = None) -> dict:
        data = data or get_data()
        c = data.faction_creature(self.faction, tier)
        return {r: v * n for r, v in c.cost.items()}

    def max_recruit(self, tier: int, resources: dict, data: GameData | None = None) -> int:
        data = data or get_data()
        c = data.faction_creature(self.faction, tier)
        n = self.available.get(tier, 0)
        for r, v in c.cost.items():
            if v > 0:
                n = min(n, resources.get(r, 0) // v)
        return max(0, n)

    def recruit(self, tier: int, n: int, army: Army, data: GameData | None = None) -> bool:
        data = data or get_data()
        c = data.faction_creature(self.faction, tier)
        if n <= 0 or n > self.available.get(tier, 0) or not army.can_add(c):
            return False
        army.add(c, n)
        self.available[tier] -= n
        return True

    # ---------- 时间推进 ----------
    def new_day(self) -> None:
        self.built_today = False

    def new_week(self, data: GameData | None = None) -> None:
        data = data or get_data()
        for tier in range(1, 8):
            if self.dwelling_built(tier):
                self.available[tier] = self.available.get(tier, 0) + self.growth(tier, data)

    def __repr__(self) -> str:
        return f"<Town {self.name} ({self.faction}) owner={self.owner}>"
