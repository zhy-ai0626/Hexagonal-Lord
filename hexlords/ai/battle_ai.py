"""战斗 AI：给当前行动的部队挑一个动作；给英雄挑法术。

思路（和 HOMM 讲义里的"选目标 = 我造成的价值 − 我挨反击损失的价值"一致）：
- 能射击就射"期望击杀价值"最高的目标，优先敌方射手。
- 近战：对每个打得到的目标，算 期望输出价值 − 期望反击损失价值，取最大。
- 打不到任何人：朝最近的敌人靠近；如果已经贴不上了，慢的部队先等待再防御。
"""
from __future__ import annotations

from ..core import hexmath as hx
from ..core.battle import Battle, BattleStack
from ..core.data import Spell, get_data


def expected_damage(b: Battle, att: BattleStack, defn: BattleStack, ranged: bool, moved: int = 0) -> float:
    """不掷骰子的平均伤害（复制 Battle.calc_damage 的公式）。"""
    n = att.count
    if att.has_effect_flag("min_damage"):
        base = att.type.dmg_min * n
    elif att.has_effect_flag("max_damage"):
        base = att.type.dmg_max * n
    else:
        base = att.type.avg_dmg * n
    a, d = att.attack_value(), defn.defense_value()
    mult = 1 + 0.05 * min(a - d, 60) if a >= d else 1 - 0.025 * min(d - a, 28)
    dmg = base * mult
    if att.hero:
        dmg *= 1 + float(att.hero.skill_value("archery" if ranged else "offense"))
    if defn.hero:
        dmg *= 1 - float(defn.hero.skill_value("armorer"))
    if ranged and hx.distance(att.pos, defn.pos) > 10:
        dmg *= 0.5
    if not ranged and att.type.ranged and not att.has("no_melee_penalty"):
        dmg *= 0.5
    if att.has("charge") and moved > 0:
        dmg *= 1 + 0.05 * moved
    return max(1.0, dmg)


def value_lost(defn: BattleStack, dmg: float) -> float:
    """dmg 点伤害对 defn 造成的"价值损失"（按生命比例折算成战斗价值）。"""
    total = defn.total_hp
    if total <= 0:
        return 0
    frac = min(1.0, dmg / total)
    v = defn.count * defn.type.value * frac
    if defn.type.ranged:
        v *= 1.2        # 优先打射手
    return v


def choose_action(b: Battle) -> None:
    """对 b.current 执行一个动作。"""
    s = b.current
    if s is None:
        return
    enemies = b.alive_stacks(1 - s.side)
    if not enemies:
        return
    # 1. 射击
    if s.can_shoot() and not (b.adjacent_enemy(s) and not s.has("no_melee_penalty")):
        best = max(enemies, key=lambda t: value_lost(t, expected_damage(b, s, t, True)))
        b.do_shoot(best)
        return
    # 2. 近战
    best_score, best_target, best_from = None, None, None
    reach = b.reachable(s)
    for t in enemies:
        for p in hx.neighbors(*t.pos):
            if p not in reach:
                continue
            moved = reach[p]
            gain = value_lost(t, expected_damage(b, s, t, False, moved))
            # 反击损失：目标存活且还有反击次数
            dmg_to_t = expected_damage(b, s, t, False, moved)
            survivors = max(0, t.total_hp - dmg_to_t)
            loss = 0.0
            if survivors > 0 and t.retaliations > 0 and not t.blind:
                # 粗略：按存活比例缩放反击
                frac = survivors / t.total_hp
                loss = value_lost(s, expected_damage(b, t, s, False) * frac)
            score = gain - loss * 0.8
            if best_score is None or score > best_score:
                best_score, best_target, best_from = score, t, p
    if best_target is not None:
        b.do_melee(best_target, best_from)
        return
    # 3. 靠近最近的敌人
    if s.entangled > 0 or len(reach) <= 1:
        b.do_defend()
        return
    target = min(enemies, key=lambda t: hx.distance(s.pos, t.pos))
    dest = min(reach, key=lambda p: (hx.distance(p, target.pos), reach[p]))
    if dest == s.pos or hx.distance(dest, target.pos) >= hx.distance(s.pos, target.pos):
        if not s.waited:
            b.do_wait()
        else:
            b.do_defend()
        return
    b.do_move(dest)


def choose_spell(b: Battle, side: int) -> tuple[Spell, tuple[int, int] | None] | None:
    """给 side 方英雄挑一个法术和目标；不值得施法返回 None。"""
    h = b.heroes[side]
    if h is None or b.spell_cast[side]:
        return None
    data = get_data()
    power = h.stat("power")
    enemies = b.alive_stacks(1 - side)
    allies = b.alive_stacks(side)
    if not enemies or not allies:
        return None
    best: tuple[float, Spell, tuple[int, int] | None] | None = None
    for sid in h.spells:
        sp = data.spells[sid]
        if h.mana < sp.cost:
            continue
        if sp.kind == "damage":
            amount = (sp.base + sp.per_power * power) * h.spell_damage_mult()
            if sp.target == "area":
                for center in {e.pos for e in enemies}:
                    cells = set(hx.area(center, 1))
                    v = sum(value_lost(t, amount / (2 if t.has("spell_resist") else 1)) * (1 if t.side != side else -1.5)
                            for t in b.alive_stacks() if t.pos in cells)
                    if best is None or v > best[0]:
                        best = (v, sp, center)
            else:
                for t in enemies:
                    v = value_lost(t, amount / (2 if t.has("spell_resist") else 1))
                    if best is None or v > best[0]:
                        best = (v, sp, t.pos)
        elif sp.kind in ("heal", "resurrect"):
            amount = sp.base + sp.per_power * power
            for t in (b.stacks if sp.kind == "resurrect" else allies):
                if t.side != side or t.count >= t.start_count:
                    continue
                missing = t.start_count * t.type.hp - t.total_hp
                v = min(amount, missing) / t.type.hp * t.type.value * 0.9
                if best is None or v > best[0]:
                    best = (v, sp, t.pos)
        elif sp.kind == "debuff" and sp.target in ("enemy", "all_enemies"):
            tgt = max(enemies, key=lambda t: t.count * t.type.value)
            if sp.id in tgt.effects:
                continue
            v = tgt.count * tgt.type.value * (0.25 if sp.target == "enemy" else 0.35)
            if sp.effect.get("blind"):
                v *= 1.5
            if best is None or v > best[0]:
                best = (v, sp, tgt.pos if sp.target == "enemy" else None)
        elif sp.kind == "buff":
            tgt = max(allies, key=lambda t: t.count * t.type.value)
            if sp.id in tgt.effects:
                continue
            v = tgt.count * tgt.type.value * (0.2 if sp.target == "ally" else 0.3)
            if best is None or v > best[0]:
                best = (v, sp, tgt.pos if sp.target == "ally" else None)
    if best is None:
        return None
    # 价值太低就省法力（阈值：相当于杀掉 1 个低阶兵）
    if best[0] < 8:
        return None
    return best[1], best[2]


def auto_resolve(b: Battle, ai_sides: tuple[int, ...] = (0, 1), max_rounds: int = 60) -> None:
    """让 AI 把战斗打完（双方都由 AI 操作）。"""
    guard = 0
    while not b.over and guard < 5000:
        guard += 1
        s = b.current
        if s is None:
            break
        if s.side in ai_sides:
            cast = choose_spell(b, s.side)
            if cast:
                try:
                    b.cast(s.side, cast[0], cast[1])
                except ValueError:
                    pass
                if b.over:
                    break
        choose_action(b)
        if b.round > max_rounds:
            # 僵局：伤害总和多的一方判胜
            tot = [sum(x.total_hp for x in b.alive_stacks(0)), sum(x.total_hp for x in b.alive_stacks(1))]
            b.surrender(0 if tot[0] < tot[1] else 1)
