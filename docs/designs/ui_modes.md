# 界面双模式与外观

> **这一篇回答什么问题**：专业 / 挂件（ME模式）两套界面各自长什么样、怎么切换、
> 下次启动进哪一套怎么定，外观亮暗与配色、字体怎么调，启动时你会先看到什么。
> - **普通玩家**：顺着 **§1 → §5** 看就能把两套界面用顺手；只想换外观、换字体的
>   直接看 **§3 / §4**。
> - **排查切换、置顶、DPI 问题的**，以及想读懂配色文件和点阵规则的**界面改造者**：
>   从 **§3 / §4 的折叠块**与 **§6** 进。
>
> 相关页面：副本窗口运行时 [dungeon/README.md](dungeon/README.md) ·
> 副本窗口的显示组件与主题 token [dungeon/components.md](dungeon/components.md) ·
> 更新检查 [update_check.md](update_check.md)。

## 1. 两套界面，随时切换

程序同时有两套完整界面，共用同一份数据和设置，随时可以互相切换：

- **专业界面**：一个 1280×720 的大窗口，左边导航栏、右边内容区；探索 / 挑战 /
  资源中心 / 剧本编辑 / 地标管理 / 描述管理六个页面平铺切换（没有多级页面栈），
  设置是一个弹出的对话框、不算页面。世界包声明拥有 `scenarios` 时，「剧本编辑」
  页会锁成一条提示条。
- **挂件**：一个 360×620 的小窗（最小 330×470），界面文案叫「ME模式」，恒为暗色。
  日常游玩都在——副本、角色档案、挑战、世界包、聊天和精简设置（置顶 / 身材预览
  头像开关 / 世界履历 / AI 服务商）；但**资源中心、剧本编辑器、地标管理、描述
  管理没有挂件版**，网络代理、屏蔽词等不少设置也只在专业界面的设置对话框里
  （挂件的设置屏有一行提示指向）。观感和特别机制见 §2。

怎么切：专业界面用导航栏的「⇄ ME模式」，挂件用标题栏的「⇄」。相关的设置存在
`data/user/settings.json`：`ui_mode` 记录你**实际在**哪个界面（每次切换都会落
盘），`ui_startup` 记录**启动偏好** `pro / mini / exit`（exit 表示跟随上次退出时
所在的界面，是缺省值），启动时由它决定先开哪一套。「设置 → 启动界面模式」只改
启动偏好，不会动当前窗口。副本会话进行中不允许切换。

> 切换不是换皮肤：它会关掉当前窗口、按另一套重新搭起来；副本会话跟着旧窗口结束，
> 所以进行中会直接拒绝切换。

## 2. ME 模式的观感与特别机制

**低像素观感**：整个挂件只有直角（没有圆角）和 2px 硬描边；用色全部来自一张
16 色调色板（每种颜色备一对亮 / 暗值，按当前外观取一边）；文字用内嵌的位图字形
渲染，小字号也不糊。面板、按钮、输入框、滚动区都出自同一套像素控件，图片在显示
前也会统一量化成像素风。

**调查掷局**：挂件启动后 80ms 会自动掷一次骰子，一次掷三样
（`ui/mini/investigation.py::Investigator.investigate`）：

| 掷什么 | 规则 |
|---|---|
| 剧本（副本方案） | 从全集里随机掷；你当前位置进不去的方案先按进入准入过滤（同地址维度 / 距离上限 / 身高区间，见 [dungeon/admission.md](dungeon/admission.md)），全都进不去就放宽成全集，并注明「地址已放宽」 |
| 取材表 | 世界包锁定 `material_table` 时不掷；否则从可用组里随机掷一组，掷中立刻应用（和资源中心走同一条路） |
| 世界包线索 | 只掷还没启用、清单也没有错的包，并按你当前位置的地址维度过滤；**只给你线索，不直接启用** |

掷中剧本 / 取材表会立即生效并保存设置。

**整窗换屏**：ME 模式没有独立的小弹窗——角色档案 / 设置 / AI 服务商 / 挑战
列表 / 挑战确认 / 世界包 / 聊天（唯一没有标题栏的一屏）等，全都是在同一个窗口
里整屏换页，像栈一样层层进入，靠每屏左上角的 ◀ 返回键一屏屏退回去。也因此没有
点击穿透这回事，置顶窗口不会和弹窗抢层级。

**窗口置顶**：设置里可以开关。Windows / macOS 上开了就生效；Linux 是否可用取决于
窗口管理器，不支持时设置项会置灰；设置失败会回退为关并提示。Windows 上标题栏也会
跟着换成暗色。

## 3. 外观：亮暗与配色

程序给系统浅色和深色各记一套配色：系统浅色默认用 Classic，系统深色默认用
Slate（留空表示跟随默认），设置里可以分别换（键 `theme_palette` /
`theme_dark_palette`），CTk 的内置色主题 `color_theme` 也在同一处选。生效配色
一变，整个窗口会遮罩重刷。

> 亮暗怎么跟系统走：程序用 darkdetect 探测系统当前亮暗，主窗口每 2 秒轮询一次，
> 系统切换亮暗后就自动换用对应的那套配色。

> 配色文件是程序自带的资源，一个文件就是一套配色（`assets/theme/Slate.json`
> 暗色 / `Classic.json` 亮色）。挂件恒为暗色——入口里固定设 Dark，所以它只用得
> 到半边。

<details>
<summary>配色文件四层结构、运行时换配色与外观广播（界面改造者展开查）</summary>

一套配色文件分四层（`ui/ctk/theme.py`）：

| 层 | 内容 | 引用形式 |
|---|---|---|
| `primitives` | 原子色阶（全文件唯一允许裸 hex 的地方） | `$prim:"slate.700"` |
| `roles` | 语义角色，亮暗成对 `[light, dark]` | `$role:"border-*"` |
| `vars` | 页面常量（对外接口），常量名前缀就标明所属模块 | `$pair / $map` |
| `mode` | 可选声明 `light / dark`——声明后就是「单观感配色」，成对 token 允许只写一边 | — |

**运行时换配色** `apply_palette(name)`：新值**就地写进原对象**（已经建好的控件
持有同一个对象，所以立刻生效）；不可变的单色 token 按身份替换掉各模块里的同名
全局量；配色声明了 mode 就同步外观模式；最后显式让全部 CTk 控件重走一遍外观
回调（明暗没变时官方库不会触发）。

**外观广播**（`core/appearance.py::set_mode / subscribe / resolve`）：模块级的
单值 `Light / Dark`（默认 Dark），一设置就遍历订阅者广播；`resolve(color_value)`
把 `(亮, 暗)` 二元组按当前模式取一边。目前的订阅者只有挂件的像素重刷。

CTk 运行时补丁（`ui/ctk/ctk_patch.py`，import 即生效）：外观切换时同步刷新控件
的 tkinter Frame `bg`，并修复带 `textvariable` 的 placeholder。

</details>

## 4. 字体

三个阅读区可以在设置里换字体：**报告正文** `report_font`（Windows 缺省仿宋）、
**描述文本** `desc_font`（缺省等宽）、**副本正文** `dungeon_font`（副本独占
设置，存 `dungeon_settings.json`，缺省用 CJK 首选）；设置对话框会先用
`tkfont.families()` 确认字体真的存在才接受。

界面里的中文首选按平台自动挑：Windows 微软雅黑 / macOS 苹方 / Linux Noto Sans
CJK SC。你在设置里选的 Windows 独有字体（宋体 / 仿宋 / 楷体这些）到了非 Windows
平台会自动落到该平台的中文首选上，`Consolas` 落到对应平台的等宽字体，其余原样
使用（`ui/ctk/fonts.py::font_family_for`）。

<details>
<summary>各平台字体候选清单与缩放对齐（配置的字体没生效时展开查）</summary>

| 平台 | 首选 `cjk_family()` | 回退候选（按序） |
|---|---|---|
| Windows | Microsoft YaHei | → 微软雅黑 → SimHei → Arial |
| macOS | PingFang SC | → Hiragino Sans GB → STHeiti → Heiti SC → Arial Unicode MS → Microsoft YaHei → Helvetica |
| Linux | Noto Sans CJK SC | → Noto Sans SC → WenQuanYi Micro Hei → WenQuanYi Zen Hei → Droid Sans Fallback → DejaVu Sans |

`align_native_scaling(root)` 把 Tk 的 `tk scaling` 对齐到 CTk 的
`widget_scaling`，并跟随系统缩放（原生控件的磅→像素换算就和 CTk 一致了）。挂件
模式另有一套点阵字体候选，和专业字体体系互不相干（§2）。

</details>

## 5. 启动屏

进专业界面时，启动的全流程是这样的：先弹出一个进度小窗（**启动屏**）显示构建
进度 → 全部构建完成后，主窗口按启动屏记录的位置、大小和状态（最大化 / 最小化）
**原地顶替**加载占位 → 启动屏随即关闭。构建过程中可以取消；启动屏实在拉不起来
时，退回进程内的加载窗来顶替。主题切换时那个全窗遮罩，复用的就是这套加载页。

## 6. 内部实现

- **进入前的引导与看门狗**：不管进哪套界面，都先引导——加载设置 → 网络代理 →
  世界包激活态；主循环开跑前装好卡死看门狗（卡死就转储）。调度循环在两套入口
  之间周转，读到切换请求先做跨根清理，再进另一套界面的入口。
- **两套入口**（`main.py`）：挂件——固定暗色 → DPI 上下文（见下）里建根窗口 →
  挂件主窗口进主循环 → 返回切换请求（如果有）；专业——先设 CTk 色主题与配色
  （必须在建任何控件之前）→ 拉起子进程启动屏（§5）→ 回退加载窗 → 任务泵逐项
  构建（每 50ms 轮询一次取消）→ 构建完成用主窗口原地替换加载窗。
- **启动屏协议**（`ui/ctk/splash.py::splash_process`）：启动屏跑在独立子进程里，
  主进程同步构建界面；它必须在创建任何 Tk 窗口之前拉起，配色也在子进程里先于
  控件构建应用，保证和主界面同色。

<details>
<summary>主进程与启动屏之间的 Pipe 消息（改启动屏通信或排查它不动时展开查）</summary>

| 方向 | 消息 | 含义 |
|---|---|---|
| 主 → 启动屏 | `("progress", value, detail)` | 更新进度条与详情 |
| 主 → 启动屏 | `("error", message)` | 初始化失败，转错误展示 |
| 主 → 启动屏 | `("request_geometry",)` / `None` | 请求几何 / 关闭 |
| 启动屏 → 主 | `("geometry", state, geometry_str)` / `("close_requested",)` | 回报几何 / 用户点了关闭 |

</details>

- **切换清场序列**（`app/shell.py::switch_to` 的完整步骤）：切换不重启进程、也不
  复用控件，旧窗口整个销毁后按另一套从头构建；两套界面的关闭都是 `os._exit(0)`，
  没有退出钩子。具体步骤：
  1. 保存设置 → 落盘 `ui_mode` → 登记切换请求；
  2. 摘掉 `WM_DELETE_WINDOW` 协议（否则销毁窗口会误触发关闭逻辑）；
  3. 把根窗口从 customtkinter 的 DPI 跟踪登记里摘除；
  4. 清场：两轮「派发事件队列（单轮上限 2000）→ cancel 掉全部 `after` 定时器」，
     再注入一个只过滤 `invalid command name*` 的 Tcl `bgerror`；
  5. `root.destroy()`。调度循环随后先清掉挂件主题重刷回调表与字体缓存——它们都
     绑在已销毁的解释器上——再进另一套界面的入口。
- **挂件的 DPI**（`ui/mini/dpi.py::virtualized_dpi`）：CTk 建根窗口时已经把整个
  进程设成 per-monitor DPI 感知，挂件要是按 96 DPI 写死像素就会随系统缩放漂移；
  这个上下文管理器在挂件建窗前把**当前线程**切回 DPI 非感知
  （`SetThreadDpiAwarenessContext`，Win10 1607+ 可用），退出时还原（不然重建出来
  的专业界面也会变成非感知）。非 Windows 上是空操作。
- **点阵字号是负数**：正数字号是磅值，会乘 DPI 漂移，落不到内嵌位图上，所以
  挂件统一用负数的像素字号；纯西文判定 `is_latin`，混排时 `split_runs` 分段换
  字体。
- **像素控件与图像**：面板 / 按钮 / 输入框 / 滚动区等控件都是原生 tkinter，由像素
  工厂统一提供；图片显示前走 LANCZOS 缩小 →（可选）合成底色后 MEDIANCUT 量化 →
  整数倍 NEAREST 放大（`ui/mini/pixel.py::pixelate`）。

<details>
<summary>Linux 置顶与 Windows 标题栏暗色的实现细节（置顶或标题栏异常时展开查）</summary>

`ui/hosting/x11.py::state_above` 组装一个 `XClientMessageEvent` 发给 root，
`is_above()` 回读确认，失败就重发一次；能力探测 `available()` 看 root 的
`_NET_SUPPORTED` 里有没有 `_NET_WM_STATE_ABOVE`。Windows 侧的标题栏暗色由 DWM
处理。

</details>

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](dungeon/README.md)（全景）·
  [script](dungeon/script.md)（章节与触发器字段）·
  [prompts](dungeon/prompts.md)（提示词与上下文）·
  [characters](dungeon/characters.md)（人物表与账本）·
  [voice](dungeon/voice.md)（对话语音）·
  [admission](dungeon/admission.md)（进入准入）·
  [scene](dungeon/scene.md)（地点与参照物）·
  [minigame](dungeon/minigame.md)（小游戏）·
  [components](dungeon/components.md)（显示组件）
- **character/**：[README](character/README.md)（全景）·
  [evolution](character/evolution.md)（介入度 / 深度 / 行动点）·
  [time](character/time.md)（恢复结算 / 作息 / 导出）·
  [chat](character/chat/README.md)（话题与好感 / 紧张度）·
  [lens](character/chat/lens.md)（信息视角细节）
- **behaviors/**：[README](behaviors/README.md)（玩家向）·
  [dev-guide](behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](behaviors/hooks-logic.md) / [report](behaviors/hooks-report.md) /
  [character](behaviors/hooks-character.md) / [chat](behaviors/hooks-chat.md)）·
  [example-imperial](behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](world_packs/author.md)（制作与清单）

**单篇**

[地址系统](address_system.md) · [报告生成](report_selection.md) ·
[资源与包体系](resources.md) ·
[挑战包](challenges.md) ·
[剧本编辑器](scenario_editor.md) · [界面双模式与外观](ui_modes.md)（本页） ·
[身材剪影](body_preview.md) ·
[更新检查](update_check.md)

</details>
