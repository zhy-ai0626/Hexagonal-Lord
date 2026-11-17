"""随机地图生成。

步骤：
1. 用两层"值噪声"（粗网格随机值 + 双线性插值）生成高度和湿度，决定地形。
2. 玩家出生点放在四角，周围清成草地，放主城和起始英雄。
3. 在出生点之间铺路，保证连通（路会穿过树林和山脉）。
4. 按"离最近出生点的距离"决定守卫强度，撒矿、资源、宝箱、宝物、野外兵营、野怪等。
"""
from __future__ import annotations

import math
import random

from .army import Army
from .data import GameData
from .hero import Hero
from .town import TOWN_NAMES, Town
from .world import BLOCKED, MINE_OUTPUT, ObjKind, Terrain, World


def _value_noise(rng: random.Random, w: int, h: int, cell: int) -> list[list[float]]:
    gw, gh = w // cell + 2, h // cell + 2
    grid = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        gy, fy = divmod(y, cell)
        fy /= cell
        fy = fy * fy * (3 - 2 * fy)
        for x in range(w):
            gx, fx = divmod(x, cell)
            fx /= cell
            fx = fx * fx * (3 - 2 * fx)
            a = grid[gy][gx] * (1 - fx) + grid[gy][gx + 1] * fx
            b = grid[gy + 1][gx] * (1 - fx) + grid[gy + 1][gx + 1] * fx
            out[y][x] = a * (1 - fy) + b * fy
    return out


class MapGenerator:
    def __init__(self, data: GameData, rng: random.Random, w: int = 44, h: int = 44):
        self.data, self.rng, self.w, self.h = data, rng, w, h
        self.world = World(w, h)
        self.starts: list[tuple[int, int]] = []
        self.component: set[tuple[int, int]] = set()

    # ---------- 入口 ----------
    def generate(self, players: list) -> tuple[list[Town], list[Hero]]:
        self._terrain()
        self._starts(len(players))
        self._roads()
        towns, heroes = self._player_towns(players)
        self._component()
        self._neutral_towns(towns, len(players))
        self._objects(len(players))
        self._prune_unreachable()
        return towns, heroes

    # ---------- 地形 ----------
    def _terrain(self) -> None:
        w, h, rng = self.w, self.h, self.rng
        elev = _value_noise(rng, w, h, 7)
        moist = _value_noise(rng, w, h, 5)
        biome = _value_noise(rng, w, h, 11)
        for y in range(h):
            for x in range(w):
                e, m, b = elev[y][x], moist[y][x], biome[y][x]
                if e > 0.74:
                    t = Terrain.MOUNTAIN
                elif e < 0.22:
                    t = Terrain.WATER
                elif m > 0.68:
                    t = Terrain.FOREST
                elif b > 0.72:
                    t = Terrain.SNOW
                elif b < 0.25:
                    t = Terrain.SWAMP if m > 0.45 else Terrain.ROUGH
                else:
                    t = Terrain.GRASS
                self.world.set_terrain(x, y, t)

    def _clear(self, cx: int, cy: int, r: int, t: Terrain = Terrain.GRASS) -> None:
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            for x in range(max(0, cx - r), min(self.w, cx + r + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self.world.set_terrain(x, y, t)

    def _starts(self, n: int) -> None:
        m = 5
        corners = [(m, m), (self.w - 1 - m, self.h - 1 - m), (self.w - 1 - m, m), (m, self.h - 1 - m)]
        self.starts = corners[:n]
        for sx, sy in self.starts:
            self._clear(sx, sy, 4)

    # ---------- 道路与连通 ----------
    def _roads(self) -> None:
        """在每个出生点与地图中心之间，以及相邻出生点之间铺路。"""
        center = (self.w // 2, self.h // 2)
        self._clear(center[0], center[1], 3)
        pairs = [(s, center) for s in self.starts]
        for i in range(len(self.starts)):
            pairs.append((self.starts[i], self.starts[(i + 1) % len(self.starts)]))
        for a, b in pairs:
            for (x, y) in self._cheap_path(a, b):
                self.world.set_terrain(x, y, Terrain.ROAD)

    def _cheap_path(self, a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
        """阻挡格代价高的 4 方向 Dijkstra，得到一条尽量少穿山的路线。"""
        import heapq
        dist = {a: 0}
        prev = {}
        pq = [(0, a)]
        while pq:
            d, cur = heapq.heappop(pq)
            if cur == b:
                break
            if d > dist[cur]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cur[0] + dx, cur[1] + dy
                if not self.world.in_bounds(nx, ny):
                    continue
                t = self.world.terrain(nx, ny)
                c = 12 if t in BLOCKED else (1 if t == Terrain.ROAD else 3 + self.rng.random() * 2)
                nd = d + c
                if nd < dist.get((nx, ny), math.inf):
                    dist[(nx, ny)] = nd
                    prev[(nx, ny)] = cur
                    heapq.heappush(pq, (nd, (nx, ny)))
        path, cur = [], b
        while cur != a:
            path.append(cur)
            cur = prev[cur]
        path.append(a)
        return path

    def _component(self) -> None:
        """从第一个出生点出发可达的所有格子（不考虑物件）。"""
        start = self.starts[0]
        seen = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in seen or not self.world.passable(nx, ny):
                        continue
                    if dx and dy and (not self.world.passable(x + dx, y) or not self.world.passable(x, y + dy)):
                        continue
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        self.component = seen

    # ---------- 城镇与英雄 ----------
    def _player_towns(self, players: list) -> tuple[list[Town], list[Hero]]:
        towns, heroes = [], []
        used_names: set[str] = set()
        for p, (sx, sy) in zip(players, self.starts):
            name = self._town_name(p.faction, used_names)
            town = Town(name, p.faction, sx, sy, owner=p.idx)
            town.buildings |= {"tavern", "dwell1", "dwell2"}
            town.available = {1: town.growth(1, self.data), 2: town.growth(2, self.data)}
            town.garrison.add(self.data.faction_creature(p.faction, 1), 6)
            self.world.add_object(ObjKind.TOWN, sx, sy, {"town_id": town.id}, owner=p.idx)
            p.towns.append(town)
            towns.append(town)
            hdefs = self.data.heroes_of_faction(p.faction)
            hdef = self.rng.choice(hdefs)
            hx_, hy_ = sx + (1 if sx < self.w // 2 else -1), sy + (1 if sy < self.h // 2 else -1)
            hero = Hero(hdef, p.idx, hx_, hy_, self.data)
            hero.army.add(self.data.faction_creature(p.faction, 1), 12)
            hero.army.add(self.data.faction_creature(p.faction, 2), 6)
            hero.new_day()
            p.heroes.append(hero)
            p.hero_pool = [h.id for h in hdefs if h.id != hdef.id]
            self.rng.shuffle(p.hero_pool)
            heroes.append(hero)
        return towns, heroes

    def _town_name(self, faction: str, used: set[str]) -> str:
        pool = [n for n in TOWN_NAMES[faction] if n not in used]
        name = self.rng.choice(pool) if pool else f"{faction}-{len(used)}"
        used.add(name)
        return name

    def _neutral_towns(self, towns: list[Town], n_players: int) -> None:
        """地图中部放 1–2 座无主城镇，有守军。"""
        used = {t.name for t in towns}
        n = 1 if n_players <= 2 else 2
        cands = [(x, y) for (x, y) in self.component
                 if self._dist_to_start((x, y)) > 14 and self._free_area(x, y, 2)]
        self.rng.shuffle(cands)
        for (x, y) in cands[:n]:
            faction = self.rng.choice(list(self.data.factions))
            town = Town(self._town_name(faction, used), faction, x, y, owner=None)
            town.buildings |= {"dwell1", "dwell2", "fort"}
            town.available = {1: town.growth(1, self.data), 2: town.growth(2, self.data)}
            g = town.garrison
            g.add(self.data.faction_creature(faction, 2), 15)
            g.add(self.data.faction_creature(faction, 3), 6)
            self.world.add_object(ObjKind.TOWN, x, y, {"town_id": town.id})
            towns.append(town)

    # ---------- 物件 ----------
    def _dist_to_start(self, p: tuple[int, int]) -> float:
        return min(math.hypot(p[0] - s[0], p[1] - s[1]) for s in self.starts)

    def _free_area(self, x: int, y: int, r: int) -> bool:
        """(x,y) 周围 r 格内没有别的物件、不是道路，且周围开阔。"""
        if self.world.terrain(x, y) == Terrain.ROAD:
            return False
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if (x + dx, y + dy) in self.world.obj_at:
                    return False
        open_n = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if self.world.passable(x + dx, y + dy))
        return open_n >= 6

    def _pick_spot(self, dmin: float, dmax: float, spacing: int = 2) -> tuple[int, int] | None:
        for _ in range(300):
            x, y = self.rng.randrange(self.w), self.rng.randrange(self.h)
            if (x, y) not in self.component:
                continue
            d = self._dist_to_start((x, y))
            if dmin <= d <= dmax and self._free_area(x, y, spacing):
                return x, y
        return None

    def _guard(self, budget: float) -> Army | None:
        """按价值预算生成一支守军：挑一种中立或种族兵种，数量 = 预算 / 单体价值。"""
        if budget <= 0:
            return None
        pool = list(self.data.neutrals) + [c for f in self.data.factions.values() for c in f.creatures]
        # 预算小就用低阶兵，预算大就允许高阶
        max_tier = 1 + int(min(6, budget / 900))
        pool = [c for c in pool if c.tier <= max_tier and c.tier >= max(1, max_tier - 2)]
        ct = self.rng.choice(pool)
        n = max(1, int(budget / ct.value))
        army = Army()
        army.add(ct, n)
        return army

    def _budget(self, p: tuple[int, int], base: float, scale: float) -> float:
        """守卫预算：离出生点越远越强。"""
        t = min(1.0, max(0.0, (self._dist_to_start(p) - 5) / 30))
        return base + scale * t * t + self.rng.random() * base * 0.5

    def _objects(self, n_players: int) -> None:
        w, rng, d = self.world, self.rng, self.data
        # 每个出生点附近：金矿、伐木场、采石场（轻守卫）
        for sx, sy in self.starts:
            for res in ("gold", "wood", "ore"):
                for _ in range(100):
                    x, y = sx + rng.randint(-8, 8), sy + rng.randint(-8, 8)
                    if (x, y) in self.component and 3 <= math.hypot(x - sx, y - sy) <= 8 and self._free_area(x, y, 2):
                        guard = self._guard(150 + rng.random() * 150) if res != "gold" or rng.random() < 0.7 else None
                        w.add_object(ObjKind.MINE, x, y, {"resource": res, "amount": MINE_OUTPUT[res]}, guard=guard)
                        break
            # 附近几堆资源和一个宝箱
            for _ in range(4):
                spot = self._near(sx, sy, 2, 7)
                if spot:
                    res = rng.choice(["gold", "wood", "ore", "wood", "ore"])
                    amt = rng.randint(500, 1200) if res == "gold" else rng.randint(4, 9)
                    w.add_object(ObjKind.RESOURCE, *spot, {"resource": res, "amount": amt})
            spot = self._near(sx, sy, 3, 7)
            if spot:
                w.add_object(ObjKind.CHEST, *spot)
        # 全图：稀有矿
        for res in ("crystal", "stardust", "mithril"):
            for _ in range(n_players):
                spot = self._pick_spot(9, 24)
                if spot:
                    w.add_object(ObjKind.MINE, *spot, {"resource": res, "amount": MINE_OUTPUT[res]},
                                 guard=self._guard(self._budget(spot, 400, 1500)))
        # 更多金矿/木/矿在中距离
        for res in ("gold", "wood", "ore"):
            for _ in range(n_players):
                spot = self._pick_spot(10, 30)
                if spot:
                    w.add_object(ObjKind.MINE, *spot, {"resource": res, "amount": MINE_OUTPUT[res]},
                                 guard=self._guard(self._budget(spot, 300, 1800)))
        # 资源堆、宝箱、营火
        for _ in range(14 * n_players):
            spot = self._pick_spot(3, 60, spacing=1)
            if spot:
                res = rng.choice(["gold", "wood", "ore", "crystal", "stardust", "mithril", "gold"])
                amt = rng.randint(400, 1500) if res == "gold" else rng.randint(3, 8)
                w.add_object(ObjKind.RESOURCE, *spot, {"resource": res, "amount": amt})
        for _ in range(4 * n_players):
            spot = self._pick_spot(6, 60)
            if spot:
                w.add_object(ObjKind.CHEST, *spot, guard=self._guard(self._budget(spot, 100, 600)) if rng.random() < 0.4 else None)
        for _ in range(3 * n_players):
            spot = self._pick_spot(6, 60)
            if spot:
                res = rng.choice(["wood", "ore", "crystal", "stardust", "mithril"])
                w.add_object(ObjKind.CAMPFIRE, *spot, {"gold": rng.randint(400, 800), "resource": res, "amount": rng.randint(3, 6)})
        # 宝物：按品级决定守卫
        arts = list(d.artifacts.values())
        rng.shuffle(arts)
        for art in arts[: 5 * n_players]:
            lo = {1: 4, 2: 9, 3: 14, 4: 18}[art.grade]
            spot = self._pick_spot(lo, 60)
            if spot:
                budget = {1: 300, 2: 900, 3: 2200, 4: 4500}[art.grade] * (0.8 + rng.random() * 0.5)
                w.add_object(ObjKind.ARTIFACT, *spot, {"artifact": art.id}, guard=self._guard(budget))
        # 野外兵营（中立兵种 + 种族 1–4 级）
        dw_pool = [c for c in d.neutrals if c.tier <= 5] + [c for f in d.factions.values() for c in f.creatures if c.tier <= 4]
        for _ in range(3 * n_players):
            spot = self._pick_spot(6, 60)
            if spot:
                ct = rng.choice(dw_pool)
                w.add_object(ObjKind.DWELLING, *spot, {"creature": ct.id, "available": ct.growth},
                             guard=self._guard(ct.value * ct.growth * 1.5) if rng.random() < 0.6 else None)
        # 法术神殿、法力之泉、知识之树、马厩
        spells = list(d.spells.values())
        for _ in range(2 * n_players):
            spot = self._pick_spot(5, 60)
            if spot:
                sp = rng.choice([s for s in spells if s.level <= 3])
                w.add_object(ObjKind.SHRINE, *spot, {"spell": sp.id})
        for kind, n in ((ObjKind.WELL, 2 * n_players), (ObjKind.TREE, n_players), (ObjKind.STABLE, n_players)):
            for _ in range(n):
                spot = self._pick_spot(5, 60)
                if spot:
                    w.add_object(kind, *spot)
        # 游荡野怪
        for _ in range(5 * n_players):
            spot = self._pick_spot(8, 60)
            if spot:
                w.add_object(ObjKind.MONSTER, *spot, guard=self._guard(self._budget(spot, 250, 3000)))

    def _near(self, sx: int, sy: int, dmin: int, dmax: int) -> tuple[int, int] | None:
        for _ in range(100):
            x, y = sx + self.rng.randint(-dmax, dmax), sy + self.rng.randint(-dmax, dmax)
            if (x, y) in self.component and dmin <= math.hypot(x - sx, y - sy) <= dmax and self._free_area(x, y, 1):
                return x, y
        return None

    def _prune_unreachable(self) -> None:
        """把放完物件后从出生点走不到的物件删掉（物件格只能作终点，可能堵路）。"""
        reach = self.world.all_distances(self.starts[0])
        for obj in list(self.world.objects.values()):
            if obj.pos not in reach and obj.kind != ObjKind.TOWN:
                self.world.remove_object(obj)
