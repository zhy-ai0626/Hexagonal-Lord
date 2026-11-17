"""战斗画面：六角格战场、部队、行动按钮、法术书、战斗记录。

人类玩家：点己方可达格移动，点敌人攻击（射手自动射击），右侧按钮等待/防御/施法/自动/撤退。
电脑一方由 battle_ai 操作，带一点延迟让人看清。
"""
from __future__ import annotations

import math

import pygame

from ..ai.battle_ai import choose_action, choose_spell
from ..core import hexmath as hx
from ..core.battle import ATTACKER, DEFENDER, Battle, BattleStack
from ..core.data import get_data
from . import theme as T
from .app import Scene
from .widgets import Button, Tooltip

HEX = 30
ORIGIN = (60, 70)
SIDE_COLOR = {ATTACKER: (90, 140, 240), DEFENDER: (230, 90, 80)}
ABILITY_NAMES = {
    "shield_wall": "坚盾（防御时防御 +50%）", "charge": "冲锋（每走 1 格伤害 +5%）", "no_melee_penalty": "近战无惩罚",
    "morale_aura": "士气光环（全军士气 +1）", "resurrect": "复活（每场一次，自动复活友军 100 生命）",
    "double_shot": "二连射", "blind_strike": "致盲打击（20% 致盲）", "entangle": "缠绕（目标下回合不能移动）",
    "poison_breath": "毒息（中毒 3 回合，每回合损失 10% 生命）", "mana_drain": "吸魔（每次攻击吸走对方英雄 2 法力）",
    "undead": "亡灵（不受士气影响）", "life_drain": "吸血（造成伤害恢复生命，可复活）",
    "spell_resist": "魔法抗性（法术伤害减半）", "fire_breath": "烈焰吐息（波及目标身后一格）",
}


def hex_center(c: int, r: int) -> tuple[int, int]:
    x, y = hx.hex_to_pixel(c, r, HEX)
    return int(ORIGIN[0] + x + HEX), int(ORIGIN[1] + y + HEX)


def hex_points(c: int, r: int, shrink: int = 1) -> list[tuple[float, float]]:
    cx, cy = hex_center(c, r)
    s = HEX - shrink
    return [(cx + s * math.cos(math.radians(60 * i - 30)), cy + s * math.sin(math.radians(60 * i - 30))) for i in range(6)]


def mouse_hex(pos) -> tuple[int, int] | None:
    c, r = hx.pixel_to_hex(pos[0] - ORIGIN[0] - HEX, pos[1] - ORIGIN[1] - HEX, HEX)
    return (c, r) if hx.in_bounds(c, r) else None


class BattleScene(Scene):
    def __init__(self, app, battle: Battle, human_sides: set[int]):
        super().__init__(app)
        self.b = battle
        self.human = human_sides
        self.data = get_data()
        self.hover: tuple[int, int] | None = None
        self.ai_timer = 0.0
        self.auto = False
        self.spell_mode = None          # None / "book" / Spell（选目标中）
        self.floats: list[list] = []    # [text, x, y, ttl, color]
        self.last_dmg_id = None
        self.log_seen = len(battle.log)
        px = 900
        self.btn_wait = Button((px, 560, 110, 36), "等待 (W)")
        self.btn_def = Button((px + 120, 560, 110, 36), "防御 (D)")
        self.btn_spell = Button((px + 240, 560, 110, 36), "施法 (C)")
        self.btn_auto = Button((px, 604, 110, 36), "自动 (A)")
        self.btn_flee = Button((px + 120, 604, 110, 36), "撤退 (R)")
        self.btn_speed = Button((px + 240, 604, 110, 36), "加速 (F)")
        self.btn_close = Button((T.SCREEN_W // 2 - 70, 560, 140, 40), "继续")
        self.spell_buttons: list[Button] = []

    # ---------- 工具 ----------
    def cur(self) -> BattleStack | None:
        return self.b.current

    def human_turn(self) -> bool:
        s = self.cur()
        return s is not None and s.side in self.human and not self.auto

    def add_float(self, s: str, pos: tuple[int, int], color=T.HILITE) -> None:
        cx, cy = hex_center(*pos)
        self.floats.append([s, cx, cy - 30, 1.2, color])

    def _pull_feedback(self) -> None:
        ld = self.b.last_damage
        if ld is not None and id(ld) != self.last_dmg_id:
            self.last_dmg_id = id(ld)
            t = ld["target"]
            self.add_float(f"-{ld['dmg']}" + (f" ☠{ld['killed']}" if ld["killed"] else ""), t.pos, T.RED)

    # ---------- 输入 ----------
    def handle(self, ev):
        b = self.b
        if b.over:
            if self.btn_close.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE)):
                self.done = True
            return
        if ev.type == pygame.MOUSEMOTION:
            self.hover = mouse_hex(ev.pos)
        if self.btn_auto.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_a):
            self.auto = not self.auto
            self.btn_auto.selected = self.auto
            self.spell_mode = None
        if self.btn_speed.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_f):
            self.app.ai_delay = 0.05 if self.app.ai_delay > 0.1 else 0.35
            self.btn_speed.selected = self.app.ai_delay < 0.1
        if self.btn_flee.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_r):
            side = next(iter(self.human)) if self.human else None
            if side is not None and self.app.confirm("撤退会失去全部部队，确定吗？"):
                b.surrender(side)
            return
        if not self.human_turn():
            return
        s = self.cur()
        assert s is not None
        # 法术书
        if self.spell_mode == "book":
            for btn in self.spell_buttons:
                if btn.handle(ev):
                    sp = self.data.spells[btn.key]
                    if sp.target in ("all_enemies", "all_allies"):
                        self._cast(sp, None)
                    else:
                        self.spell_mode = sp
                    return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3):
                self.spell_mode = None
            return
        if self.spell_mode is not None:       # 选目标
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3):
                self.spell_mode = None
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                h = mouse_hex(ev.pos)
                if h is not None and h in b.spell_targets(s.side, self.spell_mode):
                    self._cast(self.spell_mode, h)
            return
        if self.btn_wait.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_w):
            b.do_wait()
        elif self.btn_def.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_d):
            b.do_defend()
        elif self.btn_spell.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_c):
            self._open_book(s.side)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            h = mouse_hex(ev.pos)
            if h is None:
                return
            target = b.stack_at(h)
            if target is not None and target.side != s.side:
                self._attack(s, target, ev.pos)
            elif target is None and h in b.reachable(s) and h != s.pos:
                b.do_move(h)
        self._pull_feedback()

    def _attack(self, s: BattleStack, target: BattleStack, mouse) -> None:
        b = self.b
        if s.can_shoot() and not (b.adjacent_enemy(s) and not s.has("no_melee_penalty")):
            b.do_shoot(target)
            return
        ps = b.attack_positions(s, target)
        if not ps:
            return
        frm = s.pos if s.pos in ps else min(ps, key=lambda p: math.dist(hex_center(*p), mouse))
        if s.pos in ps and math.dist(hex_center(*s.pos), mouse) > HEX * 2.5:
            frm = min(ps, key=lambda p: math.dist(hex_center(*p), mouse))
        b.do_melee(target, frm)

    def _open_book(self, side: int) -> None:
        h = self.b.heroes[side]
        if h is None:
            self.app.message("没有英雄，无法施法。")
            return
        if self.b.spell_cast[side]:
            self.app.message("本回合已经施过法了。")
            return
        if not h.spells:
            self.app.message("英雄还不会任何法术。")
            return
        self.spell_buttons = []
        spells = sorted((self.data.spells[s] for s in h.spells), key=lambda s: (s.level, s.name))
        for i, sp in enumerate(spells):
            ok = h.mana >= sp.cost
            self.spell_buttons.append(Button((330, 110 + i * 40, 420, 34), f"{sp.name}（{sp.level} 级，{sp.cost} 法力）",
                                             16, enabled=ok, key=sp.id, tooltip=sp.desc))
        self.spell_mode = "book"

    def _cast(self, sp, target) -> None:
        s = self.cur()
        assert s is not None
        try:
            self.b.cast(s.side, sp, target)
            if target is not None:
                self.add_float(sp.name, target, T.BLUE)
        except ValueError as e:
            self.app.message(str(e))
        self.spell_mode = None

    # ---------- 更新 ----------
    def update(self, dt: float) -> None:
        for f in self.floats:
            f[3] -= dt
            f[2] -= 25 * dt
        self.floats = [f for f in self.floats if f[3] > 0]
        b = self.b
        if b.over or self.human_turn():
            return
        s = self.cur()
        if s is None:
            return
        self.ai_timer += dt
        if self.ai_timer < self.app.ai_delay:
            return
        self.ai_timer = 0.0
        cast = choose_spell(b, s.side)
        if cast:
            try:
                b.cast(s.side, cast[0], cast[1])
                if cast[1] is not None:
                    self.add_float(cast[0].name, cast[1], T.BLUE)
            except ValueError:
                pass
            if b.over:
                return
        choose_action(b)
        self._pull_feedback()

    # ---------- 绘制 ----------
    def draw(self, surf):
        surf.fill((28, 34, 30))
        b = self.b
        s = self.cur()
        reach = b.reachable(s) if (s and self.human_turn()) else {}
        targets = set()
        if self.human_turn() and self.spell_mode not in (None, "book"):
            targets = set(b.spell_targets(s.side, self.spell_mode))
        hover_from = None
        if self.hover and s and self.human_turn() and self.spell_mode is None:
            t = b.stack_at(self.hover)
            if t and t.side != s.side and not (s.can_shoot() and not b.adjacent_enemy(s)):
                ps = b.attack_positions(s, t)
                if ps:
                    m = pygame.mouse.get_pos()
                    hover_from = s.pos if (s.pos in ps and math.dist(hex_center(*s.pos), m) <= HEX * 2.5) else min(ps, key=lambda p: math.dist(hex_center(*p), m))
        # 格子
        for r in range(hx.BATTLE_H):
            for c in range(hx.BATTLE_W):
                pts = hex_points(c, r)
                col = (62, 84, 56) if (c + r) % 2 == 0 else (58, 78, 52)
                if (c, r) in b.obstacles:
                    col = (96, 78, 60)
                elif (c, r) in reach and (c, r) != s.pos:
                    col = (96, 130, 80)
                if (c, r) in targets:
                    col = (90, 90, 150)
                if hover_from == (c, r):
                    col = (170, 140, 60)
                if self.hover == (c, r):
                    col = tuple(min(255, x + 25) for x in col)
                pygame.draw.polygon(surf, col, pts)
                pygame.draw.polygon(surf, (36, 48, 36), pts, 1)
                if (c, r) in b.obstacles:
                    cx, cy = hex_center(c, r)
                    pygame.draw.circle(surf, (120, 100, 80), (cx, cy), 12)
                    pygame.draw.circle(surf, (70, 55, 45), (cx, cy), 12, 2)
        # 部队
        for st in b.stacks:
            if not st.alive:
                continue
            cx, cy = hex_center(*st.pos)
            col = SIDE_COLOR[st.side]
            if st is s:
                pygame.draw.circle(surf, T.GOLD, (cx, cy), 25, 3)
            pygame.draw.circle(surf, col, (cx, cy), 20)
            pygame.draw.circle(surf, (20, 20, 20), (cx, cy), 20, 2)
            T.text(surf, st.name[:2], (cx, cy - 2), 15, (15, 15, 15), align="center", bold=True)
            badge = pygame.Rect(0, 0, 34, 16)
            badge.center = (cx, cy + 22)
            pygame.draw.rect(surf, (15, 15, 15), badge, border_radius=3)
            T.text(surf, str(st.count), badge.center, 13, T.HILITE, align="center")
            marks = ""
            if st.blind:
                marks += "盲"
            if st.poison:
                marks += "毒"
            if st.entangled:
                marks += "缠"
            if st.defending:
                marks += "盾"
            if any(k in st.effects for k in ("haste", "mass_haste", "stoneskin", "bless", "mass_bless")):
                marks += "↑"
            if any(k in st.effects for k in ("slow", "mass_slow", "weakness", "curse")):
                marks += "↓"
            if marks:
                T.text(surf, marks, (cx + 22, cy - 22), 13, T.HILITE, align="center", shadow=True)
        for f in self.floats:
            T.text(surf, f[0], (int(f[1]), int(f[2])), 18, f[4], align="center", bold=True, shadow=True)
        self._draw_panel(surf)
        if self.spell_mode == "book":
            self._draw_book(surf)
        if b.over:
            self._draw_result(surf)
        # 悬停提示
        if self.hover and not b.over:
            t = b.stack_at(self.hover)
            if t:
                Tooltip.draw(surf, self._stack_info(t), pygame.mouse.get_pos(), 15, 360)

    def _stack_info(self, t: BattleStack) -> str:
        ct = t.type
        lines = [f"{ct.name} ×{t.count}（{'进攻方' if t.side == ATTACKER else '防守方'}）",
                 f"攻击 {t.attack_value()}  防御 {t.defense_value()}  伤害 {ct.dmg_min}-{ct.dmg_max}",
                 f"生命 {t.hp_top}/{ct.hp}  速度 {t.speed()}" + (f"  箭数 {t.shots}" if ct.ranged else "") + ("  飞行" if ct.flying else "")]
        for a in ct.abilities:
            lines.append("· " + ABILITY_NAMES.get(a, a))
        if t.effects:
            lines.append("效果：" + "，".join(f"{self.data.spells[e].name if e in self.data.spells else e}({n})" for e, n in t.effects.items()))
        return "\n".join(lines)

    def _draw_panel(self, surf):
        b = self.b
        px = 900
        T.panel(surf, pygame.Rect(px - 10, 10, 380, 540), T.PANEL)
        T.text(surf, f"第 {b.round} 回合", (px, 20), 20, T.GOLD, bold=True)
        y = 50
        for side, label in ((ATTACKER, "进攻方"), (DEFENDER, "防守方")):
            h = b.heroes[side]
            pygame.draw.rect(surf, SIDE_COLOR[side], (px, y + 4, 10, 18))
            if h:
                T.text(surf, f"{label}：{h.name}（{h.cls.name} {h.level} 级）", (px + 18, y), 17)
                T.text(surf, f"攻 {h.stat('attack')} 防 {h.stat('defense')} 魔 {h.stat('power')} 知 {h.stat('knowledge')}  法力 {h.mana}/{h.max_mana}",
                       (px + 18, y + 22), 15, T.TEXT_DIM)
            else:
                T.text(surf, f"{label}：无英雄", (px + 18, y), 17)
            T.text(surf, f"士气 {b.side_morale[side]:+d}  运气 {b.side_luck[side]:+d}", (px + 18, y + 42), 15, T.TEXT_DIM)
            y += 70
        s = b.current
        if s:
            T.text(surf, "当前行动：", (px, y), 16, T.TEXT_DIM)
            T.text_block(surf, self._stack_info(s), pygame.Rect(px, y + 22, 360, 160), 15)
        y = 370
        T.text(surf, "行动顺序：", (px, y), 16, T.TEXT_DIM)
        order = [s] if s else []
        order += [x for x in b.queue if x.alive and not x.acted]
        order += sorted([x for x in b.wait_list if x.alive], key=lambda x: x.speed())
        for i, st in enumerate(order[:9]):
            cx = px + 10 + i * 40
            pygame.draw.circle(surf, SIDE_COLOR[st.side], (cx + 10, y + 40), 15)
            T.text(surf, st.name[:1], (cx + 10, y + 40), 14, (15, 15, 15), align="center", bold=True)
        hint = ""
        if self.human_turn():
            hint = "点格子移动，点敌人攻击" if self.spell_mode is None else ("选择法术" if self.spell_mode == "book" else "点击目标施法（右键取消）")
        elif not b.over:
            hint = "电脑行动中…" if (s and s.side not in self.human) else "自动战斗中…"
        T.text(surf, hint, (px, y + 70), 15, T.HILITE)
        self.btn_wait.enabled = self.btn_def.enabled = self.btn_spell.enabled = self.human_turn() and self.spell_mode is None
        self.btn_flee.enabled = bool(self.human) and not b.over
        for btn in (self.btn_wait, self.btn_def, self.btn_spell, self.btn_auto, self.btn_flee, self.btn_speed):
            btn.draw(surf)
        # 战斗记录
        T.panel(surf, pygame.Rect(50, 600, 830, 190), T.PANEL)
        for i, line in enumerate(b.log[-8:]):
            T.text(surf, line, (62, 608 + i * 22), 15, T.TEXT if i == 7 else T.TEXT_DIM)

    def _draw_book(self, surf):
        T.dim(surf, 100)
        r = pygame.Rect(300, 60, 480, 80 + 40 * len(self.spell_buttons))
        T.panel(surf, r)
        T.text(surf, "法术书（右键 / Esc 关闭）", (r.centerx, r.y + 24), 20, T.GOLD, align="center", bold=True)
        for btn in self.spell_buttons:
            btn.draw(surf)
        m = pygame.mouse.get_pos()
        for btn in self.spell_buttons:
            if btn.rect.collidepoint(m):
                Tooltip.draw(surf, btn.tooltip, m)

    def _draw_result(self, surf):
        b = self.b
        res = b.result
        T.dim(surf, 120)
        r = pygame.Rect(0, 0, 640, 300)
        r.center = (T.SCREEN_W // 2, 400)
        T.panel(surf, r)
        won = b.winner in self.human if self.human else b.winner == ATTACKER
        title = "胜利！" if won else "战败"
        if not self.human:
            title = "进攻方胜利" if b.winner == ATTACKER else "防守方胜利"
        T.text(surf, title, (r.centerx, r.y + 36), 28, T.GOLD if won else T.RED, align="center", bold=True)
        y = r.y + 90
        for side, label in ((ATTACKER, "进攻方损失"), (DEFENDER, "防守方损失")):
            cas = "，".join(f"{k}×{v}" for k, v in res.casualties[side].items()) or "无"
            T.text(surf, f"{label}：{cas}", (r.x + 40, y), 17)
            y += 30
        T.text(surf, f"经验：进攻方 +{res.xp[0]}，防守方 +{res.xp[1]}；共 {res.rounds} 回合", (r.x + 40, y), 16, T.TEXT_DIM)
        self.btn_close.rect.center = (r.centerx, r.bottom - 40)
        self.btn_close.draw(surf)
