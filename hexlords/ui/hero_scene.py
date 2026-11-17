"""英雄画面、两个英雄间的军队交换画面，以及共用的"军队槽位行"控件。"""
from __future__ import annotations

import pygame

from ..core.army import Army, split_stack, transfer_stack
from ..core.data import get_data
from ..core.hero import PRIMARY, PRIMARY_NAMES, xp_for_level
from . import theme as T
from .app import Scene
from .widgets import Button, Tooltip


class ArmyRow:
    """一行 7 个槽位。点一个槽位选中，再点另一个槽位：移动 / 合并 / 交换；按住 Shift 点目标则拆分。"""
    SLOT = 78

    def __init__(self, x: int, y: int, army: Army, label: str = ""):
        self.x, self.y, self.army, self.label = x, y, army, label
        self.rects = [pygame.Rect(x + i * (self.SLOT + 6), y, self.SLOT, self.SLOT) for i in range(7)]

    def hit(self, pos) -> int | None:
        for i, r in enumerate(self.rects):
            if r.collidepoint(pos):
                return i
        return None

    def draw(self, surf, selected: int | None = None, color=None):
        if self.label:
            T.text(surf, self.label, (self.x, self.y - 22), 16, T.TEXT_DIM)
        for i, r in enumerate(self.rects):
            T.panel(surf, r, (36, 34, 44), T.GOLD if selected == i else (90, 84, 100), radius=4)
            st = self.army.slots[i]
            if st and st.count > 0:
                col = color or (150, 130, 180)
                pygame.draw.circle(surf, col, (r.centerx, r.centery - 8), 22)
                pygame.draw.circle(surf, (20, 20, 20), (r.centerx, r.centery - 8), 22, 2)
                T.text(surf, st.type.name[:2], (r.centerx, r.centery - 9), 15, (15, 15, 15), align="center", bold=True)
                T.text(surf, str(st.count), (r.centerx, r.bottom - 12), 15, T.HILITE, align="center", bold=True)

    def tooltip(self, surf, pos) -> None:
        i = self.hit(pos)
        if i is None:
            return
        st = self.army.slots[i]
        if st and st.count > 0:
            ct = st.type
            Tooltip.draw(surf, f"{ct.name} ×{st.count}（{ct.tier} 级）\n攻 {ct.attack} 防 {ct.defense} 伤害 {ct.dmg_min}-{ct.dmg_max}\n"
                               f"生命 {ct.hp} 速度 {ct.speed}" + (f" 箭数 {ct.shots}" if ct.ranged else "") + (" 飞行" if ct.flying else "")
                               + "\n（点选后点另一槽位移动，Shift+点击拆分）", pos)


class ArmyMixin:
    """处理多行军队槽位之间的点选、移动、拆分。子类提供 self.rows: list[ArmyRow]。"""
    rows: list[ArmyRow]

    def _army_init(self):
        self.sel: tuple[int, int] | None = None     # (行号, 槽号)

    def _army_click(self, pos, shift: bool) -> bool:
        for ri, row in enumerate(self.rows):
            i = row.hit(pos)
            if i is None:
                continue
            if self.sel is None:
                if row.army.slots[i] and row.army.slots[i].count > 0:
                    self.sel = (ri, i)
                return True
            sr, si = self.sel
            src = self.rows[sr].army
            if (sr, si) == (ri, i):
                self.sel = None
                return True
            if shift and src.slots[si] and src.slots[si].count > 1:
                dst = row.army.slots[i]
                if dst is None or dst.type.id == src.slots[si].type.id:
                    n = self.app.number(f"拆分多少个{src.slots[si].type.name}到目标槽位？", src.slots[si].count - 1, src.slots[si].count // 2)
                    if n > 0:
                        split_stack(src, si, row.army, i, n)
            else:
                if not self._can_move(sr, si, ri, i):
                    self.app.message("英雄至少要留一支部队。")
                else:
                    transfer_stack(src, si, row.army, i)
            self.sel = None
            return True
        return False

    def _can_move(self, sr, si, ri, i) -> bool:
        """英雄不能把最后一支部队全部移走。"""
        src_row = self.rows[sr]
        if sr == ri or not getattr(src_row, "is_hero", False):
            return True
        army = src_row.army
        dst = self.rows[ri].army.slots[i]
        if dst is not None and dst.count > 0 and dst.type.id != army.slots[si].type.id:
            return True        # 交换，不会变空
        return sum(1 for s in army.stacks()) > 1


class HeroScene(Scene, ArmyMixin):
    overlay = True

    def __init__(self, app, hero):
        super().__init__(app)
        self.h = hero
        self.data = get_data()
        self.rect = pygame.Rect(60, 40, 1160, 720)
        self.rows = [ArmyRow(self.rect.x + 40, self.rect.bottom - 120, hero.army, "军队")]
        self.rows[0].is_hero = True
        self._army_init()
        self.close = Button((self.rect.right - 140, self.rect.bottom - 50, 110, 34), "关闭 (Esc)")
        self.art_rects: list[tuple[pygame.Rect, str, object]] = []

    def handle(self, ev):
        if self.close.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_h)):
            self.done = True
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
            if self._army_click(ev.pos, bool(shift)):
                return
            for r, kind, art in self.art_rects:
                if r.collidepoint(ev.pos):
                    if kind == "equipped":
                        self.h.unequip(art.slot)
                    else:
                        self.h.backpack.remove(art)
                        if art.slot in self.h.equipment:
                            self.h.unequip(art.slot)
                        self.h.equip(art)
                    return

    def draw(self, surf):
        T.dim(surf, 120)
        T.panel(surf, self.rect)
        h, d = self.h, self.data
        x, y = self.rect.x + 30, self.rect.y + 20
        T.text(surf, f"{h.name}", (x, y), 26, T.GOLD, bold=True)
        T.text(surf, f"{h.cls.name} · {h.level} 级 · {d.factions[h.faction].name}", (x + 160, y + 6), 18, T.TEXT_DIM)
        nxt = xp_for_level(h.level + 1)
        T.text(surf, f"经验 {h.xp} / {nxt}", (x + 420, y + 6), 16, T.TEXT_DIM)
        bio = d.hero_defs[h.def_id].bio
        T.text(surf, bio, (x, y + 40), 15, T.TEXT_DIM)
        # 四维
        y += 70
        for i, p in enumerate(PRIMARY):
            base, total = getattr(h, p), h.stat(p)
            T.panel(surf, pygame.Rect(x + i * 130, y, 120, 54), T.PANEL_LIGHT, None)
            T.text(surf, PRIMARY_NAMES[p], (x + i * 130 + 60, y + 14), 15, T.TEXT_DIM, align="center")
            T.text(surf, f"{total}" + (f" ({base}+{total - base})" if total != base else ""), (x + i * 130 + 60, y + 36), 18, align="center", bold=True)
        T.text(surf, f"法力 {h.mana}/{h.max_mana}   移动力 {h.move_points}/{h.max_move}   士气 {h.morale():+d}   运气 {h.luck():+d}",
               (x, y + 64), 16)
        spec = h.specialty
        if spec.startswith("creature:"):
            spec_t = f"专精：{d.creatures[spec[9:]].name}（攻防速 +1）"
        elif spec.startswith("gold:"):
            spec_t = f"专精：每天 +{spec[5:]} 金币"
        else:
            spec_t = f"专精：{d.skills[spec[6:]].name}（效果 ×1.5）"
        T.text(surf, spec_t, (x, y + 88), 16, T.GREEN)
        # 副技能
        y += 120
        T.text(surf, "副技能", (x, y), 17, T.GOLD, bold=True)
        for i, (sid, lvl) in enumerate(sorted(h.skills.items())):
            sk = d.skills[sid]
            cx, cy = x + (i % 4) * 130, y + 26 + (i // 4) * 44
            T.panel(surf, pygame.Rect(cx, cy, 120, 38), T.PANEL_LIGHT, None)
            T.text(surf, f"{d.skill_level_names[lvl - 1]}{sk.name}", (cx + 60, cy + 11), 14, align="center")
            T.text(surf, sk.describe(lvl), (cx + 60, cy + 28), 12, T.TEXT_DIM, align="center")
        # 法术
        sx, sy = self.rect.x + 580, self.rect.y + 20
        T.text(surf, f"法术书（最高可学 {h.max_spell_level()} 级）", (sx, sy), 17, T.GOLD, bold=True)
        spells = sorted((d.spells[s] for s in h.spells), key=lambda s: (s.level, s.name))
        for i, sp in enumerate(spells):
            T.text(surf, f"{sp.level}级 {sp.name}（{sp.cost}）", (sx + (i % 2) * 260, sy + 26 + (i // 2) * 22), 15)
        if not spells:
            T.text(surf, "（还没有法术）", (sx, sy + 26), 15, T.TEXT_DIM)
        # 宝物
        ay = sy + 230
        T.text(surf, "装备（点击卸下）", (sx, ay), 17, T.GOLD, bold=True)
        self.art_rects = []
        for i, slot in enumerate(d.slots):
            r = pygame.Rect(sx + (i % 4) * 135, ay + 26 + (i // 4) * 50, 125, 44)
            art = h.equipment.get(slot)
            T.panel(surf, r, T.PANEL_LIGHT if art else (36, 34, 44), T.GOLD if art else (80, 75, 85), radius=4)
            T.text(surf, d.slot_names[slot], (r.x + 6, r.y + 4), 12, T.TEXT_DIM)
            if art:
                T.text(surf, art.name, (r.x + 6, r.y + 22), 14, T.HILITE)
                self.art_rects.append((r, "equipped", art))
        by = ay + 140
        T.text(surf, "背包（点击装备）", (sx, by), 17, T.GOLD, bold=True)
        for i, art in enumerate(h.backpack[:12]):
            r = pygame.Rect(sx + (i % 4) * 135, by + 26 + (i // 4) * 40, 125, 34)
            T.panel(surf, r, T.PANEL_LIGHT, (80, 75, 85), radius=4)
            T.text(surf, art.name, (r.centerx, r.centery), 14, align="center")
            self.art_rects.append((r, "backpack", art))
        self.rows[0].draw(surf, self.sel[1] if self.sel else None, color=d.factions[h.faction].color)
        self.close.draw(surf)
        m = pygame.mouse.get_pos()
        self.rows[0].tooltip(surf, m)
        for r, _, art in self.art_rects:
            if r.collidepoint(m):
                Tooltip.draw(surf, f"{art.name}（{d.slot_names[art.slot]}）\n{art.desc}", m)


class ExchangeScene(Scene, ArmyMixin):
    """两个己方英雄相遇：互换部队和背包宝物。"""
    overlay = True

    def __init__(self, app, a, b):
        super().__init__(app)
        self.a, self.b = a, b
        self.data = get_data()
        self.rect = pygame.Rect(140, 150, 1000, 500)
        self.rows = [ArmyRow(self.rect.x + 60, self.rect.y + 120, a.army, f"{a.name} 的军队"),
                     ArmyRow(self.rect.x + 60, self.rect.y + 300, b.army, f"{b.name} 的军队")]
        for r in self.rows:
            r.is_hero = True
        self._army_init()
        self.close = Button((self.rect.right - 140, self.rect.bottom - 50, 110, 34), "关闭 (Esc)")
        self.give_ab = Button((self.rect.x + 700, self.rect.y + 130, 240, 32), f"背包宝物 → {b.name}", 15)
        self.give_ba = Button((self.rect.x + 700, self.rect.y + 310, 240, 32), f"背包宝物 → {a.name}", 15)
        self.open_a = Button((self.rect.x + 700, self.rect.y + 170, 240, 32), f"查看 {a.name}", 15)
        self.open_b = Button((self.rect.x + 700, self.rect.y + 350, 240, 32), f"查看 {b.name}", 15)

    def handle(self, ev):
        if self.close.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
            self.done = True
        elif self.give_ab.handle(ev):
            self.b.backpack.extend(self.a.backpack)
            self.a.backpack.clear()
        elif self.give_ba.handle(ev):
            self.a.backpack.extend(self.b.backpack)
            self.b.backpack.clear()
        elif self.open_a.handle(ev):
            self.app.open_hero(self.a)
        elif self.open_b.handle(ev):
            self.app.open_hero(self.b)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self._army_click(ev.pos, bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))

    def draw(self, surf):
        T.dim(surf, 120)
        T.panel(surf, self.rect)
        T.text(surf, "军队交换", (self.rect.centerx, self.rect.y + 30), 24, T.GOLD, align="center", bold=True)
        T.text(surf, "点一支部队再点目标槽位：移动 / 合并 / 交换；Shift+点击拆分。每个英雄至少留一支部队。",
               (self.rect.centerx, self.rect.y + 62), 15, T.TEXT_DIM, align="center")
        for i, (row, h) in enumerate(zip(self.rows, (self.a, self.b))):
            row.draw(surf, self.sel[1] if (self.sel and self.sel[0] == i) else None, color=self.data.factions[h.faction].color)
            T.text(surf, f"{h.cls.name} {h.level} 级 · 攻 {h.stat('attack')} 防 {h.stat('defense')} · 背包 {len(h.backpack)} 件",
                   (row.x, row.y + 90), 14, T.TEXT_DIM)
        for b in (self.close, self.give_ab, self.give_ba, self.open_a, self.open_b):
            b.draw(surf)
        m = pygame.mouse.get_pos()
        for row in self.rows:
            row.tooltip(surf, m)
