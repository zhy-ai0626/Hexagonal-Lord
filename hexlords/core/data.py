"""读取 data/ 下的 JSON 数据表，整理成程序里用的对象。

所有数值都来自 JSON，改数据不用动代码。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

RESOURCES = ["gold", "wood", "ore", "crystal", "stardust", "mithril"]


@dataclass(frozen=True)
class CreatureType:
    id: str
    name: str
    faction: str            # 种族 id，中立为 "neutral"
    tier: int
    attack: int
    defense: int
    dmg_min: int
    dmg_max: int
    hp: int
    speed: int
    shots: int
    flying: bool
    abilities: frozenset
    cost: dict
    growth: int

    @property
    def ranged(self) -> bool:
        return self.shots > 0

    @property
    def avg_dmg(self) -> float:
        return (self.dmg_min + self.dmg_max) / 2

    @property
    def value(self) -> float:
        """单个生物的"战斗价值"，用于 AI 估算军队强弱和经验值。

        思路（和 HOMM 的 AI value 类似）：生命乘上防御修正，伤害乘上攻击修正，
        再开方，使高阶兵不会无限膨胀；远程和飞行各加成。
        """
        toughness = self.hp * (1 + self.defense * 0.05)
        punch = self.avg_dmg * (1 + self.attack * 0.05)
        v = (toughness * punch) ** 0.5
        if self.ranged:
            v *= 1.3
        if self.flying:
            v *= 1.1
        v *= 1 + max(0, self.speed - 4) * 0.03
        return v


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    level: int
    school: str
    cost: int
    kind: str
    target: str
    base: int = 0
    per_power: int = 0
    effect: dict = field(default_factory=dict)
    duration: str | int = 0
    desc: str = ""


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    values: tuple
    desc: str

    def describe(self, level: int) -> str:
        v = self.values[level - 1]
        pct = f"{int(round(v * 100))}%"
        return self.desc.format(pct=pct, val=v)


@dataclass(frozen=True)
class Artifact:
    id: str
    name: str
    slot: str
    grade: int
    bonus: dict
    desc: str


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    cost: dict
    requires: tuple
    replaces: str | None = None
    income: int = 0
    fort_level: int = 0
    guild_level: int = 0
    tier: int = 0
    desc: str = ""


@dataclass(frozen=True)
class HeroClass:
    id: str
    name: str
    faction: str
    primary: tuple
    growth: tuple
    growth_late: tuple
    start_skills: dict
    start_spells: tuple
    skill_weights: dict


@dataclass(frozen=True)
class HeroDef:
    id: str
    name: str
    cls: str
    specialty: str
    bio: str


@dataclass
class Faction:
    id: str
    name: str
    desc: str
    color: tuple
    rare_resource: str
    special_building: dict
    hero_classes: tuple
    creatures: list          # 按 tier 排序的 CreatureType
    dwelling_names: list


class GameData:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.dir = data_dir
        fj = self._load("factions.json")
        self.resource_names: dict = fj["resources"]
        self.creatures: dict[str, CreatureType] = {}
        self.factions: dict[str, Faction] = {}
        for fid, f in fj["factions"].items():
            cres = [self._creature(c, fid) for c in f["creatures"]]
            cres.sort(key=lambda c: c.tier)
            for c in cres:
                self.creatures[c.id] = c
            self.factions[fid] = Faction(
                id=fid, name=f["name"], desc=f["desc"], color=tuple(f["color"]),
                rare_resource=f["rare_resource"], special_building=f["special_building"],
                hero_classes=tuple(f["hero_classes"]), creatures=cres,
                dwelling_names=list(f["dwelling_names"]),
            )
        self.neutrals: list[CreatureType] = []
        for c in fj["neutrals"]:
            ct = self._creature(c, "neutral")
            self.creatures[ct.id] = ct
            self.neutrals.append(ct)

        sj = self._load("spells.json")
        self.spells: dict[str, Spell] = {}
        for s in sj["spells"]:
            self.spells[s["id"]] = Spell(
                id=s["id"], name=s["name"], level=s["level"], school=s["school"],
                cost=s["cost"], kind=s["kind"], target=s["target"],
                base=s.get("base", 0), per_power=s.get("per_power", 0),
                effect=s.get("effect", {}), duration=s.get("duration", 0), desc=s.get("desc", ""),
            )

        kj = self._load("skills.json")
        self.skills: dict[str, Skill] = {
            k["id"]: Skill(k["id"], k["name"], tuple(k["values"]), k["desc"]) for k in kj["skills"]
        }
        self.skill_level_names: list = kj["level_names"]

        aj = self._load("artifacts.json")
        self.artifacts: dict[str, Artifact] = {
            a["id"]: Artifact(a["id"], a["name"], a["slot"], a["grade"], a["bonus"], a["desc"])
            for a in aj["artifacts"]
        }
        self.slots: list = aj["slots"]
        self.slot_names: dict = aj["slot_names"]

        bj = self._load("buildings.json")
        self.buildings: dict[str, Building] = {}
        for b in bj["buildings"]:
            self.buildings[b["id"]] = Building(
                id=b["id"], name=b["name"], cost=b["cost"], requires=tuple(b["requires"]),
                replaces=b.get("replaces"), income=b.get("income", 0),
                fort_level=b.get("fort_level", 0), guild_level=b.get("guild_level", 0),
                tier=b.get("tier", 0), desc=b.get("desc", ""),
            )
        # 种族特色建筑也放进建筑表
        for f in self.factions.values():
            sb = f.special_building
            self.buildings[sb["id"]] = Building(
                id=sb["id"], name=sb["name"], cost=sb["cost"], requires=("dwell1",), desc=sb["desc"],
            )

        hj = self._load("heroes.json")
        self.hero_classes: dict[str, HeroClass] = {}
        for cid, c in hj["classes"].items():
            self.hero_classes[cid] = HeroClass(
                id=cid, name=c["name"], faction=c["faction"], primary=tuple(c["primary"]),
                growth=tuple(c["growth"]), growth_late=tuple(c["growth_late"]),
                start_skills=dict(c["start_skills"]), start_spells=tuple(c["start_spells"]),
                skill_weights=dict(c["skill_weights"]),
            )
        self.hero_defs: dict[str, HeroDef] = {
            h["id"]: HeroDef(h["id"], h["name"], h["cls"], h["specialty"], h.get("bio", ""))
            for h in hj["heroes"]
        }

    def _load(self, name: str):
        with open(self.dir / name, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _creature(c: dict, faction: str) -> CreatureType:
        return CreatureType(
            id=c["id"], name=c["name"], faction=faction, tier=c["tier"],
            attack=c["attack"], defense=c["defense"], dmg_min=c["dmg"][0], dmg_max=c["dmg"][1],
            hp=c["hp"], speed=c["speed"], shots=c.get("shots", 0), flying=c.get("flying", False),
            abilities=frozenset(c.get("abilities", [])), cost=dict(c.get("cost", {})),
            growth=c.get("growth", 1),
        )

    # ---------- 便捷查询 ----------
    def faction_creature(self, faction_id: str, tier: int) -> CreatureType:
        return self.factions[faction_id].creatures[tier - 1]

    def heroes_of_faction(self, faction_id: str) -> list[HeroDef]:
        return [h for h in self.hero_defs.values() if self.hero_classes[h.cls].faction == faction_id]

    def spells_of_level(self, level: int) -> list[Spell]:
        return [s for s in self.spells.values() if s.level == level]

    def building_cost(self, bid: str, faction_id: str) -> dict:
        """把 cost 里的 'rare' 换成该种族的稀有资源。"""
        cost = dict(self.buildings[bid].cost)
        if "rare" in cost:
            cost[self.factions[faction_id].rare_resource] = cost.pop("rare")
        return cost


_DATA: GameData | None = None


def get_data() -> GameData:
    global _DATA
    if _DATA is None:
        _DATA = GameData()
    return _DATA
