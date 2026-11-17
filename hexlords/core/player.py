"""玩家：资源、英雄、城镇、探索过的区域。人类和电脑玩家都用这个类。"""
from __future__ import annotations

from .data import RESOURCES

PLAYER_COLORS = [
    ("红", (220, 60, 60)),
    ("蓝", (70, 110, 230)),
    ("绿", (60, 180, 90)),
    ("橙", (240, 160, 50)),
]

START_RESOURCES = {"gold": 10000, "wood": 20, "ore": 20, "crystal": 5, "stardust": 5, "mithril": 5}


class Player:
    def __init__(self, idx: int, name: str, faction: str, is_ai: bool):
        self.idx = idx
        self.name = name
        self.faction = faction
        self.is_ai = is_ai
        self.color_name, self.color = PLAYER_COLORS[idx]
        self.resources: dict[str, int] = dict(START_RESOURCES)
        self.heroes: list = []           # Hero 对象
        self.towns: list = []            # Town 对象
        self.explored: set[tuple[int, int]] = set()
        self.alive = True
        self.days_without_town = 0
        self.hero_pool: list[str] = []   # 酒馆里可雇佣的英雄 def_id
        self.visited_objects: set[int] = set()   # 每玩家只能领一次的地点

    def can_afford(self, cost: dict) -> bool:
        return all(self.resources.get(r, 0) >= n for r, n in cost.items())

    def pay(self, cost: dict) -> None:
        for r, n in cost.items():
            self.resources[r] = self.resources.get(r, 0) - n

    def gain(self, res: dict) -> None:
        for r, n in res.items():
            self.resources[r] = self.resources.get(r, 0) + n

    def has_capitol(self) -> bool:
        return any("capitol" in t.buildings for t in self.towns)

    def market_count(self) -> int:
        return sum(1 for t in self.towns if "market" in t.buildings)

    def trade_rate(self, give: str, get: str) -> int:
        """市场汇率：用 n 个 give 换 1 个 get。市场越多越划算。"""
        m = self.market_count()
        if m == 0:
            return 0
        base = {1: 10, 2: 7, 3: 5}.get(m, 4)
        rare = {"crystal", "stardust", "mithril"}
        if give == "gold":
            # 金币换资源：1 木/矿 = base*250 金，1 稀有 = base*500 金
            return base * (500 if get in rare else 250)
        if get == "gold":
            # 资源换金币：每个木/矿给 250/base*... 简化为固定
            return 1    # 1 个资源换 (下方 gold_per_resource) 金币
        if give in rare and get not in rare:
            return max(1, base // 2)
        if give not in rare and get in rare:
            return base * 2
        return base

    def gold_per_resource(self, give: str) -> int:
        m = self.market_count()
        base = {1: 10, 2: 7, 3: 5}.get(m, 4)
        rare = {"crystal", "stardust", "mithril"}
        return (5000 if give in rare else 2500) // base

    def summary(self) -> str:
        return " ".join(f"{r}:{self.resources.get(r, 0)}" for r in RESOURCES)
