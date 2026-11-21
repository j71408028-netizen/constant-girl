# 显示组件（面向作者）

> **这一篇回答什么问题**：副本窗口里的显示组件是什么、方案怎么声明、窗口怎么
> 挂接、正文版式怎么给其他组件留位；以及与之相邻但**不属于组件包**的窗口级浮层。
> 一般读者顺序读完即可；**组件作者**从 §9 契约与 §7 参数表进。
> 直接相关页：编辑器里的组件管理页 [../scenario_editor.md](../scenario_editor.md) §5 ·
> 方案字段与旧配置迁移 [script.md](script.md)。

## 1. 组件是什么

显示组件是副本窗口里的**可插拔界面块**：状态栏、过程日志、三种正文版式都是组件。
方案作者在 `config.json` 里声明用哪几个（§2），玩家在副本里通过浮层设置改它们的
停靠侧（§3）。

方案里的三个键：

| 键 | 形状 | 说明 |
|---|---|---|
| `text_component` | `text` / `text_card` / `text_nvl` 三选一 | 正文版式（谁接管正文显示） |
| `components` | 组件 id 列表 | 其余组件，按声明顺序排在主组件之后 |
| `components_params` | `{组件id: {参数: 值}}` | 每个组件的参数（§7） |

文本主组件**必须三选一**：缺省或写错都回退 `text`；旧写法把文本组件混写在
`components` 列表里的，加载时自动提升为主组件、落盘时迁走（迁移规则见
[script.md](script.md) §9.2）。

## 2. 从方案声明到窗口挂接

进入副本时，程序按这个顺序把组件立起来：

1. **读声明**：`text_component` 归一（不在三选一集合回退 `text`）；`components`
   列表去重保序、未知 id 记一条日志跳过；结果里没有文本主组件时自动补一个——
   **正文一定有版式**。
2. **实例化**：每个（窗口, 组件）一对一实例，注入按 §7 规则合并后的参数。
3. **挂接**：逐组件 `build` → 两遍式重排（§3）→ 每帧 `draw`。窗口尺寸变化、
   过程日志展开收起、代管区靠左靠右切换，都会触发重排。

## 3. slot 代管区

**代管区（slot）**是文本主组件在重排时划出的「我替你留好、代管其呈现」的区域：
窗口做机械匹配把它分给声明的子组件，**子组件不再自己发明坐标**。代管区自带三种
底纹契约——`host` 文本组件画面板底子组件只画内容（默认）/ `bare` 无底纹 /
`own` 子组件自绘面板——外观由方案参数与主题接管，不用组件操心。

匹配按声明机械进行：形状必须命中（横带 / 竖栏 / 块三种），代管区声明的角色与
组件的 `roles` 求交集，按声明顺序取第一个还有空位的；竖栏从上往下占格、横带从左
往右。重排是**两遍式**：先让文本主组件划区并分配，再让其余组件排版——此时它们已
能查到自己被分到的矩形。放不下就回退独立浮动面板（状态栏落左上角、过程日志落
右上角）。纯数据与几何都在 `dungeon/window/layout.py::Slot / SlotStyle`（入场
动画数学同文件），不依赖绘制库。

<details>
<summary>各文本组件实际交出的代管区（写需要贴靠正文的外部组件时展开查）</summary>

| 文本组件 | 代管区 | 形状 / 用途 |
|---|---|---|
| `text` | `scrim_band` | 横带（bare 底纹）：状态栏，只在有状态栏组件时声明 |
| `text` | `scrim_side` | 竖栏（own）：过程日志，从下方升起并淡入 |
| `text_card` | `card_footer` | 横带（host）：状态栏，右端给继续指示留位 |
| `text_card` | `card_side` / `card_side_low` | 竖栏（own）：过程日志，从停靠侧屏幕边缘平移进入 |
| `text_nvl` | `nvl_header` | 横带（host）：状态栏，只补足状态栏自报的高度差 |
| `text_nvl` | `nvl_side` | 竖栏（host 不画底纹）：与正文列共底纹融合 |

</details>

> **两点边界**：停靠侧「靠左 / 靠右」不是方案参数，是玩家在副本设置里改的窗口
> 视觉设置，改完即时重排；入场动画（从屏幕边缘平移、淡入）由代管区的样式声明
> 驱动，组件只管往分配好的矩形里画内容。

## 4. 窗口级浮层（overlay）

浮层与组件是**两套机制**——组件不注册为浮层。浮层只有三种，全部模态：**对话
记录**（半透明遮罩 + 滚动面板）、**副本设置**（音量总线滑条 / 帧率上限 20–240 /
组件代管区靠左靠右，改动松手即落盘）、**人物档案**（在场 / 最近离开分组，重要
角色的临时称呼可手动合并）；小游戏舞台打开时压过一切浮层。实现与双层绘制在
`dungeon/window/overlay.py::OverlayHandler`。

| 键 | 作用 |
|---|---|
| F12 / F2 / H / A / O / C | 过程日志 / 截图 / 对话记录 / 自动播放 / 设置 / 人物档案 |
| ESC | 有关浮层先关浮层 |
| 空格 / 回车 / 左键 | 推进剧情（浮层打开期间挂起，点击只关浮层；悬停在组件工具条上时不推进） |

组件也能调出浮层（经 `ctx` 的服务调用），行为与按键一致。

## 5. 内部实现

- **生命周期收尾**：停帧 → 释放图形资源 → 逐组件 `destroy` → 丢弃本窗口的实例
  缓存。
- **进程内组件包只加载一次**，之后每个副本窗口各建一套实例。
- > **容错口径**：单个组件出错不拖垮一局——任何钩子抛异常只在过程日志记一条，
  > 窗口照常运行（draw 失败下一帧还会重试）；组件构造失败就跳过且不重试。

## 6. 拓展用法：外部组件包

本节收录界面上没有说明、但程序实际支持的用法。目前一件：**外部组件包**——只需
一个目录，入口文件固定叫 `components.py`，暴露 `REGISTRY = {组件id: 组件类}`
字典即可；加载失败自动回退内置包，一局副本永远有正文可读（加载实现在
`dungeon/window/component_registry.py::ComponentRegistry._load`）。组件的 id 规则、
参数契约与守卫口径见 §9 / §7。

## 7. 参数表

每个参数一条声明：

| 键 | 说明 |
|---|---|
| `key` / `label` | 参数名（写进 `components_params` 的内层键）/ 编辑器表单标签 |
| `type` | `int` / `float` / `bool` / `color` / `text` |
| `default` | 默认值；color 必须是 `(r,g,b,a)` 四通道 0–255 整数 |
| `min` / `max` | 数值范围；**声明了就一定被夹取** |
| `note` | 编辑器提示文案 |

夹取规则编辑器与运行时同一套：默认值打底 → 方案覆盖值非 None 才生效 → 数值夹进
min/max → **未知参数键忽略**。方案里整块参数写坏（不是字典）就整体回退默认值。
color 在方案里写成 `[r,g,b,a]` 数组。

<details>
<summary>五个官方组件的完整参数表（调参时展开查）</summary>

| id | 专属参数（默认值 / 范围） |
|---|---|
| `text` | `height_percent`（45 / 15-80）、`max_lines`（1 / 1-5）、`gradient_color`（衬底最底处颜色，向上渐隐） |
| `text_card` | `width_percent`（70 / 30-95）、`max_lines`（1 / 1-5）、`bg_color` / `border_color`、`glass`（True，背后采样背景模糊） |
| `text_nvl` | `margin_percent`（0 / 0-30，0=全屏）、`bg_color`、`use_serif`（True，衬线字体，找不到回退默认） |
| `attr_bar` | `name_color` / `text_color`、`panel_width`（480 / 200-1600）、`draw_own_surface`（False） |
| `proc_log` | `panel_width`（460 / 240-960）、`scroll_height`（300 / 60-800）、`max_lines`（300 / 50-2000）、`draw_own_surface`（False） |

`draw_own_surface=True` 时组件否决宿主代管区的缺省底纹、自绘面板。

</details>

## 8. 官方组件

官方组件收在窗口运行时的组件包 `dungeon/window/component_pack/`
（`__init__.py::REGISTRY` 是唯一出口）：

| id | 版式 | 一句话 |
|---|---|---|
| `text` | 底部渐变 | 视口底部向上淡出的深色衬底显示最近几句（ADV 风格） |
| `text_card` | 底部卡片 | 居中圆角毛玻璃卡片（背景模糊副本 + 染色 + 玻璃边） |
| `text_nvl` | 全屏 NVL | 全屏半透明覆盖层堆叠全部历史段落，滚轮回看 |
| `attr_bar` | 状态栏 | 单行实时显示演化属性（展示状态为「显示」的才上屏），数值颜色随值域绿→黄→红 |
| `proc_log` | 过程日志 | 订阅运行消息的面板，默认收起（F12 展开） |

文本三件套共享悬浮工具条（自动播放 / 截图 / 过程日志 / 人物档案 / 副本设置）与
三个公共参数：`label_color` / `highlight_color` / `show_indicator`（各自专属参数
全表在 §7）。

## 9. 组件作者须知

组件是一个 Python 类，继承窗口提供的基类
（`dungeon/window/component_registry.py::DungeonComponent`）。**所有钩子都有默认
空实现**——只做展示的组件实现 `build` 与 `draw` 就能跑起来，其余按需覆盖。

类属性是组件的「身份证」：编辑器组件页显示的名称、说明与参数表单都从这里读。

| 属性 | 说明 |
|---|---|
| `id` | 组件唯一 id，同时是 `components_params` 里的键 |
| `label` / `description` | 编辑器展示名 / 一句话说明；留空时编辑器显示 id |
| `param_specs` | 参数声明列表（§7） |
| `roles` / `shapes` | 想被文本主组件「代管区」收留时声明的角色与形状（§3）；留空表示自己找位置 |
| `owns_text_display` | True 表示接管正文显示（文本三件套） |
| `TAG_PREFIX` | 绘制层子窗口 tag 前缀，组件之间不得相撞 |

窗口按固定时机调用这些钩子：

| 钩子 | 调用时机 |
|---|---|
| `build(ctx)` | 进入会话、实例化后一次 |
| `layout(ctx)` | 每轮重排；只算几何与缓存，不绘制 |
| `draw(ctx)` | 每帧，立即模式绘制 |
| `refresh(ctx)` | 状态更新后经帧时钟调用（默认就是转调 `layout`） |
| `destroy(ctx)` | 会话收尾（图形资源已释放，只兜底清状态） |
| `slots(ctx)` | 可选；返回代管区清单，目前只有文本主组件实现（§3） |
| `top_inset(ctx)` | 可选；自报在窗口顶部占用的高度（状态栏用） |
| `toggle(ctx)` | 可选；面板类展开 / 收起（过程日志用，F12 触发） |

组件拿数据、调服务只通过窗口递进来的 `ctx`，分四类：**读状态**（故事历史、副本
状态、演化量）、**问几何**（视口尺寸、自己被分到的矩形、停靠侧、背景模糊采样）、
**用帧时钟**（延时与周期任务）、**调服务**（浮层、截图、自动播放）。服务面的实
现集中在 `dungeon/window/components.py::ComponentHandler`。

<details>
<summary>守卫怎么盯住这些约定（写外部组件包前展开看）</summary>

无 GUI 守卫 `python tests/check_component_pack.py` 用替身窗口跑一遍
build → layout → refresh → destroy 冒烟，并用 AST 检查三条：不许绕过 `ctx` 读
窗口私有成员；不许 `print`（日志一律走 `dungeon/process_log`）；凡定义了 `id`
的类必须登记进注册表。

</details>

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（全景）· [script](script.md)（章节与触发器字段）·
  [characters](characters.md)（人物表与账本）· [voice](voice.md)（对话语音）·
  [admission](admission.md)（进入准入）· [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏）· [components](components.md)（显示组件，本页）
- **chat/**：[README](../chat/README.md)（话题与好感 / 紧张度）·
  [lens](../chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md) / [chat](../behaviors/hooks-chat.md)）·
  [example-imperial](../behaviors/example-imperial.md)（示例包）

**单篇**

[地址系统](../address_system.md) · [报告生成](../report_selection.md) ·
[角色演化](../character_evolution.md) · [资源与包体系](../resources.md) ·
[挑战包](../challenges.md) · [世界包](../world_packs.md) ·
[剧本编辑器](../scenario_editor.md) · [界面双模式与外观](../ui_modes.md) ·
[角色的长期行为](../character_time.md) · [身材剪影](../body_preview.md) ·
[更新检查](../update_check.md)

</details>
