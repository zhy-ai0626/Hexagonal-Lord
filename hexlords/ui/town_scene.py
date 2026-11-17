"""城镇画面：建造建筑、招募兵种、驻军与英雄军队互换、酒馆雇佣、法师塔、市场。"""
from __future__ import annotations

import pygame

from ..core.data import RESOURCES, get_data
from . import theme as T
from .app import Scene
from .hero_scene import ArmyMixin, ArmyRow
from .widgets import Button, Tooltip

BUILD_ORDER = [
    "village_hall", "town_hall", "city_hall", "capitol",
    "fort", "citadel", "castle", "tavern", "market", "SPECIAL",
    "mage_guild_1", "mage_guild_2", "mage_guild_3", "mage_guild_4",
    "dwell1", "dwell2", "dwell3", "dwell4", "dwell5", "dwell6", "dwell7",
]


class TownScene(Scene, ArmyMixin):
    overlay = True

    def __init__(self, app, town):
        super().__init__(app)
        self.town = town
        self.g = app.game
        self.player = self.g.players[town.owner]
        self.data = get_data()
        self.faction = self.data.factions[town.faction]
        self.rect = pygame.Rect(20, 20, 1240, 760)
        self.hero = self.g.heroes.get(town.visiting_hero) if town.visiting_hero else None
        self.build_buttons: list[Button] = []
        bx, by = self.rect.x + 24, self.rect.y + 120
        for i, bid in enumerate(BUILD_ORDER):
            if bid == "SPECIAL":
                bid = self.faction.special_building["id"]
            r = (bx + (i % 3) * 196, by + (i // 3) * 44, 188, 38)
            self.build_buttons.append(Button(r, self._bname(bid), 15, key=bid))
        self.recruit_buttons: list[Button] = []
        rx, ry = self.rect.x + 640, self.rect.y + 60
        for tier in range(1, 8):
            self.recruit_buttons.append(Button((rx + 470, ry + 8 + (tier - 1) * 44, 100, 32), "招募", 15, key=str(tier)))
        self.rows = [ArmyRow(self.rect.x + 640, self.rect.bottom - 120, town.garrison, "驻军")]
        if self.hero:
            self.rows.append(ArmyRow(self.rect.x + 24, self.rect.bottom - 120, self.hero.army, f"{self.hero.name} 的军队"))
            self.rows[1].is_hero = True
        self._army_init()
        self.btn_close = Button((self.rect.right - 130, self.rect.y + 14, 110, 34), "关闭 (Esc)")
        self.btn_hero = Button((self.rect.right - 250, self.rect.y + 14, 110, 34), "英雄 (H)", enabled=bool(self.hero))
        self.btn_tavern = Button((rx, ry + 330, 150, 34), "酒馆：雇佣英雄", 15)
        self.btn_market = Button((rx + 160, ry + 330, 150, 34), "市场：交易", 15)
        self.btn_all = Button((rx + 320, ry + 330, 150, 34), "全部驻军给英雄", 15, enabled=bool(self.hero))

    def _bname(self, bid: str) -> str:
        b = self.data.buildings[bid]
        if b.tier:
            return self.faction.dwelling_names[b.tier - 1]
        return b.name

    # ---------- 输入 ----------
    def handle(self, ev):
        if self.btn_close.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
            self.done = True
            return
        if self.btn_hero.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_h and self.hero):
            self.app.open_hero(self.hero)
            return
        if self.btn_tavern.handle(ev):
            self._tavern()
            return
        if self.btn_market.handle(ev):
            self._market()
            return
        if self.btn_all.handle(ev) and self.hero:
            self.town.garrison.merge_into(self.hero.army)
            return
        for b in self.build_buttons:
            if b.handle(ev):
                self._build(b.key)
                return
        for b in self.recruit_buttons:
            if b.handle(ev):
                self._recruit(int(b.key))
                return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self._army_click(ev.pos, bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))

    def _build(self, bid: str) -> None:
        ok, why = self.town.can_build(bid, self.player.resources, self.data, self.player.has_capitol())
        b = self.data.buildings[bid]
        if not ok:
            self.app.message(f"{self._bname(bid)}：{why}")
            return
        cost = T.cost_text(self.data.building_cost(bid, self.town.faction))
        if self.app.confirm(f"建造 {self._bname(bid)}？\n{b.desc}\n费用：{cost}", "建造"):
            ok, why = self.g.build(self.player, self.town, bid)
            if not ok:
                self.app.message(why)

    def _recruit(self, tier: int) -> None:
        t = self.town
        ct = self.data.faction_creature(t.faction, tier)
        maxn = t.max_recruit(tier, self.player.resources, self.data)
        if maxn <= 0:
            self.app.message(f"现在招不了{ct.name}（可招 {t.available.get(tier, 0)}，每个 {T.cost_text(ct.cost)}）。")
            return
        n = self.app.number(f"招募{ct.name}（每个 {T.cost_text(ct.cost)}）", maxn)
        if n <= 0:
            return
        army = self.hero.army if self.hero and self.hero.army.can_add(ct) else t.garrison
        ok, why = self.g.recruit(self.player, t, tier, n, army)
        if not ok:
            self.app.message(why)

    def _tavern(self) -> None:
        if "tavern" not in self.town.buildings:
            self.app.message("这座城还没有酒馆。")
            return
        offers = self.g.tavern_offers(self.player)
        if not offers:
            self.app.message("酒馆里没有可雇佣的英雄。")
            return
        opts = []
        for did in offers:
            hd = self.data.hero_defs[did]
            cls = self.data.hero_classes[hd.cls]
            opts.append(f"{hd.name}（{cls.name}）— {hd.bio}")
        opts.append("算了")
        i = self.app.choice("雇佣英雄需要 2500 金币，英雄会出现在城里并带一小队 1 级兵。", opts, "酒馆")
        if i < len(offers):
            ok, why = self.g.hire_hero(self.player, self.town, offers[i])
            if not ok:
                self.app.message(why)
            else:
                self.done = True
                self.app.open_town(self.town)

    def _market(self) -> None:
        p = self.player
        if p.market_count() == 0:
            self.app.message("这座城还没有市场。")
            return
        names = [self.data.resource_names[r] for r in RESOURCES]
        i = self.app.choice("用什么资源交易？", names + ["取消"], "市场")
        if i >= len(RESOURCES):
            return
        give = RESOURCES[i]
        others = [r for r in RESOURCES if r != give]
        j = self.app.choice(f"用 {names[i]} 换什么？", [self.data.resource_names[r] for r in others] + ["取消"], "市场")
        if j >= len(others):
            return
        get = others[j]
        if get == "gold":
            rate = p.gold_per_resource(give)
            maxn = p.resources.get(give, 0)
            n = self.app.number(f"1 {names[i]} = {rate} 金币，卖多少？", maxn)
            if n > 0:
                self.g.trade(p, give, get, n)
        else:
            rate = p.trade_rate(give, get)
            maxn = p.resources.get(give, 0) // max(1, rate)
            n = self.app.number(f"{rate} {names[i]} = 1 {self.data.resource_names[get]}，买多少 {self.data.resource_names[get]}？", maxn)
            if n > 0:
                self.g.trade(p, give, get, n)

    # ---------- 绘制 ----------
    def draw(self, surf):
        T.dim(surf, 150)
        T.panel(surf, self.rect)
        t, d, p = self.town, self.data, self.player
        x, y = self.rect.x + 24, self.rect.y + 16
        T.text(surf, f"{t.name}", (x, y), 26, T.GOLD, bold=True)
        T.text(surf, f"{self.faction.name} · {t.hall_name(d)} · 每天 +{t.income(d)} 金 · 城防 {['无', '要塞', '城堡', '王堡'][t.fort_level(d)]} · 法师塔 {t.guild_level(d)} 级",
               (x + 150, y + 8), 16, T.TEXT_DIM)
        T.text(surf, "  ".join(f"{d.resource_names[r]} {p.resources.get(r, 0)}" for r in RESOURCES), (x, y + 44), 16, T.HILITE)
        T.text(surf, "建筑（每天只能建一座）" + ("  — 今天已建造" if t.built_today else ""), (x, y + 76), 17, T.GOLD, bold=True)
        for b in self.build_buttons:
            bid = b.key
            if t.has(bid, d):
                b.color = (50, 90, 60)
                b.enabled = True
            else:
                ok, _ = t.can_build(bid, p.resources, d, p.has_capitol())
                b.color = T.PANEL_LIGHT if ok else (45, 43, 50)
                b.enabled = True
            b.draw(surf)
            if t.has(bid, d):
                T.text(surf, "✓", (b.rect.right - 14, b.rect.centery), 14, T.GREEN, align="center")
        # 招募
        rx, ry = self.rect.x + 640, self.rect.y + 60
        T.text(surf, "招募（周产量会累积）", (rx, ry - 24), 17, T.GOLD, bold=True)
        for tier in range(1, 8):
            yy = ry + 8 + (tier - 1) * 44
            ct = d.faction_creature(t.faction, tier)
            btn = self.recruit_buttons[tier - 1]
            built = t.dwelling_built(tier)
            btn.enabled = built
            col = self.faction.color if built else (70, 66, 78)
            pygame.draw.circle(surf, col, (rx + 18, yy + 16), 15)
            T.text(surf, ct.name[:2], (rx + 18, yy + 16), 12, (15, 15, 15), align="center", bold=True)
            if built:
                T.text(surf, f"{ct.name}  可招 {t.available.get(tier, 0)}  （+{t.growth(tier, d)}/周）", (rx + 42, yy), 15)
                T.text(surf, f"每个 {T.cost_text(ct.cost)}", (rx + 42, yy + 18), 13, T.TEXT_DIM)
            else:
                T.text(surf, f"{ct.name}（未建 {self.faction.dwelling_names[tier - 1]}）", (rx + 42, yy + 8), 15, T.TEXT_DIM)
            btn.draw(surf)
        for b in (self.btn_tavern, self.btn_market, self.btn_all):
            b.draw(surf)
        # 法师塔
        gy = ry + 380
        T.text(surf, "法师塔法术", (rx, gy), 16, T.GOLD, bold=True)
        if t.guild_spells:
            lines = []
            for lvl in sorted(t.guild_spells):
                lines.append(f"{lvl} 级：" + "、".join(d.spells[s].name for s in t.guild_spells[lvl]))
            for i, l in enumerate(lines):
                T.text(surf, l, (rx, gy + 22 + i * 20), 14, T.TEXT_DIM)
        else:
            T.text(surf, "（未建法师塔）", (rx, gy + 22), 14, T.TEXT_DIM)
        # 军队
        for i, row in enumerate(self.rows):
            row.draw(surf, self.sel[1] if (self.sel and self.sel[0] == i) else None, color=self.faction.color)
        if not self.hero:
            T.text(surf, "（没有英雄在城里；招募的兵进入驻军）", (self.rect.x + 24, self.rect.bottom - 90), 15, T.TEXT_DIM)
        self.btn_close.draw(surf)
        self.btn_hero.draw(surf)
        # 提示
        m = pygame.mouse.get_pos()
        for b in self.build_buttons:
            if b.rect.collidepoint(m):
                bd = d.buildings[b.key]
                ok, why = t.can_build(b.key, p.resources, d, p.has_capitol())
                state = "已建造" if t.has(b.key, d) else ("可以建造" if ok else why)
                req = "、".join(self._bname(r) for r in bd.requires) or "无"
                Tooltip.draw(surf, f"{self._bname(b.key)}\n{bd.desc}\n费用：{T.cost_text(d.building_cost(b.key, t.faction))}\n前置：{req}\n状态：{state}", m)
        for row in self.rows:
            row.tooltip(surf, m)
