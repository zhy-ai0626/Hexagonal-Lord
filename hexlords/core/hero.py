"""英雄：四维属性、等级经验、副技能、法术、宝物、军队、移动力、法力。"""
from __future__ import annotations

import random

from .army import Army
from .data import Artifact, GameData, HeroClass, HeroDef, get_data

PRIMARY = ["attack", "defense", "power", "knowledge"]
PRIMARY_NAMES = {"attack": "攻击", "defense": "防御", "power": "魔力", "knowledge": "知识"}
MAX_SKILLS = 8          # 最多学 8 个副技能
MAX_LEVEL = 30


def xp_for_level(level: int) -> int:
    """升到 level 级所需的累计经验（1 级 0，2 级 1000，3 级 2200，4 级 3600 ...）。"""
    if level <= 1:
        return 0
    n = level - 1
    return 1000 * n + 100 * n * (n - 1)


class Hero:
    _next_id = 1

    def __init__(self, hdef: HeroDef, owner: int, x: int, y: int, data: GameData | None = None):
        data = data or get_data()
        self.id = Hero._next_id
        Hero._next_id += 1
        self.def_id = hdef.id
        self.name = hdef.name
        self.cls: HeroClass = data.hero_classes[hdef.cls]
        self.faction = self.cls.faction
        self.specialty = hdef.specialty
        self.owner = owner
        self.x, self.y = x, y

        self.attack, self.defense, self.power, self.knowledge = self.cls.primary
        self.level = 1
        self.xp = 0
        self.pending_levelups = 0
        self.skills: dict[str, int] = dict(self.cls.start_skills)
        self.spells: set[str] = set(self.cls.start_spells)
        self.equipment: dict[str, Artifact] = {}
        self.backpack: list[Artifact] = []
        self.army = Army()
        self.mana = self.max_mana
        self.max_move = 0
        self.move_points = 0
        self.visited_once: set = set()      # 只能用一次的地点（知识树等）
        self.sleeping = False

    # ---------- 属性 ----------
    def art_bonus(self, key: str) -> float:
        return sum(a.bonus.get(key, 0) for a in self.equipment.values())

    def stat(self, name: str) -> int:
        return getattr(self, name) + int(self.art_bonus(name))

    @property
    def max_mana(self) -> int:
        return self.stat("knowledge") * 10

    def skill_level(self, sid: str) -> int:
        return self.skills.get(sid, 0)

    def skill_value(self, sid: str, data: GameData | None = None):
        """技能效果值（没学返回 0）；专精技能效果 ×1.5。"""
        lvl = self.skill_level(sid)
        if lvl == 0:
            return 0
        data = data or get_data()
        v = data.skills[sid].values[lvl - 1]
        if self.specialty == f"skill:{sid}":
            v = v * 1.5
        return v

    def morale(self) -> int:
        m = int(self.skill_value("leadership")) + int(self.art_bonus("morale"))
        return max(-3, min(3, m))

    def luck(self) -> int:
        l = int(self.skill_value("luck")) + int(self.art_bonus("luck"))
        return max(-3, min(3, l))

    def sight_radius(self) -> int:
        return 5 + int(self.skill_value("scouting"))

    def max_spell_level(self) -> int:
        return max(2, int(self.skill_value("wisdom")))

    def spell_damage_mult(self) -> float:
        return 1 + float(self.skill_value("sorcery")) + float(self.art_bonus("spell_dmg"))

    def mana_regen(self) -> int:
        return 1 + int(self.skill_value("mysticism")) + int(self.art_bonus("mana_regen"))

    def daily_gold(self) -> int:
        g = int(self.skill_value("estates")) + int(self.art_bonus("gold"))
        if self.specialty.startswith("gold:"):
            g += int(self.specialty.split(":")[1])
        return g

    def creature_specialty(self) -> str | None:
        if self.specialty.startswith("creature:"):
            return self.specialty.split(":")[1]
        return None

    # ---------- 移动 ----------
    def compute_max_move(self) -> int:
        """移动力由最慢的兵种决定：速度 3 → 1500，每多 1 点速度 +60，最高按速度 11 计。"""
        spd = self.army.min_speed()
        spd = max(3, min(11, spd if spd else 3))
        base = 1500 + 60 * (spd - 3)
        base = int(base * (1 + float(self.skill_value("logistics"))))
        return base + int(self.art_bonus("move"))

    def new_day(self, in_town_with_guild: bool = False) -> None:
        self.max_move = self.compute_max_move()
        self.move_points = self.max_move
        if in_town_with_guild:
            self.mana = self.max_mana
        else:
            self.mana = min(self.max_mana, self.mana + self.mana_regen())

    # ---------- 经验 ----------
    def add_xp(self, amount: int) -> int:
        """增加经验，返回新获得的升级次数（升级的具体处理由 Game 做，因为要选技能）。"""
        self.xp += amount
        gained = 0
        while self.level + self.pending_levelups < MAX_LEVEL and self.xp >= xp_for_level(self.level + self.pending_levelups + 1):
            self.pending_levelups += 1
            gained += 1
        return gained

    def roll_levelup(self, rng: random.Random, data: GameData | None = None) -> dict:
        """生成一次升级的内容：主属性 +1（按职业权重随机）、两个副技能选项。"""
        data = data or get_data()
        weights = self.cls.growth if self.level < 10 else self.cls.growth_late
        stat = rng.choices(PRIMARY, weights=weights)[0]
        options = self._skill_options(rng, data)
        return {"stat": stat, "skills": options}

    def _skill_options(self, rng: random.Random, data: GameData) -> list[str]:
        upgradable = [s for s, l in self.skills.items() if l < 3]
        learnable = [s for s in data.skills if s not in self.skills] if len(self.skills) < MAX_SKILLS else []
        pool = []
        if upgradable:
            pool.append(rng.choice(upgradable))
        if learnable:
            w = [self.cls.skill_weights.get(s, 1) for s in learnable]
            pick = rng.choices(learnable, weights=w)[0]
            pool.append(pick)
            if not upgradable and len(learnable) > 1:
                rest = [s for s in learnable if s != pick]
                w2 = [self.cls.skill_weights.get(s, 1) for s in rest]
                pool.append(rng.choices(rest, weights=w2)[0])
        elif len(upgradable) > 1:
            rest = [s for s in upgradable if s != pool[0]]
            pool.append(rng.choice(rest))
        return pool

    def apply_levelup(self, stat: str, skill: str | None) -> None:
        self.level += 1
        self.pending_levelups = max(0, self.pending_levelups - 1)
        setattr(self, stat, getattr(self, stat) + 1)
        if skill:
            self.skills[skill] = self.skills.get(skill, 0) + 1
        if stat == "knowledge":
            self.mana = min(self.max_mana, self.mana + 10)

    # ---------- 宝物 ----------
    def equip(self, art: Artifact) -> None:
        """装上宝物；槽位被占则放进背包。"""
        if art.slot not in self.equipment:
            self.equipment[art.slot] = art
        else:
            self.backpack.append(art)

    def unequip(self, slot: str) -> None:
        if slot in self.equipment:
            self.backpack.append(self.equipment.pop(slot))

    def all_artifacts(self) -> list[Artifact]:
        return list(self.equipment.values()) + list(self.backpack)

    # ---------- 其他 ----------
    def can_learn(self, spell_level: int) -> bool:
        return spell_level <= self.max_spell_level()

    def strength(self) -> float:
        """粗略战斗力（给 AI 和界面用）：军队价值 × 英雄攻防修正。"""
        return self.army.total_value() * (1 + 0.04 * (self.stat("attack") + self.stat("defense")))

    def __repr__(self) -> str:
        return f"<Hero {self.name} L{self.level} @({self.x},{self.y})>"
