"""战斗引擎（不含界面）。

规则要点（参考英雄无敌 3 的结构，数值是自己定的）：
- 15×11 六角战场，进攻方在左（第 0 列），防守方在右（第 14 列）。
- 每回合所有部队按速度从高到低各行动一次；"等待"的部队排到本回合最后（按速度从低到高）。
- 伤害 = 基础伤害（每个生物掷一次骰子，超过 10 个按 10 次缩放）× 攻防修正
  攻 > 防：每点差 +5%，最高 +300%；防 > 攻：每点差 -2.5%，最低 -70%。
- 近战会遭到一次反击（每回合一次）；远程无反击，距离超过 10 格或被近身时伤害减半。
- 士气：行动后有概率再行动一次（每回合最多一次）；运气：伤害翻倍。
- 英雄每回合可施放一次法术。
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from . import hexmath as hx
from .army import Army, Stack
from .data import CreatureType, GameData, Spell, get_data
from .hero import Hero

ATTACKER, DEFENDER = 0, 1

# 不同部队数时的起始行（让阵型居中）
_ROWS = {1: [5], 2: [3, 7], 3: [2, 5, 8], 4: [1, 4, 6, 9], 5: [0, 3, 5, 7, 10],
         6: [0, 2, 4, 6, 8, 10], 7: [0, 2, 4, 5, 6, 8, 10]}


class BattleStack:
    """战场上的一支部队。"""

    def __init__(self, src: Stack, side: int, slot: int, hero: Hero | None):
        self.src = src
        self.type: CreatureType = src.type
        self.count = src.count
        self.start_count = src.count
        self.side = side
        self.slot = slot
        self.hero = hero
        self.hp_top = self.type.hp          # 最上面一个生物的当前生命
        self.pos: tuple[int, int] = (0, 0)
        self.shots = self.type.shots
        self.retaliations = 1
        self.waited = False
        self.acted = False
        self.defending = False
        self.morale_used = False
        self.effects: dict[str, int] = {}   # 法术 id -> 剩余回合
        self.effect_values: dict[str, dict] = {}
        self.entangled = 0
        self.poison = 0
        self.resurrect_used = False
        self.fort_bonus = 0
        self.specialty_bonus = 1 if (hero and hero.creature_specialty() == self.type.id) else 0

    # ---------- 状态 ----------
    @property
    def alive(self) -> bool:
        return self.count > 0

    @property
    def total_hp(self) -> int:
        return (self.count - 1) * self.type.hp + self.hp_top if self.count > 0 else 0

    @property
    def name(self) -> str:
        return self.type.name

    def has(self, ability: str) -> bool:
        return ability in self.type.abilities

    def effect_sum(self, key: str) -> int:
        return sum(v.get(key, 0) for v in self.effect_values.values())

    def has_effect_flag(self, key: str) -> bool:
        return any(v.get(key) for v in self.effect_values.values())

    @property
    def blind(self) -> bool:
        return self.has_effect_flag("blind")

    def attack_value(self) -> int:
        a = self.type.attack + self.specialty_bonus + self.effect_sum("attack")
        if self.hero:
            a += self.hero.stat("attack")
        return max(0, a)

    def defense_value(self) -> int:
        d = self.type.defense + self.specialty_bonus + self.effect_sum("defense") + self.fort_bonus
        if self.hero:
            d += self.hero.stat("defense")
        if self.defending:
            d += int(d * (0.5 if self.has("shield_wall") else 0.2)) + 1
        return max(0, d)

    def speed(self) -> int:
        return max(1, self.type.speed + self.specialty_bonus + self.effect_sum("speed"))

    def can_shoot(self) -> bool:
        return self.type.ranged and self.shots > 0

    # ---------- 受伤与治疗 ----------
    def take_damage(self, dmg: int) -> int:
        """承受伤害，返回死亡数。"""
        if dmg <= 0 or not self.alive:
            return 0
        before = self.count
        total = self.total_hp - dmg
        if total <= 0:
            self.count = 0
            self.hp_top = 0
            return before
        self.count = (total - 1) // self.type.hp + 1
        self.hp_top = total - (self.count - 1) * self.type.hp
        return before - self.count

    def heal(self, amount: int, resurrect: bool = False) -> int:
        """治疗。resurrect=True 时可以让已死亡的生物复活（不超过初始数量）。返回复活数。"""
        if amount <= 0:
            return 0
        if not self.alive and not resurrect:
            return 0
        if not self.alive:
            self.count, self.hp_top = 0, 0
        before = self.count
        cap = self.start_count * self.type.hp if resurrect else self.total_hp + (self.type.hp - self.hp_top)
        total = min(self.total_hp + amount, cap)
        self.count = (total - 1) // self.type.hp + 1 if total > 0 else 0
        self.hp_top = total - (self.count - 1) * self.type.hp if total > 0 else 0
        return self.count - before

    def __repr__(self) -> str:
        return f"<{self.name}×{self.count} side={self.side} pos={self.pos}>"


@dataclass
class BattleResult:
    winner: int
    casualties: list[dict] = field(default_factory=lambda: [{}, {}])   # 每方 {兵种名: 死亡数}
    xp: list[int] = field(default_factory=lambda: [0, 0])
    rounds: int = 0


class Battle:
    def __init__(self, att_hero: Hero | None, att_army: Army, def_hero: Hero | None, def_army: Army,
                 rng: random.Random, fort_level: int = 0, def_tavern: bool = False,
                 data: GameData | None = None, obstacles: int | None = None):
        self.data = data or get_data()
        self.rng = rng
        self.heroes = [att_hero, def_hero]
        self.armies = [att_army, def_army]
        self.fort_level = fort_level
        self.side_morale = [0, 0]
        self.side_luck = [0, 0]
        for s, h in enumerate(self.heroes):
            if h:
                self.side_morale[s] = h.morale()
                self.side_luck[s] = h.luck()
        if def_tavern:
            self.side_morale[DEFENDER] += 1
        self.stacks: list[BattleStack] = []
        self.obstacles: set[tuple[int, int]] = set()
        self.round = 0
        self.queue: deque[BattleStack] = deque()
        self.wait_list: list[BattleStack] = []
        self.current: BattleStack | None = None
        self.spell_cast = [False, False]
        self.log: list[str] = []
        self.over = False
        self.winner: int | None = None
        self.result: BattleResult | None = None
        self.last_damage: dict | None = None     # 给界面做动画用
        self._setup(obstacles)

    # ---------- 布阵 ----------
    def _setup(self, n_obstacles: int | None) -> None:
        for side, army in enumerate(self.armies):
            live = [(i, s) for i, s in enumerate(army.slots) if s is not None and s.count > 0]
            rows = _ROWS[max(1, min(7, len(live)))]
            col = 0 if side == ATTACKER else hx.BATTLE_W - 1
            for (slot, st), row in zip(live, rows):
                bs = BattleStack(st, side, slot, self.heroes[side])
                bs.pos = (col, row)
                if side == DEFENDER and self.fort_level:
                    bs.fort_bonus = 2 * self.fort_level
                self.stacks.append(bs)
            # 同方有"士气光环"的兵种：全队士气 +1
            if any("morale_aura" in st.type.abilities for _, st in live):
                self.side_morale[side] += 1
        n = self.rng.randint(4, 8) if n_obstacles is None else n_obstacles
        occupied = {s.pos for s in self.stacks}
        tries = 0
        while len(self.obstacles) < n and tries < 200:
            tries += 1
            c, r = self.rng.randint(2, hx.BATTLE_W - 3), self.rng.randint(0, hx.BATTLE_H - 1)
            if (c, r) not in occupied:
                self.obstacles.add((c, r))
        self._new_round()

    # ---------- 回合与行动顺序 ----------
    def alive_stacks(self, side: int | None = None) -> list[BattleStack]:
        return [s for s in self.stacks if s.alive and (side is None or s.side == side)]

    def stack_at(self, pos: tuple[int, int]) -> BattleStack | None:
        for s in self.stacks:
            if s.alive and s.pos == pos:
                return s
        return None

    def _new_round(self) -> None:
        self.round += 1
        self.spell_cast = [False, False]
        for s in self.alive_stacks():
            s.acted = s.waited = s.defending = s.morale_used = False
            s.retaliations = 1
            if s.poison > 0:
                dmg = max(1, s.total_hp // 10)
                killed = s.take_damage(dmg)
                s.poison -= 1
                self.log.append(f"{s.name} 中毒受到 {dmg} 点伤害，{killed} 个阵亡")
            if s.entangled > 0:
                s.entangled -= 1
            for eid in list(s.effects):
                s.effects[eid] -= 1
                if s.effects[eid] <= 0:
                    del s.effects[eid]
                    s.effect_values.pop(eid, None)
        self._check_over()
        order = sorted(self.alive_stacks(), key=lambda s: (-s.speed(), s.side, s.slot))
        self.queue = deque(order)
        self.wait_list = []
        self.log.append(f"—— 第 {self.round} 回合 ——")
        self._advance()

    def _advance(self) -> None:
        """选出下一个行动的部队。"""
        self.current = None
        if self.over:
            return
        while self.queue or self.wait_list:
            if not self.queue:
                self.queue = deque(sorted(self.wait_list, key=lambda s: (s.speed(), s.side)))
                self.wait_list = []
            s = self.queue.popleft()
            if not s.alive or s.acted:
                continue
            if s.blind:
                self.log.append(f"{s.name} 被致盲，无法行动")
                s.acted = True
                continue
            # 负士气：有概率跳过本回合
            m = self._morale_of(s)
            if m < 0 and self.rng.random() < -m / 12:
                self.log.append(f"{s.name} 士气低落，跳过行动")
                s.acted = True
                continue
            if s.has("resurrect") and not s.resurrect_used:
                self._auto_resurrect(s)
            self.current = s
            return
        self._new_round()

    def _morale_of(self, s: BattleStack) -> int:
        if s.has("undead"):
            return 0
        return max(-3, min(3, self.side_morale[s.side]))

    def _after_action(self, s: BattleStack) -> None:
        """一次行动结束后：判断士气再行动，否则轮到下一个。"""
        s.acted = True
        self._check_over()
        if not self.over and s.alive and not s.morale_used:
            m = self._morale_of(s)
            if m > 0 and self.rng.random() < m / 12:
                s.morale_used = True
                s.acted = False
                self.log.append(f"{s.name} 士气高涨，再次行动！")
                self.queue.appendleft(s)
        self._advance()

    # ---------- 移动 ----------
    def reachable(self, s: BattleStack) -> dict[tuple[int, int], int]:
        """s 本回合能走到的格子 -> 步数（含原地 0）。飞行可越过障碍和部队，但必须落在空格。"""
        if s.entangled > 0:
            return {s.pos: 0}
        maxd = s.speed()
        occupied = {o.pos for o in self.alive_stacks() if o is not s}
        if s.type.flying:
            out = {}
            for r in range(hx.BATTLE_H):
                for c in range(hx.BATTLE_W):
                    d = hx.distance(s.pos, (c, r))
                    if d <= maxd and (c, r) not in occupied and (c, r) not in self.obstacles:
                        out[(c, r)] = d
            return out
        dist = {s.pos: 0}
        q = deque([s.pos])
        while q:
            cur = q.popleft()
            if dist[cur] >= maxd:
                continue
            for nb in hx.neighbors(*cur):
                if nb in dist or nb in occupied or nb in self.obstacles:
                    continue
                dist[nb] = dist[cur] + 1
                q.append(nb)
        return dist

    def path_to(self, s: BattleStack, goal: tuple[int, int]) -> list[tuple[int, int]]:
        """给动画用的格子序列（地面单位 BFS 路径；飞行直接跳）。"""
        if s.type.flying or goal == s.pos:
            return [goal]
        occupied = {o.pos for o in self.alive_stacks() if o is not s}
        prev = {s.pos: None}
        q = deque([s.pos])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            for nb in hx.neighbors(*cur):
                if nb in prev or nb in occupied or nb in self.obstacles:
                    continue
                prev[nb] = cur
                q.append(nb)
        if goal not in prev:
            return [goal]
        path, cur = [], goal
        while cur != s.pos:
            path.append(cur)
            cur = prev[cur]
        return path[::-1]

    def attack_positions(self, s: BattleStack, target: BattleStack) -> list[tuple[int, int]]:
        """s 可以从哪些格子近战攻击 target（已在旁边则含当前位置）。"""
        reach = self.reachable(s)
        return [p for p in hx.neighbors(*target.pos) if p in reach]

    def melee_targets(self, s: BattleStack) -> dict[int, list[tuple[int, int]]]:
        out = {}
        for t in self.alive_stacks(1 - s.side):
            ps = self.attack_positions(s, t)
            if ps:
                out[id(t)] = ps
        return out

    def adjacent_enemy(self, s: BattleStack) -> bool:
        return any(t.pos in hx.neighbors(*s.pos) for t in self.alive_stacks(1 - s.side))

    # ---------- 行动 ----------
    def do_move(self, pos: tuple[int, int]) -> None:
        s = self.current
        assert s is not None
        reach = self.reachable(s)
        if pos not in reach:
            raise ValueError("走不到那里")
        s.pos = pos
        self.log.append(f"{s.name} 移动")
        self._after_action(s)

    def do_wait(self) -> None:
        s = self.current
        assert s is not None
        if s.waited:
            return self.do_defend()
        s.waited = True
        self.wait_list.append(s)
        self.log.append(f"{s.name} 等待")
        self._advance()

    def do_defend(self) -> None:
        s = self.current
        assert s is not None
        s.defending = True
        self.log.append(f"{s.name} 防御")
        self._after_action(s)

    def do_melee(self, target: BattleStack, from_pos: tuple[int, int] | None = None) -> None:
        s = self.current
        assert s is not None
        if target.side == s.side or not target.alive:
            raise ValueError("非法目标")
        ps = self.attack_positions(s, target)
        if not ps:
            raise ValueError("打不到")
        if from_pos is None:
            from_pos = s.pos if s.pos in ps else min(ps, key=lambda p: hx.distance(s.pos, p))
        if from_pos not in ps:
            raise ValueError("不能从那里攻击")
        moved = self.reachable(s).get(from_pos, 0)
        s.pos = from_pos
        self._strike(s, target, ranged=False, moved=moved)
        if target.alive and s.alive and target.retaliations > 0 and not target.has_effect_flag("blind_waking"):
            target.retaliations -= 1
            self.log.append(f"{target.name} 反击")
            self._strike(target, s, ranged=False, retaliation=True)
        target.effect_values.pop("blind_waking", None)
        self._after_action(s)

    def do_shoot(self, target: BattleStack) -> None:
        s = self.current
        assert s is not None
        if not s.can_shoot() or target.side == s.side or not target.alive:
            raise ValueError("不能射击")
        if self.adjacent_enemy(s) and not s.has("no_melee_penalty"):
            # 被近身的射手只能近战（有 no_melee_penalty 的可以照常射）
            if target.pos in hx.neighbors(*s.pos):
                return self.do_melee(target, s.pos)
            raise ValueError("被近身，无法射击")
        s.shots -= 1
        self._strike(s, target, ranged=True)
        if s.has("double_shot") and target.alive and s.shots > 0:
            s.shots -= 1
            self.log.append(f"{s.name} 二连射")
            self._strike(s, target, ranged=True)
        self._after_action(s)

    # ---------- 伤害 ----------
    def calc_damage(self, att: BattleStack, defn: BattleStack, ranged: bool, moved: int = 0,
                    retaliation: bool = False, lucky: bool = False) -> int:
        n = att.count
        if att.has_effect_flag("min_damage"):
            base = att.type.dmg_min * n
        elif att.has_effect_flag("max_damage"):
            base = att.type.dmg_max * n
        elif n <= 10:
            base = sum(self.rng.randint(att.type.dmg_min, att.type.dmg_max) for _ in range(n))
        else:
            base = sum(self.rng.randint(att.type.dmg_min, att.type.dmg_max) for _ in range(10)) * n / 10
        a, d = att.attack_value(), defn.defense_value()
        if a >= d:
            mult = 1 + 0.05 * min(a - d, 60)
        else:
            mult = 1 - 0.025 * min(d - a, 28)
        dmg = base * mult
        h = att.hero
        if h:
            if ranged:
                dmg *= 1 + float(h.skill_value("archery"))
            else:
                dmg *= 1 + float(h.skill_value("offense"))
        dh = defn.hero
        if dh:
            dmg *= 1 - float(dh.skill_value("armorer"))
        if ranged:
            if hx.distance(att.pos, defn.pos) > 10:
                dmg *= 0.5
        elif att.type.ranged and not att.has("no_melee_penalty"):
            dmg *= 0.5          # 射手被迫近战
        if att.has("charge") and moved > 0 and not retaliation:
            dmg *= 1 + 0.05 * moved
        if att.has_effect_flag("blind_waking_half") or retaliation and att.has_effect_flag("blind_half"):
            dmg *= 0.5
        if lucky:
            dmg *= 2
        return max(1, int(dmg))

    def _strike(self, att: BattleStack, defn: BattleStack, ranged: bool, moved: int = 0,
                retaliation: bool = False) -> None:
        luck = self.side_luck[att.side]
        lucky = luck > 0 and not retaliation and self.rng.random() < luck / 12
        if defn.blind:
            # 被打醒：解除致盲，反击时只有一半力量
            for eid in list(defn.effects):
                if defn.effect_values.get(eid, {}).get("blind"):
                    del defn.effects[eid]
                    del defn.effect_values[eid]
            defn.effect_values["blind_half"] = {"blind_half": True}
            defn.effects["blind_half"] = 1
        dmg = self.calc_damage(att, defn, ranged, moved, retaliation, lucky)
        killed = defn.take_damage(dmg)
        kind = "射击" if ranged else "攻击"
        txt = f"{att.name}×{att.count} {kind} {defn.name}，造成 {dmg} 点伤害，{killed} 个阵亡"
        if lucky:
            txt = "幸运一击！" + txt
        self.log.append(txt)
        self.last_damage = {"attacker": att, "target": defn, "dmg": dmg, "killed": killed, "ranged": ranged}
        # 命中后的特殊能力
        if att.has("life_drain") and dmg > 0:
            n = att.heal(dmg, resurrect=True)
            if n:
                self.log.append(f"{att.name} 吸取生命，复活 {n} 个")
        if att.has("mana_drain") and defn.hero and defn.hero.mana > 0:
            defn.hero.mana = max(0, defn.hero.mana - 2)
            self.log.append(f"{att.name} 吸走对方英雄 2 点法力")
        if att.has("blind_strike") and defn.alive and self.rng.random() < 0.2:
            self._apply_effect(defn, "blind_strike", {"blind": True}, 2)
            self.log.append(f"{defn.name} 被致盲")
        if att.has("entangle") and defn.alive:
            defn.entangled = 2
            self.log.append(f"{defn.name} 被缠绕，下回合无法移动")
        if att.has("poison_breath") and defn.alive and not ranged:
            defn.poison = 3
            self.log.append(f"{defn.name} 中毒")
        if att.has("fire_breath") and not ranged and not retaliation:
            self._breath(att, defn, dmg)
        # 反击时解除"半力"标记
        if retaliation:
            att.effects.pop("blind_half", None)
            att.effect_values.pop("blind_half", None)

    def _breath(self, att: BattleStack, defn: BattleStack, dmg: int) -> None:
        """烈焰吐息：目标身后一格的部队也受到同样伤害。"""
        ax, ay, az = hx.to_cube(*att.pos)
        tx, ty, tz = hx.to_cube(*defn.pos)
        bx, by, bz = 2 * tx - ax, 2 * ty - ay, 2 * tz - az
        col = bx + (bz - (bz & 1)) // 2
        behind = self.stack_at((col, bz))
        if behind and behind is not att:
            killed = behind.take_damage(dmg)
            self.log.append(f"烈焰吐息波及 {behind.name}，造成 {dmg} 点伤害，{killed} 个阵亡")

    def _auto_resurrect(self, s: BattleStack) -> None:
        """天使：每场战斗一次，自动复活损失最重的友军部队 100 点生命。"""
        cands = [o for o in self.stacks if o.side == s.side and o is not s and o.start_count > o.count]
        if not cands:
            return
        tgt = max(cands, key=lambda o: (o.start_count - o.count) * o.type.value)
        n = tgt.heal(100, resurrect=True)
        s.resurrect_used = True
        self.log.append(f"{s.name} 复活了 {n} 个 {tgt.name}")

    def _apply_effect(self, s: BattleStack, eid: str, values: dict, rounds: int) -> None:
        s.effects[eid] = max(1, rounds)
        s.effect_values[eid] = dict(values)

    # ---------- 法术 ----------
    def can_cast(self, side: int, spell: Spell) -> tuple[bool, str]:
        h = self.heroes[side]
        if h is None:
            return False, "没有英雄"
        if self.spell_cast[side]:
            return False, "本回合已施法"
        if spell.id not in h.spells:
            return False, "不会这个法术"
        if h.mana < spell.cost:
            return False, "法力不足"
        return True, ""

    def spell_targets(self, side: int, spell: Spell) -> list[tuple[int, int]]:
        """该法术可以点击的格子。"""
        if spell.target in ("all_enemies", "all_allies"):
            return []
        if spell.target == "area":
            return [(c, r) for r in range(hx.BATTLE_H) for c in range(hx.BATTLE_W)]
        if spell.target == "enemy":
            return [s.pos for s in self.alive_stacks(1 - side)]
        if spell.kind == "resurrect":
            return [s.pos for s in self.stacks if s.side == side and s.count < s.start_count]
        return [s.pos for s in self.alive_stacks(side)]

    def cast(self, side: int, spell: Spell, target: tuple[int, int] | None = None) -> None:
        ok, why = self.can_cast(side, spell)
        if not ok:
            raise ValueError(why)
        h = self.heroes[side]
        assert h is not None
        power = h.stat("power")
        duration = power if spell.duration == "power" else int(spell.duration or 0)
        duration = max(1, duration)
        h.mana -= spell.cost
        self.spell_cast[side] = True
        self.log.append(f"{h.name} 施放「{spell.name}」")
        targets: list[BattleStack] = []
        if spell.target == "all_enemies":
            targets = self.alive_stacks(1 - side)
        elif spell.target == "all_allies":
            targets = self.alive_stacks(side)
        elif spell.target == "area":
            assert target is not None
            targets = [s for s in self.alive_stacks() if s.pos in hx.area(target, 1)]
        else:
            assert target is not None
            t = self.stack_at(target)
            if t is None and spell.kind == "resurrect":
                t = next((s for s in self.stacks if s.pos == target and s.side == side), None)
            if t is None:
                raise ValueError("目标无效")
            targets = [t]
        amount = int((spell.base + spell.per_power * power) * (h.spell_damage_mult() if spell.kind == "damage" else 1))
        for t in targets:
            if spell.kind == "damage":
                dmg = amount // 2 if t.has("spell_resist") else amount
                killed = t.take_damage(dmg)
                self.log.append(f"「{spell.name}」对 {t.name} 造成 {dmg} 点伤害，{killed} 个阵亡")
            elif spell.kind == "heal":
                t.heal(amount)
                self.log.append(f"{t.name} 恢复 {amount} 点生命")
            elif spell.kind == "resurrect":
                n = t.heal(amount, resurrect=True)
                self.log.append(f"复活了 {n} 个 {t.name}")
            else:
                self._apply_effect(t, spell.id, spell.effect, duration)
        self._check_over()
        if self.over:
            self.current = None

    # ---------- 结束 ----------
    def _check_over(self) -> None:
        if self.over:
            return
        a, d = self.alive_stacks(ATTACKER), self.alive_stacks(DEFENDER)
        if a and d:
            return
        self.over = True
        self.winner = DEFENDER if not a else ATTACKER
        self.current = None
        self._finish()

    def surrender(self, side: int) -> None:
        """撤退：该方视为战败（部队全部损失）。"""
        for s in self.alive_stacks(side):
            s.count = 0
        self.over = True
        self.winner = 1 - side
        self.current = None
        self.log.append("撤退了")
        self._finish()

    def _finish(self) -> None:
        res = BattleResult(winner=self.winner, rounds=self.round)
        for s in self.stacks:
            dead = s.start_count - s.count
            if dead > 0:
                res.casualties[s.side][s.name] = res.casualties[s.side].get(s.name, 0) + dead
                res.xp[1 - s.side] += int(dead * s.type.value)
            # 把结果写回原军队
            s.src.count = s.count
        for a in self.armies:
            a.remove_dead()
        self.result = res
        self.log.append("战斗结束：" + ("进攻方胜利" if self.winner == ATTACKER else "防守方胜利"))
