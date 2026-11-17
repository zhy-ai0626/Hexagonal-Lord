"""冒险地图：地形、地图物件、寻路、视野。

地图是方格，英雄 8 方向移动。每种地形有移动消耗（草地 100），
斜向移动 ×1.41。树林、山脉、水域不可通行。
地图物件（城镇、矿、资源、野怪……）占一格，英雄走上去就触发"拜访"；
物件所在的格子只能作为路径终点，不能穿过。
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from enum import IntEnum

from .army import Army


class Terrain(IntEnum):
    GRASS = 0
    ROUGH = 1
    SWAMP = 2
    SNOW = 3
    ROAD = 4
    FOREST = 5
    MOUNTAIN = 6
    WATER = 7


TERRAIN_NAME = {
    Terrain.GRASS: "草地", Terrain.ROUGH: "荒原", Terrain.SWAMP: "沼泽", Terrain.SNOW: "雪地",
    Terrain.ROAD: "道路", Terrain.FOREST: "树林", Terrain.MOUNTAIN: "山脉", Terrain.WATER: "水域",
}
MOVE_COST = {
    Terrain.GRASS: 100, Terrain.ROUGH: 125, Terrain.SWAMP: 175, Terrain.SNOW: 150, Terrain.ROAD: 60,
}
BLOCKED = {Terrain.FOREST, Terrain.MOUNTAIN, Terrain.WATER}


class ObjKind:
    TOWN = "town"            # data: town_id
    MINE = "mine"            # data: resource, amount(每日产量)
    RESOURCE = "resource"    # data: resource, amount
    CHEST = "chest"          # 宝箱：选金币或经验
    MONSTER = "monster"      # 野怪：guard 是其军队
    ARTIFACT = "artifact"    # data: artifact
    DWELLING = "dwelling"    # 野外兵营：data: creature, available
    SHRINE = "shrine"        # 法术神殿：data: spell
    WELL = "well"            # 法力之泉：恢复全部法力
    TREE = "tree"            # 知识之树：花 2000 金升一级
    CAMPFIRE = "campfire"    # 营火：金币 + 一种资源
    STABLE = "stable"        # 马厩：本周移动力 +400（简化：当天移动力 +400）


OBJ_NAME = {
    ObjKind.TOWN: "城镇", ObjKind.MINE: "矿", ObjKind.RESOURCE: "资源", ObjKind.CHEST: "宝箱",
    ObjKind.MONSTER: "野怪", ObjKind.ARTIFACT: "宝物", ObjKind.DWELLING: "野外兵营",
    ObjKind.SHRINE: "法术神殿", ObjKind.WELL: "法力之泉", ObjKind.TREE: "知识之树",
    ObjKind.CAMPFIRE: "营火", ObjKind.STABLE: "马厩",
}
MINE_NAME = {"gold": "金矿", "wood": "伐木场", "ore": "采石场", "crystal": "魔晶矿", "stardust": "星砂井", "mithril": "秘银矿"}
MINE_OUTPUT = {"gold": 1000, "wood": 2, "ore": 2, "crystal": 1, "stardust": 1, "mithril": 1}


@dataclass
class MapObject:
    id: int
    kind: str
    x: int
    y: int
    data: dict = field(default_factory=dict)
    owner: int | None = None
    guard: Army | None = None

    @property
    def pos(self) -> tuple[int, int]:
        return self.x, self.y

    def display_name(self) -> str:
        if self.kind == ObjKind.MINE:
            return MINE_NAME[self.data["resource"]]
        return OBJ_NAME.get(self.kind, self.kind)


DIRS8 = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


class World:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.tiles: list[list[Terrain]] = [[Terrain.GRASS] * w for _ in range(h)]
        self.objects: dict[int, MapObject] = {}
        self.obj_at: dict[tuple[int, int], MapObject] = {}
        self._next_obj = 1

    # ---------- 地形 ----------
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def terrain(self, x: int, y: int) -> Terrain:
        return self.tiles[y][x]

    def set_terrain(self, x: int, y: int, t: Terrain) -> None:
        self.tiles[y][x] = t

    def passable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.tiles[y][x] not in BLOCKED

    # ---------- 物件 ----------
    def add_object(self, kind: str, x: int, y: int, data: dict | None = None,
                   owner: int | None = None, guard: Army | None = None) -> MapObject:
        obj = MapObject(self._next_obj, kind, x, y, data or {}, owner, guard)
        self._next_obj += 1
        self.objects[obj.id] = obj
        self.obj_at[(x, y)] = obj
        return obj

    def remove_object(self, obj: MapObject) -> None:
        self.objects.pop(obj.id, None)
        if self.obj_at.get((obj.x, obj.y)) is obj:
            del self.obj_at[(obj.x, obj.y)]

    def object_at(self, x: int, y: int) -> MapObject | None:
        return self.obj_at.get((x, y))

    # ---------- 寻路 ----------
    def step_cost(self, x0: int, y0: int, x1: int, y1: int, pathfinding: int = 0) -> int:
        """从 (x0,y0) 走到相邻格 (x1,y1) 的消耗。pathfinding 是寻路术减少的恶劣地形额外消耗。"""
        base = MOVE_COST[self.tiles[y1][x1]]
        if base > 100:
            base = 100 + max(0, base - 100 - pathfinding)
        if x0 != x1 and y0 != y1:
            base = int(base * 1.41)
        return base

    def find_path(self, start: tuple[int, int], goal: tuple[int, int],
                  blockers: set[tuple[int, int]] | None = None, pathfinding: int = 0,
                  stop_tiles: set[tuple[int, int]] | None = None) -> list[tuple[int, int, int]] | None:
        """Dijkstra 寻路。返回 [(x, y, 累计消耗), ...]（不含起点），走不到返回 None。

        blockers：完全不能进入的格子（其他英雄所在格，除非是终点）。
        stop_tiles：只能作为终点、不能穿过的格子（有物件的格子）。
        """
        if start == goal:
            return []
        if not self.passable(*goal):
            return None
        blockers = blockers or set()
        stop_tiles = stop_tiles if stop_tiles is not None else set(self.obj_at.keys())
        dist = {start: 0}
        prev: dict[tuple[int, int], tuple[int, int]] = {}
        pq = [(0, start)]
        while pq:
            d, cur = heapq.heappop(pq)
            if cur == goal:
                break
            if d > dist.get(cur, math.inf):
                continue
            if cur != start and cur in stop_tiles:
                continue        # 物件格只能作为终点
            cx, cy = cur
            for dx, dy in DIRS8:
                nx, ny = cx + dx, cy + dy
                if not self.passable(nx, ny):
                    continue
                if (nx, ny) in blockers and (nx, ny) != goal:
                    continue
                if dx and dy:
                    # 斜向不能从两个阻挡格之间挤过去
                    if not self.passable(cx + dx, cy) or not self.passable(cx, cy + dy):
                        continue
                nd = d + self.step_cost(cx, cy, nx, ny, pathfinding)
                if nd < dist.get((nx, ny), math.inf):
                    dist[(nx, ny)] = nd
                    prev[(nx, ny)] = cur
                    heapq.heappush(pq, (nd, (nx, ny)))
        if goal not in dist:
            return None
        path = []
        cur = goal
        while cur != start:
            path.append((cur[0], cur[1], dist[cur]))
            cur = prev[cur]
        path.reverse()
        return path

    def reachable_costs(self, start: tuple[int, int], max_cost: int, pathfinding: int = 0,
                        blockers: set | None = None) -> dict[tuple[int, int], int]:
        """start 出发、消耗不超过 max_cost 的所有可达格（物件格只能作为终点）。给 AI 用。"""
        blockers = blockers or set()
        dist = {start: 0}
        pq = [(0, start)]
        while pq:
            d, cur = heapq.heappop(pq)
            if d > dist.get(cur, math.inf):
                continue
            if cur != start and cur in self.obj_at:
                continue
            cx, cy = cur
            for dx, dy in DIRS8:
                nx, ny = cx + dx, cy + dy
                if not self.passable(nx, ny) or (nx, ny) in blockers:
                    continue
                if dx and dy and (not self.passable(cx + dx, cy) or not self.passable(cx, cy + dy)):
                    continue
                nd = d + self.step_cost(cx, cy, nx, ny, pathfinding)
                if nd <= max_cost and nd < dist.get((nx, ny), math.inf):
                    dist[(nx, ny)] = nd
                    heapq.heappush(pq, (nd, (nx, ny)))
        return dist

    def all_distances(self, start: tuple[int, int], pathfinding: int = 0,
                      blockers: set | None = None) -> dict[tuple[int, int], int]:
        return self.reachable_costs(start, 10 ** 9, pathfinding, blockers)

    # ---------- 视野 ----------
    def tiles_in_radius(self, x: int, y: int, r: int) -> list[tuple[int, int]]:
        out = []
        for yy in range(max(0, y - r), min(self.h, y + r + 1)):
            for xx in range(max(0, x - r), min(self.w, x + r + 1)):
                if (xx - x) ** 2 + (yy - y) ** 2 <= r * r + r:
                    out.append((xx, yy))
        return out
