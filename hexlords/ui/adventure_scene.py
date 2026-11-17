"""冒险地图画面：地图、英雄移动、右侧面板（资源、英雄、城镇、小地图）、结束回合与电脑回合。"""
from __future__ import annotations

import os

import pygame

from ..ai.adventure_ai import AdventureAI
from ..core.data import RESOURCES, get_data
from ..core.game import Game, GameOver
from ..core.hero import Hero
from ..core.world import MINE_NAME, ObjKind, Terrain
from . import theme as T
from .app import Scene
from .widgets import Button, Tooltip

TILE = 32
VIEW_W, VIEW_H = 960, 800
SAVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "saves", "quick.sav")


class AdventureScene(Scene):
    def __init__(self, app, game: Game):
        super().__init__(app)
        self.g = game
        self.data = get_data()
        self.cam = [0.0, 0.0]            # 左上角的格坐标
        self.sel: Hero | None = None
        self.path: list | None = None    # [(x, y, cost)...]
        self.path_goal = None
        self.moving = False
        self.move_timer = 0.0
        self.hover_tile = None
        self.ai_running = False
        px = VIEW_W + 12
        self.btn_end = Button((px, 740, 145, 40), "结束回合 (E)", 17, color=(90, 70, 40))
        self.btn_next = Button((px + 155, 740, 145, 40), "下一英雄 (N)", 16)
        self.btn_hero = Button((px, 696, 95, 36), "英雄 (H)", 15)
        self.btn_town = Button((px + 102, 696, 95, 36), "城镇 (T)", 15)
        self.btn_save = Button((px + 204, 696, 46, 36), "存", 15)
        self.btn_load = Button((px + 254, 696, 46, 36), "读", 15)
        self.hero_rects: list[tuple[pygame.Rect, Hero]] = []
        self.town_rects: list[tuple[pygame.Rect, object]] = []
        self.minimap = pygame.Rect(px, 470, 300, 220)
        self.select_first_hero()
        self.center_on_selected()

    # ---------- 辅助 ----------
    @property
    def me(self):
        return self.g.players[self.app.human]

    def select_first_hero(self) -> None:
        self.sel = self.me.heroes[0] if self.me.heroes else None
        self.path = None

    def center_on(self, x: int, y: int) -> None:
        self.cam[0] = x - VIEW_W / TILE / 2 + 0.5
        self.cam[1] = y - VIEW_H / TILE / 2 + 0.5
        self._clamp_cam()

    def center_on_selected(self) -> None:
        if self.sel:
            self.center_on(self.sel.x, self.sel.y)
        elif self.me.towns:
            self.center_on(self.me.towns[0].x, self.me.towns[0].y)

    def _clamp_cam(self) -> None:
        w, h = self.g.world.w, self.g.world.h
        self.cam[0] = max(0, min(w - VIEW_W / TILE, self.cam[0]))
        self.cam[1] = max(0, min(h - VIEW_H / TILE, self.cam[1]))

    def tile_at(self, pos) -> tuple[int, int] | None:
        if pos[0] >= VIEW_W:
            return None
        x = int(pos[0] / TILE + self.cam[0])
        y = int(pos[1] / TILE + self.cam[1])
        return (x, y) if self.g.world.in_bounds(x, y) else None

    def screen_pos(self, x: int, y: int) -> tuple[int, int]:
        return int((x - self.cam[0]) * TILE), int((y - self.cam[1]) * TILE)

    # ---------- 输入 ----------
    def handle(self, ev):
        if self.moving or self.ai_running:
            return
        if ev.type == pygame.MOUSEMOTION:
            self.hover_tile = self.tile_at(ev.pos)
        if self.btn_end.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_e):
            self.end_turn()
            return
        if self.btn_next.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_n):
            self.next_hero()
            return
        if self.btn_hero.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_h):
            if self.sel:
                self.app.open_hero(self.sel)
            return
        if self.btn_town.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_t):
            self.open_town_of_selected()
            return
        if self.btn_save.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_F5):
            os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
            self.g.save(SAVE_PATH)
            self.app.message("已存档到 saves/quick.sav")
            return
        if self.btn_load.handle(ev) or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_F9):
            self.load_game()
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                if self.app.confirm("返回主菜单？（未存档的进度会丢失）"):
                    self.done = True
            elif ev.key == pygame.K_SPACE and self.sel:
                self.center_on_selected()
            return
        if ev.type == pygame.MOUSEBUTTONDOWN:
            for r, h in self.hero_rects:
                if r.collidepoint(ev.pos):
                    self.sel, self.path = h, None
                    self.center_on_selected()
                    return
            for r, t in self.town_rects:
                if r.collidepoint(ev.pos):
                    if ev.button == 1:
                        self.app.open_town(t)
                    else:
                        self.center_on(t.x, t.y)
                    return
            if self.minimap.collidepoint(ev.pos):
                w, h = self.g.world.w, self.g.world.h
                self.center_on(int((ev.pos[0] - self.minimap.x) / self.minimap.w * w), int((ev.pos[1] - self.minimap.y) / self.minimap.h * h))
                return
            tile = self.tile_at(ev.pos)
            if tile is None:
                return
            if ev.button == 3:
                self.app.message(self.describe_tile(tile), "地图信息")
                return
            if ev.button != 1:
                return
            hero = self.g.hero_at(*tile)
            if hero and hero.owner == self.me.idx and hero is not self.sel:
                self.sel, self.path = hero, None
                return
            if hero and hero is self.sel:
                t = self.g.town_of_hero(hero)
                if t:
                    self.app.open_town(t)
                else:
                    self.app.open_hero(hero)
                return
            if self.sel is None:
                return
            if self.path is not None and self.path_goal == tile:
                self.moving = True
                self.move_timer = 0
                return
            if tile not in self.me.explored:
                self.path = None
                return
            p = self.g.path_for(self.sel, tile)
            self.path, self.path_goal = (p if p else None), tile

    def describe_tile(self, tile) -> str:
        x, y = tile
        w = self.g.world
        if tile not in self.me.explored:
            return "未探索的区域。"
        parts = [f"({x}, {y}) {['草地', '荒原', '沼泽', '雪地', '道路', '树林', '山脉', '水域'][w.terrain(x, y)]}"]
        h = self.g.hero_at(x, y)
        if h:
            p = self.g.players[h.owner]
            parts.append(f"英雄 {h.name}（{p.name}方，{h.cls.name} {h.level} 级）：{h.army.describe() if h.owner == self.me.idx else '军队约 ' + self._vague(h.army.total_count())}")
        obj = w.object_at(x, y)
        if obj:
            d = self.data
            k = obj.kind
            if k == ObjKind.TOWN:
                t = self.g.towns[obj.data["town_id"]]
                owner = self.g.players[t.owner].name + "方" if t.owner is not None else "无主"
                parts.append(f"城镇 {t.name}（{d.factions[t.faction].name}，{owner}）")
            elif k == ObjKind.MINE:
                owner = self.g.players[obj.owner].name + "方" if obj.owner is not None else "无主"
                parts.append(f"{MINE_NAME[obj.data['resource']]}（{owner}），每天 +{obj.data['amount']}")
            elif k == ObjKind.RESOURCE:
                parts.append(f"{d.resource_names[obj.data['resource']]} 资源堆")
            elif k == ObjKind.ARTIFACT:
                parts.append("宝物")
            elif k == ObjKind.DWELLING:
                parts.append(f"野外兵营：{d.creatures[obj.data['creature']].name}（可招 {obj.data['available']}）")
            elif k == ObjKind.SHRINE:
                parts.append(f"法术神殿：{d.spells[obj.data['spell']].name}")
            elif k == ObjKind.MONSTER:
                parts.append("野怪")
            else:
                parts.append(obj.display_name())
            if obj.guard is not None and not obj.guard.is_empty():
                parts.append("守卫：" + "，".join(f"{s.type.name}（约 {self._vague(s.count)}）" for s in obj.guard.stacks()))
        return "\n".join(parts)

    @staticmethod
    def _vague(n: int) -> str:
        for lim, s in ((5, "几个"), (10, "不到十个"), (20, "十几个"), (50, "几十个"), (100, "近百"), (250, "上百"), (500, "几百")):
            if n < lim:
                return s
        return "成群"

    def next_hero(self) -> None:
        hs = [h for h in self.me.heroes if h.move_points > 0]
        if not hs:
            return
        if self.sel in hs:
            i = (hs.index(self.sel) + 1) % len(hs)
            self.sel = hs[i]
        else:
            self.sel = hs[0]
        self.path = None
        self.center_on_selected()

    def open_town_of_selected(self) -> None:
        if self.sel:
            t = self.g.town_of_hero(self.sel)
            if t and t.owner == self.me.idx:
                self.app.open_town(t)
                return
        if self.me.towns:
            self.app.open_town(self.me.towns[0])

    def load_game(self) -> None:
        if not os.path.exists(SAVE_PATH):
            self.app.message("没有存档。")
            return
        if not self.app.confirm("读取存档？当前进度会丢失。"):
            return
        self.g = Game.load(SAVE_PATH)
        self.app.game = self.g
        self.select_first_hero()
        self.center_on_selected()

    # ---------- 回合 ----------
    def end_turn(self) -> None:
        if any(h.move_points > 0 for h in self.me.heroes):
            if not self.app.confirm("还有英雄没走完，确定结束回合？"):
                return
        self.path = None
        events = self.g.end_turn()
        self.app.resolve_events(events)
        self.run_ai_turns()

    def run_ai_turns(self) -> None:
        while self.app.running and self.g.winner is None and self.me.alive and self.g.current_player().idx != self.app.human:
            p = self.g.current_player()
            self.ai_running = True
            self.draw(self.app.screen)
            pygame.display.flip()
            pygame.event.pump()
            ai = AdventureAI(self.g, p, self.app.run_battle)
            ai.play_turn()
            self.ai_running = False
            evs = self.g.end_turn()
            self.app.resolve_events(evs)
        if self.g.winner is not None:
            self.done = True
            return
        if not self.me.alive:
            self.app.message("你已经被消灭了。", "游戏结束")
            self.done = True
            return
        if not self.me.heroes and self.me.towns:
            self.app.message(f"你没有英雄了！{7 - self.me.days_without_town} 天内在酒馆雇佣新英雄，否则会出局。", "警告")
        self.select_first_hero()
        self.center_on_selected()

    # ---------- 更新 ----------
    def update(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        spd = 14 * dt
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.cam[0] -= spd
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.cam[0] += spd
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            self.cam[1] -= spd
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            self.cam[1] += spd
        self._clamp_cam()
        if self.moving and self.sel and self.path:
            self.move_timer += dt
            if self.move_timer >= 0.09:
                self.move_timer = 0
                x, y, _ = self.path[0]
                moved, events = self.g.step_hero(self.sel, (x, y))
                if moved:
                    self.path.pop(0)
                    if abs(self.sel.x - (self.cam[0] + VIEW_W / TILE / 2)) > 10 or abs(self.sel.y - (self.cam[1] + VIEW_H / TILE / 2)) > 8:
                        self.center_on_selected()
                if events:
                    self.moving = False
                    self.path = None
                    hero = self.sel
                    self.app.resolve_events(events)
                    if hero not in self.me.heroes:
                        self.select_first_hero()
                    if self.g.winner is not None or not self.me.alive:
                        self.done = True
                elif not moved or not self.path:
                    self.moving = False
                    self.path = None

    # ---------- 绘制 ----------
    def draw(self, surf):
        surf.fill(T.BG)
        self._draw_map(surf)
        self._draw_panel(surf)
        if self.ai_running:
            T.dim(surf, 80)
            T.text(surf, f"{self.g.current_player().name}方（电脑）行动中…", (VIEW_W // 2, VIEW_H // 2), 30, T.HILITE, align="center", bold=True, shadow=True)

    def _draw_map(self, surf):
        w = self.g.world
        explored = self.me.explored
        x0, y0 = int(self.cam[0]), int(self.cam[1])
        cols, rows = VIEW_W // TILE + 2, VIEW_H // TILE + 2
        for ty in range(y0, min(w.h, y0 + rows)):
            for tx in range(x0, min(w.w, x0 + cols)):
                sx, sy = self.screen_pos(tx, ty)
                r = pygame.Rect(sx, sy, TILE, TILE)
                if (tx, ty) not in explored:
                    pygame.draw.rect(surf, (12, 12, 16), r)
                    continue
                t = w.terrain(tx, ty)
                col = T.TERRAIN_COLORS[int(t)]
                if (tx + ty) % 2:
                    col = tuple(max(0, c - 6) for c in col)
                pygame.draw.rect(surf, col, r)
                if t == Terrain.FOREST:
                    pygame.draw.polygon(surf, (30, 70, 35), [(sx + 16, sy + 4), (sx + 5, sy + 27), (sx + 27, sy + 27)])
                elif t == Terrain.MOUNTAIN:
                    pygame.draw.polygon(surf, (80, 72, 72), [(sx + 16, sy + 3), (sx + 3, sy + 29), (sx + 29, sy + 29)])
                    pygame.draw.polygon(surf, (200, 200, 210), [(sx + 16, sy + 3), (sx + 11, sy + 13), (sx + 21, sy + 13)])
                elif t == Terrain.WATER:
                    pygame.draw.line(surf, (90, 130, 210), (sx + 6, sy + 12), (sx + 14, sy + 12), 2)
                    pygame.draw.line(surf, (90, 130, 210), (sx + 16, sy + 22), (sx + 26, sy + 22), 2)
        # 物件
        for obj in w.objects.values():
            if obj.pos not in explored:
                continue
            sx, sy = self.screen_pos(obj.x, obj.y)
            if sx < -TILE or sy < -TILE or sx > VIEW_W or sy > VIEW_H:
                continue
            self._draw_object(surf, obj, sx, sy)
        # 路径
        if self.path and self.sel:
            mp = self.sel.move_points
            for (x, y, cost) in self.path:
                sx, sy = self.screen_pos(x, y)
                col = T.GREEN if cost <= mp else T.RED
                pygame.draw.circle(surf, col, (sx + TILE // 2, sy + TILE // 2), 5)
            x, y, cost = self.path[-1]
            sx, sy = self.screen_pos(x, y)
            pygame.draw.rect(surf, T.HILITE, (sx, sy, TILE, TILE), 2)
            days = 1 + max(0, (cost - mp + self.sel.max_move - 1) // max(1, self.sel.max_move)) if cost > mp else 1
            T.text(surf, f"{cost}（{days} 天）", (sx + TILE // 2, sy - 10), 13, T.HILITE, align="center", shadow=True)
        # 英雄
        for h in self.g.heroes.values():
            if (h.x, h.y) not in explored:
                continue
            sx, sy = self.screen_pos(h.x, h.y)
            if sx < -TILE or sy < -TILE or sx > VIEW_W or sy > VIEW_H:
                continue
            col = self.g.players[h.owner].color
            c = (sx + TILE // 2, sy + TILE // 2)
            if h is self.sel:
                pygame.draw.circle(surf, T.GOLD, c, 17, 3)
            pygame.draw.circle(surf, col, c, 13)
            pygame.draw.circle(surf, (20, 20, 20), c, 13, 2)
            T.text(surf, h.name[0], c, 14, (15, 15, 15), align="center", bold=True)
        # 悬停
        if self.hover_tile and not self.moving:
            sx, sy = self.screen_pos(*self.hover_tile)
            pygame.draw.rect(surf, (255, 255, 255), (sx, sy, TILE, TILE), 1)
            if self.hover_tile in explored:
                obj = w.object_at(*self.hover_tile)
                h = self.g.hero_at(*self.hover_tile)
                if obj or h:
                    Tooltip.draw(surf, self.describe_tile(self.hover_tile), pygame.mouse.get_pos(), 14, 340)
        pygame.draw.rect(surf, T.BORDER, (0, 0, VIEW_W, VIEW_H), 2)

    def _draw_object(self, surf, obj, sx, sy):
        k = obj.kind
        cx, cy = sx + TILE // 2, sy + TILE // 2
        if k == ObjKind.TOWN:
            t = self.g.towns[obj.data["town_id"]]
            col = self.data.factions[t.faction].color
            pygame.draw.rect(surf, col, (sx + 3, sy + 6, TILE - 6, TILE - 9), border_radius=3)
            pygame.draw.rect(surf, (20, 20, 20), (sx + 3, sy + 6, TILE - 6, TILE - 9), 2, border_radius=3)
            pygame.draw.polygon(surf, (40, 40, 40), [(sx + 6, sy + 8), (cx, sy), (sx + TILE - 6, sy + 8)])
            T.text(surf, "城", (cx, cy + 2), 15, (15, 15, 15), align="center", bold=True)
            if t.owner is not None:
                pygame.draw.rect(surf, self.g.players[t.owner].color, (sx + TILE - 11, sy + 1, 9, 9))
                pygame.draw.rect(surf, (0, 0, 0), (sx + TILE - 11, sy + 1, 9, 9), 1)
        elif k == ObjKind.MINE:
            col = T.RESOURCE_COLORS[obj.data["resource"]]
            pygame.draw.polygon(surf, col, [(cx, sy + 4), (sx + 4, sy + TILE - 4), (sx + TILE - 4, sy + TILE - 4)])
            pygame.draw.polygon(surf, (20, 20, 20), [(cx, sy + 4), (sx + 4, sy + TILE - 4), (sx + TILE - 4, sy + TILE - 4)], 2)
            if obj.owner is not None:
                pygame.draw.rect(surf, self.g.players[obj.owner].color, (sx + TILE - 11, sy + 1, 9, 9))
                pygame.draw.rect(surf, (0, 0, 0), (sx + TILE - 11, sy + 1, 9, 9), 1)
        elif k == ObjKind.RESOURCE:
            col = T.RESOURCE_COLORS[obj.data["resource"]]
            pygame.draw.circle(surf, col, (cx, cy), 8)
            pygame.draw.circle(surf, (20, 20, 20), (cx, cy), 8, 2)
        elif k == ObjKind.CHEST:
            pygame.draw.rect(surf, (230, 190, 60), (sx + 7, sy + 10, 18, 13), border_radius=2)
            pygame.draw.rect(surf, (90, 60, 20), (sx + 7, sy + 10, 18, 13), 2, border_radius=2)
        elif k == ObjKind.MONSTER:
            T.icon_circle(surf, (cx, cy), 12, (200, 60, 60), "怪", 13)
        elif k == ObjKind.ARTIFACT:
            pygame.draw.polygon(surf, (250, 230, 120), [(cx, sy + 4), (sx + TILE - 5, cy), (cx, sy + TILE - 4), (sx + 5, cy)])
            pygame.draw.polygon(surf, (20, 20, 20), [(cx, sy + 4), (sx + TILE - 5, cy), (cx, sy + TILE - 4), (sx + 5, cy)], 2)
        elif k == ObjKind.DWELLING:
            pygame.draw.rect(surf, (190, 150, 100), (sx + 6, sy + 14, 20, 14))
            pygame.draw.polygon(surf, (140, 70, 50), [(sx + 4, sy + 14), (cx, sy + 3), (sx + TILE - 4, sy + 14)])
            pygame.draw.rect(surf, (20, 20, 20), (sx + 6, sy + 14, 20, 14), 1)
        elif k == ObjKind.SHRINE:
            T.icon_circle(surf, (cx, cy), 11, (170, 120, 230), "法", 12)
        elif k == ObjKind.WELL:
            T.icon_circle(surf, (cx, cy), 10, (100, 180, 240), "泉", 12)
        elif k == ObjKind.TREE:
            T.icon_circle(surf, (cx, cy), 12, (120, 210, 120), "树", 13)
        elif k == ObjKind.CAMPFIRE:
            T.icon_circle(surf, (cx, cy), 10, (250, 140, 50), "火", 12)
        elif k == ObjKind.STABLE:
            T.icon_circle(surf, (cx, cy), 10, (180, 130, 90), "马", 12)
        if obj.guard is not None and not obj.guard.is_empty() and k != ObjKind.MONSTER:
            pygame.draw.circle(surf, (200, 60, 60), (sx + 6, sy + 6), 5)
            pygame.draw.circle(surf, (0, 0, 0), (sx + 6, sy + 6), 5, 1)

    def _draw_panel(self, surf):
        px = VIEW_W + 12
        g, me = self.g, self.me
        T.panel(surf, pygame.Rect(VIEW_W + 4, 0, T.SCREEN_W - VIEW_W - 4, T.SCREEN_H), T.PANEL, None, radius=0)
        T.text(surf, g.date_text(), (px, 10), 15, T.TEXT_DIM)
        T.text(surf, f"{me.name}方 · {self.data.factions[me.faction].name}", (px, 30), 17, me.color, bold=True)
        for i, r in enumerate(RESOURCES):
            cx, cy = px + (i % 3) * 100, 58 + (i // 3) * 24
            pygame.draw.circle(surf, T.RESOURCE_COLORS[r], (cx + 7, cy + 9), 6)
            T.text(surf, f"{me.resources.get(r, 0)}", (cx + 18, cy), 15)
        # 英雄
        y = 112
        T.text(surf, "英雄", (px, y), 15, T.GOLD, bold=True)
        self.hero_rects = []
        for i, h in enumerate(me.heroes[:8]):
            r = pygame.Rect(px, y + 22 + i * 40, 300, 36)
            T.panel(surf, r, (70, 62, 50) if h is self.sel else T.PANEL_LIGHT, T.GOLD if h is self.sel else None, radius=4)
            pygame.draw.circle(surf, me.color, (r.x + 18, r.centery), 12)
            T.text(surf, h.name[0], (r.x + 18, r.centery), 13, (15, 15, 15), align="center", bold=True)
            T.text(surf, f"{h.name} L{h.level}", (r.x + 36, r.y + 3), 14)
            T.text(surf, f"移动 {h.move_points}/{h.max_move}  法力 {h.mana}/{h.max_mana}", (r.x + 36, r.y + 19), 12, T.TEXT_DIM)
            bar = pygame.Rect(r.right - 70, r.y + 10, 60, 8)
            pygame.draw.rect(surf, (30, 28, 36), bar)
            if h.max_move:
                pygame.draw.rect(surf, T.GREEN, (bar.x, bar.y, int(bar.w * h.move_points / h.max_move), bar.h))
            T.text(surf, f"{h.army.total_count()} 兵", (r.right - 40, r.y + 26), 11, T.TEXT_DIM, align="center")
            self.hero_rects.append((r, h))
        # 选中英雄的军队
        y = y + 22 + max(1, min(8, len(me.heroes))) * 40 + 4
        if self.sel:
            T.text(surf, f"{self.sel.name} 的军队：", (px, y), 14, T.TEXT_DIM)
            for i, st in enumerate(self.sel.army.slots):
                r = pygame.Rect(px + i * 42, y + 20, 38, 38)
                T.panel(surf, r, (36, 34, 44), (80, 75, 85), radius=3, width=1)
                if st and st.count > 0:
                    T.text(surf, st.type.name[:1], (r.centerx, r.y + 12), 14, align="center", bold=True)
                    T.text(surf, str(st.count), (r.centerx, r.y + 28), 12, T.HILITE, align="center")
            y += 66
        # 城镇
        T.text(surf, "城镇（左键进入，右键定位）", (px, y), 15, T.GOLD, bold=True)
        self.town_rects = []
        for i, t in enumerate(me.towns[:5]):
            r = pygame.Rect(px, y + 22 + i * 30, 300, 26)
            T.panel(surf, r, T.PANEL_LIGHT, None, radius=4)
            T.text(surf, f"{t.name}  +{t.income(self.data)} 金/天" + ("  ★" if t.built_today else ""), (r.x + 8, r.y + 4), 14)
            self.town_rects.append((r, t))
        self._draw_minimap(surf)
        self.btn_hero.enabled = self.sel is not None
        self.btn_town.enabled = bool(me.towns)
        for b in (self.btn_end, self.btn_next, self.btn_hero, self.btn_town, self.btn_save, self.btn_load):
            b.draw(surf)

    def _draw_minimap(self, surf):
        w = self.g.world
        mm = self.minimap
        pygame.draw.rect(surf, (10, 10, 14), mm)
        sx, sy = mm.w / w.w, mm.h / w.h
        explored = self.me.explored
        step = max(1, int(1 / min(sx, sy)))
        for y in range(0, w.h, step):
            for x in range(0, w.w, step):
                if (x, y) not in explored:
                    continue
                col = T.TERRAIN_COLORS[int(w.terrain(x, y))]
                pygame.draw.rect(surf, col, (mm.x + int(x * sx), mm.y + int(y * sy), max(1, int(sx * step) + 1), max(1, int(sy * step) + 1)))
        for obj in w.objects.values():
            if obj.kind == ObjKind.TOWN and obj.pos in explored:
                t = self.g.towns[obj.data["town_id"]]
                col = self.g.players[t.owner].color if t.owner is not None else (200, 200, 200)
                pygame.draw.rect(surf, col, (mm.x + int(obj.x * sx) - 2, mm.y + int(obj.y * sy) - 2, 6, 6))
        for h in self.g.heroes.values():
            if (h.x, h.y) in explored:
                pygame.draw.circle(surf, self.g.players[h.owner].color, (mm.x + int(h.x * sx), mm.y + int(h.y * sy)), 3)
        vr = pygame.Rect(mm.x + int(self.cam[0] * sx), mm.y + int(self.cam[1] * sy), int(VIEW_W / TILE * sx), int(VIEW_H / TILE * sy))
        pygame.draw.rect(surf, (255, 255, 255), vr, 1)
        pygame.draw.rect(surf, T.BORDER, mm, 1)
