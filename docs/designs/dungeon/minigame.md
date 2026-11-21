# 小游戏框架（面向作者）

> **这一篇回答什么问题**：怎么给副本做一个小游戏——包放哪、要写哪几个方法、绘制与输入从哪个门进、结算结果怎么被剧本读到。**做小游戏的作者**从 §1 看玩法形态、§2～§4 照着写；**排查「舞台没开 / 按不动 / 结果没记上」**的直接进 §5；**改框架本身**看 §5 与 §8。
>
> 一句话：**写一个 Python 类就是一个小游戏**。绘制、输入、帧时钟、贴图、结算、回放都由框架承担，作者不接触窗口框架。
>
> 相关页面：触发器动作字段（`mini_game` 的 `action_data`）见 [script.md](script.md) §6 · 宿主窗口侧端口见 `docs/Dungeon/window_host.md` §1 · 章节与触发器的整体写法见 [README.md](README.md)。

## 1. 玩起来是什么样

小游戏在**会话窗口内的覆盖层舞台**上运行：帧末绘制的一块铺满客户区的顶层窗口，压在所有浮层与工具条之上。

- 舞台存续期间**步进与自动播放挂起**，但点击不会关掉它——鼠标是游戏输入；
- 舞台铺满客户区，工具条不会被误点；
- 按 **ESC** 中止，按「无结果」收场；
- 结束调用 `api.finish(...)`，返回值记进触发器的选择数组，也写进回放记录（回放时直接复现，不重跑游戏）。

小游戏**不区分胜负**：返回值只是一个整数（达成关数、命中数，语义自定），分支由别的触发器按「选择:触发器名」判定次数 / 占比 / 趋势 / 最后一次。所以「赢了走 A、输了走 B」是剧本里写两个触发器，不是游戏里分胜负。

ESC、关窗口、游戏抛异常，三者都按「无结果」处理：不记返回值，挂起态解除，副本照常继续。

## 2. 包放哪

```
data/packs/minigames/<id>/
├── manifest.json   # {id, name, backend?: "py", entry?, params?}
└── game.py         # 恰一个 MiniGame 子类（entry 缺省即此文件）
```

| manifest 键 | 作用 | 缺省 |
|---|---|---|
| `id` | 与目录名一致（声明了才校验） | 目录名 |
| `name` | 显示名，编辑器候选与舞台标题用它 | `id` |
| `backend` | 目前只有 `"py"`；写了别的会被拒 | `py` |
| `entry` | 入口文件名 | `game.py` |
| `params` | 可配参数声明（§4） | 无 |

目录名就是游戏 id，也是触发器里要写的名字。**manifest 可以省**：目录里放一个定义了 `id` 与目录名一致的 `MiniGame` 子类的 `game.py` 就能跑，显示名退化成目录名——省掉之后，契约脚本也不再扫这个包（它按 manifest 找入口），所以正式发布前还是补上。

解析顺序先看内置注册表（`REGISTRY`，目前留空，作为框架扩展点），再看数据包；**同名以内置注册表为准**。运行时唯一的解析入口是 `resolve_mini_game(game_id)`，编辑器候选走 `list_mini_games()`。

## 3. 作者 API

```python
from dungeon.window.minigame import MiniGame

class MyGame(MiniGame):
    id = "my_game"            # 与包目录 / manifest 一致（契约脚本校验）
    label = "我的游戏"
    description = "..."
    params = (...)            # 可配参数声明（§4）
    aspect = 4 / 3            # 画面长宽比；None = 填满整个会话窗口

    def setup(self, config): ...      # 一次；config = 触发器 action_data
    def update(self, dt): ...         # 每帧；发绘制指令 + 轮询输入
    def teardown(self): ...           # 一次
```

`self.api`（`GameAPI`）是运行时注入的服务面，`setup` 之前不可用：

| 类别 | 方法 |
|---|---|
| 几何 | `width` / `height`（画布像素尺寸，随会话窗口缩放，每帧读一次即可自适应） |
| 绘制 | `draw_rect` / `draw_round_rect` / `draw_circle` / `draw_line` / `draw_polygon` / `draw_text` / `draw_image`（每帧在 `update` 里发出，运行时负责清屏与提交；颜色一律 `(r, g, b, a)`） |
| 贴图 | `draw_image(源, pmin, pmax, uv=None)`——源可以是包内相对路径的 png / jpg，也可以是离屏画布；`uv` 裁源区域（0~1） |
| 输入 | `key_down("a"…"z" / "0"…"9" / "space" / "enter" / "escape" / "up"… / "shift" / "ctrl")`、`mouse_pos()`、`mouse_down(button=0)`——全是**轮询**语义，不需要自己维护状态表 |
| 服务 | `finish(result=None)`（结算，重复调用无效） / `hud(text)`（顶部一行） / `notify(msg)`（轻通知，3 秒消失） / `read_state(key)` |

`read_state` 是只读快照，可用键：`章节` / `身高` / `介入度` / `破坏性` / `总伤亡` / `总步数`，未知键返回 `None`。

`finish` 两种传法：`api.finish(3)` 直接用整数当返回值；`api.finish({"level": 3, "score": 120})` 取 `level` 当返回值，其余字段整体并入触发器的 `game_result`，供叙事引用。

**离屏画布**（`api.offscreen(w, h)`）是给「整层预渲染」准备的：关卡生成时把地形、织物一次性画进画布，此后每帧只 `draw_image` 一次，绘制指令数与地图复杂度无关。画布内容变化后下一次绘制会自动重传，且只重传变化的矩形。

## 4. 参数与触发器接线

`params` 与 manifest 的 `params` 是同一份声明：数据包写在 manifest 里（编辑器读它生成表单），内置注册表里的游戏则从类属性读。每项形如 `{key, label, type, default, min, max}`，`type` 允许 `int` / `float` / `str` / `bool` / `color`。玩家填的值随触发器动作一起传进 `setup(config)`——`config` 就是 `mini_game` 触发器的 `action_data`。

参数的默认值建议写进 `setup` 里的兜底逻辑：玩家没填、或剧本从旧版本带过来时，游戏仍要能开局。

## 5. 内部实现

- **帧驱动，没有自己的帧时钟**：由会话窗口在**所有顶层浮层之后**调用舞台的 `render(w, h)`；每帧 `game.update(dt)`（`dt` 夹取 ≤0.05），随后画边框与 HUD，已结算则销毁。`update` 里抛异常按「无结果」收场，不拖垮副本会话。
- **输入直接问 imgui**：立即模式下每帧状态都是新鲜的，所以游戏侧轮询即可，不需要 handler 状态表。
- **绘制走 drawlist**，裁剪矩形压在画面区域内（声明了 `aspect` 时，画面等比缩放进「窗口减去边缘留白」的区域并居中，其余维持压暗背景；越界绘制一律裁掉）。
- **离屏画布用一张 GL 纹理 + 脏矩形增量**：宿主自持一张纹理，每帧按绘制包围盒记脏，用 `glTexSubImage2D` 只重传变化的那几块（整张 1088×768 重传实测 0.294 ms）；画布被整块换掉时旧纹理按弱引用自动回收。游戏侧不用改任何写法。
- **销毁随浮层同批清理**：此时帧时钟已停、GL 上下文已释放，所以删纹理只丢句柄；结果回传自然失效——这就是「关窗口后不再记结果」的来处。

## 6. 拓展用法

- **世界包可以自带小游戏**：查找顺序是自由目录 `data/packs/minigames/<id>/` 优先，其次是**当前激活世界包**里的 `data/worlds/<世界 id>/minigames/<id>/`。把游戏塞进世界包，切到那个世界就自动可用，不装包的人看不到——适合「这套剧本专属的小游戏」。
- **不写 manifest 的极简包**：只想试玩时，建个目录放一个 `game.py` 就能在编辑器候选里看到并运行；等要发布再加 manifest 补显示名与参数。

## 7. 官方资源

| 包 | 是什么 | 规模 |
|---|---|---|
| `data/packs/minigames/reaction/` | 点击反应，最小可用示例 | 约 100 行 |
| `data/packs/minigames/escape_giantess/` | 逃离巨大娘移植版：离屏画布整层预渲染地形 / 织物 + 每帧少量动态图元 | 约 2500 行 |

前者适合照着改，后者是「一个完整玩法怎么落进这个框架」的样本。内置注册表（`REGISTRY`）当前为空，保留给随应用发布的常驻游戏。

## 8. 作者须知

**硬性约束**（`python tests/check_minigame.py`，CI 门禁）：

- 一个入口文件里**恰一个** `MiniGame` 子类，且 `id` 与包 id 一致（类名不能叫 `MiniGame`）；
- 禁 import 渲染后端与宿主细节：`imgui_bundle` / `dearpygui` / `tkinter` / `customtkinter` / `threading` / `subprocess` / `socket` / `ui` / `services` / `PIL`；
- 禁 `print`（输出走 `api.notify` 或过程日志）；
- 禁碰私有面：`api._` / `self.api._` / `stage._` 一律违规——运行时随时可能重构。

贴图加载是运行时职责，所以 `PIL` 也在禁列：用 `api.draw_image("贴图.png", pmin, pmax)`，相对包目录。

<details>
<summary>跑起来看效果（改完小游戏后自检与真渲染）</summary>

| 脚本 | 覆盖 | 命令 |
|---|---|---|
| `check_minigame.py` | 包契约（manifest 结构 / 游戏代码 AST 扫描） | `python tests/check_minigame.py` |
| `dungeon_autopilot.py --scene mini-game-py` | 覆盖层舞台打开 / 结算分支 / ESC 中止 | `python scripts/dungeon_autopilot.py --scene mini-game-py` |
| `dungeon_autopilot.py --scene mini-game-repeat` | 结算后回主页面、后续步进可再进 / 不因重判原地重启 | `python scripts/dungeon_autopilot.py --scene mini-game-repeat` |
| `dungeon_autopilot.py --scene mini-game-escape` | escape 移植版真渲染冒烟：离屏 GL 纹理上传 / 每帧绘制 / 中止 | `python scripts/dungeon_autopilot.py --scene mini-game-escape` |
| `escape_sim.py` | escape 逻辑回归（无显示器、**进 PR 门禁**）：关卡生成硬约束 / 连通性 / 随机走位 / 结算 payload 形状 | `python scripts/escape_sim.py` |

</details>

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（全景）· [script](script.md)（章节与触发器字段）·
  [characters](characters.md)（人物表与账本）· [voice](voice.md)（对话语音）·
  [admission](admission.md)（进入准入）· [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏，本页）· [components](components.md)（显示组件）
- **chat/**：[README](../chat/README.md)（话题与好感 / 紧张度）·
  [lens](../chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md) / [chat](../behaviors/hooks-chat.md)）·
  [example-imperial](../behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](../world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](../world_packs/author.md)（制作与清单）

**单篇**

[地址系统](../address_system.md) · [报告生成](../report_selection.md) ·
[角色演化](../character_evolution.md) · [资源与包体系](../resources.md) ·
[挑战包](../challenges.md) ·
[剧本编辑器](../scenario_editor.md) · [界面双模式与外观](../ui_modes.md) ·
[角色的长期行为](../character_time.md) · [身材剪影](../body_preview.md) ·
[更新检查](../update_check.md)

</details>
