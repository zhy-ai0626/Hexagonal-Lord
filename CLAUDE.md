# 六角领主 Hexlords · 项目说明（给 AI 助手）

用 Python + pygame 仿《英雄无敌 3》做的回合制策略游戏。种族、兵种、宝物、法术全部原创，规则结构参考英雄无敌 3。
用户是 AI 专业大三学生，Python 基础不算扎实：改动时用中文解释原理，代码注释写中文。

**每次开始先读 `TASK_STATE.md`**：里面是当前进度、已知问题和下一步候选，以它为准。做完一块工作就更新它。

## 用户定下的方向（改之前先问）

- 界面：pygame 2D，自画几何图形 + 中文字，不用图片素材。
- 内容：全部原创，不照搬原版名字和数值。
- 数据：所有数值放 `data/*.json`，改数值不改代码。
- 规则参考：用户的 HOMM 讲义 `~/University/课外/HOMM 英雄无敌3/`（L03 兵种、L05 伤害、L09 城镇、L12–L18 电脑 AI）。想对照原版设计时去那里查。

## 环境与运行

```bash
conda activate hexlords          # Python 3.11 + pygame 2.6.1，环境已建好
cd ~/Desktop/Hexlords
python run.py
```

不激活也可以直接用 `/opt/anaconda3/envs/hexlords/bin/python`。中文字体用 macOS 自带的 `Hiragino Sans GB.ttc`（见 `hexlords/ui/theme.py` 的候选列表）。

## 测试（改完必须跑）

```bash
PY=/opt/anaconda3/envs/hexlords/bin/python
$PY tests/test_core.py                                  # 规则层单测 + 3 个种子各让 3 个 AI 打 30 天
SDL_VIDEODRIVER=dummy $PY tests/ui_smoke.py             # 无窗口渲染 12 个画面到 tests/shots/*.png
SDL_VIDEODRIVER=dummy $PY tests/play_sim.py             # 模拟玩家点击 + 电脑回合跑 8 天
```

改了界面就用 Read 打开 `tests/shots/` 里对应截图看排版。`test_core.py` 里的函数也兼容 pytest，但环境里没装 pytest，直接用 python 跑。

## 架构

```
data/*.json        factions（种族/兵种/野怪）spells skills artifacts buildings heroes
hexlords/core/     规则层，不依赖 pygame
  data.py          读 JSON → dataclass；get_data() 单例；CreatureType.value = AI 和经验用的"战斗价值"
  army.py          Army 7 槽位、Stack、transfer_stack / split_stack
  hexmath.py       15×11 odd-r 六角格：邻居、cube 距离、像素换算
  hero.py          四维、经验表 xp_for_level、副技能、宝物槽、移动力、升级抽选
  town.py          建筑树（replaces 链表示升级）、周产量、招募、法师塔抽法术
  player.py        资源、市场汇率
  world.py         方格地图、地形消耗、MapObject、Dijkstra 寻路（物件格只能当终点）
  mapgen.py        值噪声地形 → 出生点 → 铺路 → 撒物件（守卫按离出生点距离加强）
  battle.py        战斗引擎：行动队列、等待、反击、伤害公式、14 种兵种能力、法术
  game.py          回合/每日结算、英雄逐格移动、拜访物件、战斗收尾、胜负、pickle 存档
hexlords/ai/
  battle_ai.py     choose_action（期望输出价值 − 反击损失）、choose_spell、auto_resolve
  adventure_ai.py  建城优先级表、招兵、雇英雄、按 价值/(1+距离/日移动力) 选目标、探索
hexlords/ui/
  app.py           场景栈 + run_modal（对话框/战斗同步弹出）+ resolve_events 事件分发
  main.py / adventure_scene.py / town_scene.py / hero_scene.py / battle_scene.py / dialogs.py
  theme.py / widgets.py   字体、配色、按钮、悬停提示
```

### 关键约定

- **事件模型**：`Game` 里会改状态的方法返回事件列表（`Message` `Choice` `BattleEvent` `LevelUp` `Exchange` `EnterTown` `GameOver`）。界面用 `App.resolve_events` 处理，电脑用 `AdventureAI.handle` 处理。新加地图物件时，在 `Game.visit` 返回事件，不要在 core 里直接弹界面。
- **战斗**：`Battle` 只管规则，`b.current` 是当前行动部队，调用 `do_move / do_melee / do_shoot / do_wait / do_defend / cast` 推进。结束时 `_finish` 把剩余数量写回原 `Army`，`Game.finish_battle` 再处理经验、宝物、占领。
- **人类 vs 电脑战斗**：`App.run_battle` 判断哪一方归人类，有人类就开 `BattleScene`，否则 `auto_resolve`。
- **新增法术效果键**：在 `spells.json` 的 `effect` 里加键后，要在 `BattleStack.attack_value / defense_value / speed` 或 `calc_damage` 里读取它。
- **新增兵种能力**：`factions.json` 的 `abilities` 加字符串 → `battle.py` 的 `_strike` 等处实现 → `battle_scene.py` 的 `ABILITY_NAMES` 加中文说明。
- **存档**：`pickle` 整个 Game 状态（除 data），存到 `saves/quick.sav`。改了类的字段后旧存档可能读不出来，这是已知限制。
- `Hero._next_id` / `Town._next_id` 是类变量，读档时会重设。

## 工作习惯

- 技术细节直接做，方向性的大改（换界面库、改核心规则、删功能）先问用户。
- 汇报要能核查：列出跑了哪些命令、测试结果数字、改了哪些文件。
- git 仓库，远程 `origin` = https://github.com/zhy-ai0626/Hexagonal-Lord （公开仓库，分支 main）。一块工作做完、测试通过后按主题提交；push 前先问用户。
