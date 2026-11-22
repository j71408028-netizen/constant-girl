# 副本窗口运行时（`dungeon/window/`）：生命周期、宿主边界与调试自动化

> **定位**：会话窗口的**文件地图、生命周期、约束清单（C1–C15）、宿主边界与
> 调试自动化**。
> 引擎核心的分层纪律、模块地图与步进数据流见 [副本引擎架构与术语](dungeon_engine.md)；
> 方案字段与作者向机制（wiki）在 `docs/designs/dungeon/`。
> **改动 `dungeon/` 下任何代码前请先扫 §5 约束清单。**

窗口由 Tkinter 主程序拉起的**独立子进程**承载：父进程（Tk 主程序）经
`ui/hosting/dungeon_spawner.py` 序列化构造参数并 spawn 子进程，会话窗口在子进程里
跑 **imgui-bundle**（`hello_imgui` + GLFW/OpenGL），渲染后端独占子进程（§6）。
窗口起停收在 `dungeon/window/runner.py::WindowRunner.run()`——一次 `hello_imgui.run()`
内部建 GL 后端 / ImGui 上下文 / 视口与帧循环，返回时一并释放，不堵死宿主主循环。
窗口对宿主的全部依赖收敛在宿主端口 `dungeon/window/host.py`，因此 `dungeon/window/` 里没有任何
`tkinter` / `ui.*` import；§5 里约束进程内共存的那几条现在只约束**子进程内部**
（父进程从不 import 副本窗口栈）。

> **术语边界**：本文的「会话（Session）」= `DungeonSessionWindow` 从构造到 `run()` 返回的
> 一次窗口生命周期；「一局（Run）」= 进入正式运行阶段后的一次游戏。入口页返回 / 启动失败
> 只结束 Session，不产生 Run；回放 Session 只重放已有 Run。命名见 [副本引擎架构与术语](dungeon_engine.md) §2。

## 目录

| 节 | 内容 |
|---|---|
| §1 | 文件地图 |
| §2 | 生命周期（构造 / 运行 / 帧循环 / 阶段 / 退出 / 收尾） |
| §3 | 一步会话数据流（窗口侧） |
| §4 | 线程与帧时钟 |
| §5 | 约束清单（C1–C15） |
| §6 | 宿主边界与进程隔离 |
| §7 | 调试自动化 |
| §8 | 自检命令 |

---

## 1. 文件地图

| 文件 | 职责 |
|---|---|
| `dungeon/window/__init__.py` | 用 mixin 组装出 `DungeonSessionWindow` |
| `dungeon/window/base.py` | 构造（`__init__` 只存参数 + 会话初始化）与运行（`run()` 建 UI、`_runner.run()` 托管帧循环、收尾 `_finish_session`）、入口 / 运行阶段切换、关闭路径、视口尺寸（取自宿主端口） |
| `dungeon/window/runner.py` | **宿主运行器** `WindowRunner`：把 `RunnerParams` 的回调挂到窗口原有生命周期语义上（`on_post_init` / `on_load_fonts` / `on_frame_start` / `on_draw` / `on_frame_end` / `on_capture` / `on_before_exit`），`request_exit()` 只置位、帧边界落实 `app_shall_exit`（C1） |
| `dungeon/window/host.py` | **宿主端口** `HostPort`（含无宿主缺省实现）：尺寸/DPI、宿主显隐、事件泵、收尾弹框、活动窗口登记、缺省字体、回放文件选择 |
| `ui/hosting/tk_host.py` | 宿主端口的 Tk/CTk 适配器 `TkHost`——**window 层唯一的 Tk 细节所在地**（自检/自动驾驶用；产品路径走子进程宿主） |
| `dungeon/window/ui.py` | 建窗参数与 `WindowRunner` 组装、**副本字体对接**（经 `dungeon/window/fonts.py` 解析家族名→字体文件，按两档字号建 `dungeon_text_font` 与粗体 `dungeon_bold_font` 供文本组件使用）、每帧自绘（`_draw_frame`：根窗口 → 背景 → 文本 → 工具条 → 帧末顶层浮层）、**上屏游标**（`_reveal_*` 一族，30 字/秒限速真相源，仿流式与真流式共用）、布局自适应（`_relayout`，每帧比对 `io.display_size`）、输入接线（`_handle_input` 每帧读 `imgui.is_key_pressed` / `is_mouse_clicked`）、**F12 过程日志开关**、**A 自动播放 / F2 截图 / O 副本设置**（`toggle_autoplay` / `take_screenshot` / `toggle_settings`，与文本组件工具条按钮共用入口）与 **顶部轻通知窗**（`_notify`，窗口级常驻） |
| `dungeon/window/engine.py` | 推进核心：AI 流式生成、JSON 解析、伤亡结算、回放步进、关闭回调 `_on_close` |
| `dungeon/window/triggers.py` | 触发器判定（所在章节 / 前置 / 条件）、章节进入、章节效果短暂覆盖、插入段落 |
| `dungeon/window/options.py` | 选项触发器：后台生成选项文字并弹出选择弹窗 |
| `dungeon/window/ending.py` | 敏感效果结算与结局生成 |
| `dungeon/window/persistence.py` | 统一收尾 `_finalize`、退出处理 `_handle_exit`、回放 / 报告保存（原子写）、结局索引 `data/user/endings.json`；弹框一律经宿主端口 |
| `dungeon/window/components.py` | 显示组件生命周期接入（构建 / 布局 / 每帧绘制 / 销毁） |
| `dungeon/window/launcher.py` | 入口阶段混入 `DungeonLaunchStages`：动态背景轮播、方案选择面板、结局图标轮播、阶段切换 |
| `dungeon/window/background.py` | 背景图加载 / 旋转 / 模糊 / 淡入淡出 / 纹理更新（含单工作者 `PixelWorker`） |
| `dungeon/window/fx.py` | 窗口视效（闪光 / 振动 / 反色 / 色差分离）：顶层绘制列表 + 视效纹理，帧时钟计时、绝对时间消退，不阻塞其他动作 |
| `dungeon/window/gpu_textures.py` | **GPU 纹理句柄的释放口径**（C15）：`TextureGpu` 是 RAII 句柄，只在 GL 存活时丢；`release()` = 正常路径（`before_exit`），`retire()` = GL 已失效时的兜底仓库 |
| `dungeon/window/frame.py` | 帧时钟 `FrameScheduler`（窗口实例成员 `self._frame`）：`every` / `after` / `cancel` / `call` / `tick` / `drain` / `stop`——window 层唯一的时间源 |
| `dungeon/window/result.py` | `SessionResult` 与原因常量：`run()` 的返回值，替代「读窗口私有属性」 |
| `dungeon/window/fonts.py` | **字体与字号唯一真相源**：两档字号（`TEXT_FONT_SIZE` 24 / `UI_FONT_SIZE` 21 / `BOLD_FONT_SIZE`）、家族名→字体文件映射 `_FAMILY_FONT_FILES` + 平台回退链 + 粗体/衬线候选链 + `resolve_font_files()`；窗口 `ui.py` 与组件包共用同一份 |
| `dungeon/window/component_registry.py` | 显示组件注册表：惰性导入官方常驻组件包、id 解析与回退、参数合并（含 `min/max` 夹取）、按窗口复用实例；`source` 记录实际生效的包来源（外部包经 `ComponentRegistry(pack_dir=...)` 显式覆盖） |
| `dungeon/window/component_pack/` | **官方显示组件包**（窗口层常驻 Python 包）：`__init__.py` 组装 `REGISTRY`，各组件拆在同目录模块（`base.py` 共享常量与文本基类 / `text_gradient.py` / `text_card.py` / `text_nvl.py` / `attr_bar.py` / `proc_log.py`） |
| `dungeon/window/overlay.py` | **覆盖层服务面**（OverlayHandler）：`toggle_overlay / close_overlay / overlay_open / toggle_settings / component`——文本主组件经 ctx 调出对话记录等模态浮层；打开期间进入阅读模态（点击只关闭浮层、剧情推进挂起），H 调出对话记录 / O 调出副本设置 / ESC 关闭。**副本设置面板**：半透明全屏遮罩 + 居中卡片，读写副本独占设置（音量 / 帧率 / 记忆窗口 / 自动回放 / 段落字体 / 组件代管区停靠侧），拖动只改内存、松手 / 关面板时经 `base.set_dungeon_settings` 落盘；遮罩画在根窗口内、卡片在 `end()` 之后作为顶层窗口绘制 |

被本层消费的领域模块：

| 模块 | 用途 |
|---|---|
| `dungeon/prompts.py` | `DungeonPromptBuilder`：系统 / 用户提示词构建 |
| `dungeon/summary.py` | `StorySummarizer`：剧情压缩（概要 + 事实卡 + 关键事件）注入提示词 |
| `dungeon/details.py` | 细节探究提问与回放检索 |
| `dungeon/rules.py` `dungeon/models.py` | 演化规则、触发器条件规则、状态模型 |
| `dungeon/actions.py` `dungeon/audio/chapters.py` | 触发器 / 章节数据模型与动作注册表（见 [副本剧本](designs/dungeon/script.md)） |
| `dungeon/terms.py` | 领域术语与持久化契约常量（见 [副本引擎架构与术语](dungeon_engine.md) §2） |
| `dungeon/schema.py` `dungeon/validate.py` | 方案字段单一真相源 + 结构化校验器 |
| `dungeon/process_log.py` | 过程日志：副本各处的过程消息（章节 / 触发器 / 预生成 / 收尾落盘……）经 `process_log.log()` 进入线程安全环形缓冲，窗口订阅后经帧时钟投递到「过程日志」面板；**副本层禁止再直接 `print`**（`host.py` 的无宿主弹框桩除外） |
| `persistence/scenario_repo.py` | 方案仓库：`data/packs/scenarios/<id>/` 的读写（读写根分离、旧目录自愈迁移、原子写、保存即校验） |

### 1.1 mixin 组装顺序

`dungeon/window/__init__.py`：
`DungeonWindowBase, DungeonLaunchStages, DungeonWindowUI, DungeonStoryEngine,
TriggerHandler, OptionHandler, EndingHandler, DungeonPersistence, ComponentHandler`

| Mixin | 文件 | 职责 |
|---|---|---|
| `DungeonWindowBase` | `base.py` | 窗口生命周期、方案配置加载与启动前校验、会话初始化、关闭请求 |
| `DungeonLaunchStages` | `launcher.py` | 入口阶段：动态背景轮播、方案选择、已达成结局图标循环、开始 / 回放 / 返回 |
| `DungeonWindowUI` | `ui.py` | UI 构建、逐帧自绘、流式文本揭示动画、布局自适应、鼠标 / 键盘输入接线 |
| `DungeonStoryEngine` | `engine.py` | 步进核心：AI 生成、流式分句、属性演化、伤亡结算、收尾回调 |
| `TriggerHandler` | `triggers.py` | 触发器判定、章节进出、章节效果短暂覆盖、窗口视效、插入段落 |
| `OptionHandler` | `options.py` | 选项触发器：后台生成选项文字 → 弹窗 → 记录选择 |
| `EndingHandler` | `ending.py` | 章节敏感效果汇总、结局生成、结局写进回放（`_record_ending`）与回放复现（`_replay_ending`） |
| `DungeonPersistence` | `persistence.py` | 结局结算、回放 / 报告落盘、统一收尾 `_finalize(completed)` |
| `ComponentHandler` | `components.py` | 显示组件实例的构建 / 布局 / 每帧绘制 / 销毁接入 |

MRO 顺序如上。新增方法时注意排在前面的 mixin 会覆盖同名方法；mixin 之间只通过
`self` 上的约定属性通信。

## 2. 生命周期

### 2.1 构造与运行分离

`__init__` 只保存参数并初始化会话内容，不碰渲染后端；`run()` 建 UI、起停收在
`hello_imgui.run()`（帧循环由库驱动）、收尾，并返回 `SessionResult`。
调用方在 Tk 回调里 `result = DungeonSessionWindow(...).run()`，只看返回值就够了
（`result.failed` / `result.cancelled` / `result.succeeded`）；需要细看窗口内部状态时也可以自己留着实例引用
（自动驾驶自检就是这么做的）。

```
__init__
├─ 保存参数（每个构造参数都必须存到 self 上，见 §5-C3）
├─ 回放模式？ → _init_replay()（不建 AI 客户端；按身份记录 / 文件名 / 素材认所属方案）
│   无入口阶段？ → _init_session()（立即初始化）
│   有 scenario_ids？ → 延迟到入口选择后再初始化（_session_initialized 标记）

run() → SessionResult
├─ _register_with_parent()
├─ _start_session()
│  ├─ host.viewport_metrics()  # 宿主仍可见时先取尺寸/DPI（缓存给 _get_initial_viewport_size）
│  ├─ host.hide_window()       # 副本窗口是独立顶层窗口，不藏会两个窗口同时占屏
│  ├─ _build_ui()              # 算建窗/布局尺寸、建 WindowRunner（此时不碰 GL）
│  ├─ _enter_entry_phase() # 仅探索模式：动态背景 + 方案选择面板
│  │   或 _init_components() + _build_components()  # 挑战/回放：直接进会话
│  └─ _runner.run()        # ← 阻塞到关窗（hello_imgui 内部建上下文/视口/帧循环）
└─ _finish_session()    # _frame.stop() → GPU 纹理兜底退役 → 背景工作者 shutdown → 恢复主窗口 → join 结局线程 0.5s
   ├─ _closing 且非入口退出 → _handle_exit()   # 结局已触发时内部还会再 join 最长 15s（persistence._handle_exit）
   └─ _unregister_with_parent()
```

注：入口页「加载回放」不再重开窗口——同一生命周期内由 `_on_entry_replay()` 经端口
`open_replay_file()` 取数据后 `_enter_replay_phase()` 切 `is_replay`。

### 2.2 帧循环

窗口不再自己写循环：`WindowRunner` 把本窗口的钩子挂到 `hello_imgui` 的帧回调上，
每帧顺序固定：`before_imgui_render`（先落实关闭请求，再 `on_frame_start`：
`_pump_host_events()` → `self._frame.tick()`）→ `show_gui`（`_draw_frame` 重建整个
画面）→ `after_swap`（计帧/限帧、`on_capture` 抓帧）；收尾走 `before_exit`。
帧率上限由 `fps_max` 给库（`fps_idling.enable_idling = False` 保证静默期也出帧，
否则帧时钟停摆）；真实节拍由 vsync 决定，自检限帧钩子挂在 `after_swap`
（`ui._on_frame_end`，`GIANTESS_DUNGEON_TEST_FRAMES`）。

- **先 tick 后判关闭**：保证「关闭前最后一次 UI 更新」不丢
- **关闭请求在帧边界才落实**（C1）：`request_exit()` 只置位，`before_imgui_render`
  里统一写 `app_shall_exit`。绝不在回调执行途中直接退出——`hello_imgui` 的
  `confirm_exit` 路径会在帧中途把上下文拆掉（`runner.py` 模块文档详述）
- **输入接线在帧线程**：立即模式没有回调线程，`ui._handle_input` 每帧读
  `imgui.is_key_pressed` / `is_mouse_clicked`，天然与渲染同线程（§4）

### 2.3 入口阶段 → 运行阶段（Run，探索模式）

两者共享同一次 Session 生命周期（同一个 ImGui 上下文 / 视口 / 根窗口），切换不重建。

| 动作 | 路径 |
|---|---|
| 进入入口 | `_enter_entry_phase()` 启动三组后台轮播（背景图随机、结局图标、Ken Burns 帧级运动），构建右下角方案面板 + 左下角结局面板 |
| 点「开始副本」 | `_enter_dungeon_phase()` → 冻结背景 → 销毁入口 UI → `_load_session_config()`（加载配置、校验 error 级阻止进入、扣 AP、建 AI 客户端与提示词）→ 构建组件 → 显示文本容器 → `check_triggers()`。任一步失败置 `_launch_error` 并 `_close_loop()`，由调用方在 Tk 侧弹错误框 |
| 点「加载回放」 | 冻结背景后经宿主端口 `open_replay_file()` 取数据；取不到就**留在入口页**，取到就在同一窗口生命周期里切 `is_replay` |
| 点「返回」 | `_close_loop()` 关窗，不视为会话结束（见 `_exit_from_entry`） |

阶段标记（都定义在 `__init__`，勿随意改名）：

| 标记 | 含义 |
|---|---|
| `_is_entry_phase` | 入口页可见中；事件回调据此忽略点击 / 按键 |
| `_entry_started` | 已完成一次进入选择，防止二次进入 |
| `_session_initialized` | `_init_session()` 是否已执行 |
| `_exit_from_entry` | 入口阶段退出（返回 / 加载回放 / 启动失败），`_finish_session` 据此跳过 `_handle_exit` |
| `_closing` | 已请求关闭；`_on_close` 与 `_close_loop` 都会置位 |
| `_session_running` | `run()` 重入保护（宿主事件泵会回到调用方回调，避免嵌套建第二个窗口） |

### 2.4 退出路径

| 入口 | 路径 | 说明 |
|---|---|---|
| 入口页「返回」 | `_on_entry_cancel` → `_close_loop()` → `_request_close()` 置位 → `before_imgui_render` 帧边界写 `app_shall_exit` | 帧回调继续到库决定退出，走 `before_exit` → `_on_close` 清理 |
| 会话中点窗口 X | GLFW 原生关闭 | 库关窗后走同一条 `before_exit` → `_on_close` 清理（**不再依赖 exit callback**，见 §5-C6） |
| 回放播完 | `_replay_next_step` → `_request_close()` | 同「返回」 |
| 会话未触发结局就退出 | `_handle_exit()` → `_confirm_abandon()` → `_finalize(completed=False)` | 先确认放弃；**不**写 `endings.json`、不记挑战达成、不创建角色、不落盘任何回放或报告 |
| 宿主关闭整个应用 | `MainWindowManager.on_closing` → 句柄 `request_close()`（协议请子进程收尾）→ `os._exit(0)`；父进程退出即管道断开，子进程的看护线程立即终结 | 父进程从不加载副本窗口栈（imgui-bundle）；子进程收尾随管道断开结束 |

三条程序化关闭路径都归到 `_request_close()`（见 §5-C1）。

### 2.5 收尾（`_finalize`）

唯一入口 `persistence.py::_finalize(completed, reason)`，`_finalized` 标记保证幂等。

| 路径 | 调用点 | `completed` |
|---|---|---|
| 结局生成结束（章末终止 / 旧 `ending` 触发器） | `EndingHandler._generate_ending` 的 finally | `True` |
| 会话中直接点 X 退出（未触发结局） | `_handle_exit` | `False` |
| 点 X 时结局已触发、文本仍在生成 | `_handle_exit`（join 超时分支） | `True`（结局文本兜底为结局名） |
| 生成异常 `engine._note_session_error` | 不结束会话，异常记入 `_session_errors` 并显示在故事区 | — |
| 连续空响应（重试一次仍为空） | `engine._drop_empty_step` + `_note_session_error`：撤回本段占位，**不**写对话历史、不推步数、不写回放、不跑触发器，提示后可再点一次 | — |

- `completed=True`：结算结局增量 → 写 `data/user/endings.json` 结局索引 → 自动保存开关打开时保存回放与报告（**没有角色先问一句**，玩家拒绝即不保存，也不会凭空建角色）。
- `completed=False`：**不**结算、**不**写 `endings.json`、**不**记挑战达成、**不**落盘任何回放或报告。未达成结局的一局没有可保留的形态：本版不支持中途存档，也就没有接续，留一份接不上的半成品只会让玩家手里多一个读不懂的文件。
- 退出确认：`_handle_exit()` 在未完成分支先调 `_confirm_abandon()` 告知「退出即放弃、无法接续」。会话毫无内容时不打断。窗口此时已销毁，玩家即使点「否」也回不到游戏里，因此只补一句「这一局没有保留」。
- 落盘位置：有角色（探索模式）写 `data/archives/<角色>/回放|报告`；无角色或挑战模式写 `data/user/replays`、`data/user/reports`。两条路径都只覆盖「走到结局且选择保存」的一局。
- 回放文件仍是 `[记录, ...]` 数组、后缀仍为 `.replay.json`，回放加载与档案导出照常识别。

收尾语义与「能不能接续」的关系（为什么未完成局不落盘）见
[副本引擎架构与术语](dungeon_engine.md) §6。

### 2.6 GPU 纹理句柄的收尾口径（C15）

`hello_imgui.TextureGpu` 是 **RAII** 句柄：丢掉最后一个 Python 引用就去释放底层 GL
纹理，所以**只能在 GL 存活时丢**。窗口层有六处句柄容器（背景 / 窗口工具条 / 结局
图标 / 视效覆盖层 / 组件工具条 / 小游戏贴图），一律走 `dungeon/window/gpu_textures.py`
的两个出口：

| 出口 | 时机 | 行为 |
|---|---|---|
| `ui._release_gpu_textures()` → `gpu_textures.release()` | `before_exit`（**GL 后端与 ImGui 上下文仍存活**，库收尾前最后一站） | 一次性收走全部句柄并丢弃引用 ⇒ RAII 当场释放显存 |
| `ui._retire_gpu_textures()` → `gpu_textures.retire()` | `_finish_session`（`hello_imgui.run()` **已返回**） | 兜底：把残余句柄挂进进程级仓库**保住引用不让析构跑**；正常路径走不到（走到会记一条告警日志） |

坑在容器：清空一个 `{key: TextureGpu}` / `[TextureGpu]` 就等于丢引用，而「清空容器」
看着人畜无害，很容易被顺手写进 `_finish_session`——那样每局收尾都会在驱动层段错误
（2026-10 在 Linux 上实测**每局必崩**，与软/硬 GL 无关）。因此
`ui._drain_gpu_textures()` 是**唯一**的句柄清单，`_retire_gpu_textures()` 必须排在
`_destroy_components` / `_destroy_overlays` / `_window_fx.shutdown`（这三步会清空容器）
之前；`tests/check_gpu_texture_lifetime.py` 机械守住清单、两个出口与调用次序。

## 3. 一步会话数据流（窗口侧）

```
点击 / 空格（_on_mouse_click → _on_next_step）
├─ 覆盖层打开 → 阅读模态（点击只关覆盖层）
├─ 0.4 秒内连点 → 吞掉（_click_debounced，实时与回放共用）
├─ 回放（is_replay）→ 与实时同一套点击机：先 _try_advance_paragraph，
│     队列见底才 _replay_next_step；后者循环跳过不可见记录（章节进入 /
│     跳转 / 效果覆盖 / 视效），一条可见记录（正文 / 选项行 / 小游戏行 /
│     结局）消化一次点击
├─ pending_option / pending_ending 存在 → 打断
├─ 上屏游标三态判定（_try_advance_paragraph）
│  ├─ 已上屏 < 5 字 → 吞掉本次点击（防误触 / 防抢在游标起步前切段）
│  ├─ 当前段未补满 100% → 补满并停住，不切段（再点一次才切段）
│  └─ 已补满 → 有排队显示段落就揭示下一句（_reveal_pending_unit）
├─ 有非延迟插入段 → 直接消费显示
└─ _generate_next_text()：后台线程（领域侧的完整链路见 dungeon_engine.md §5）
```

| 概念 | 说明 |
|---|---|
| **逻辑段落 vs 显示段落** | 一次 AI 输出（约 100 字）是一个逻辑段落，属性演化、回放、剧情压缩、对话历史都以它为单位；内置分句器（`dungeon/splitter.py`）把它切成若干显示段落（换行、句末标点、分号为断点；句中破折号、省略号与强调引号保留、不断句），逐句展示只为阅读节奏。`@说话人@` + 引号构成台词块：块内按句末标点断句、每段继承说话人，首尾引号不进显示文本（落盘仍保留引号以区分台词）。队列耗尽后下一次点击才触发新的 AI 调用；插入触发器的段落走同一条仿流式管线 |
| **上屏游标（唯一速度真相源）** | `ui.py` 的 `_reveal_*` 一族：仿流式（预生成 / 固定文本 / 插入段）与真流式共用**同一条限速**，恒定 `_REVEAL_CHARS_PER_SECOND = 30 字/秒`（帧任务 `_REVEAL_TICK_SECONDS = 0.05` 即 20 Hz，每 tick 约 1.5 字；`frac` 小数累加器消除 1/1/2 的抖动）。状态字典 `self._reveal = {item, target, pos, frac}`，`pos` 是唯一进度真相源。**真流式与仿流式的区别只在 target 何时给定**：仿流式一次给全（`_reveal_start`），真流式的 chunk 到达只 `_reveal_extend` 延长 target、**不直写 item 文本**，游标按固定速率追赶——因此 AI 吐字再快，玩家看到的上屏节奏恒定，分句器也始终有一份领先缓冲，不需要为上屏等待。游标走到 target 末尾时**自我注销**（`self._reveal = None`）并调 `_on_reveal_finished` 登记自动播放的到期时刻，点击补满（`_reveal_snap`）同样算「本段播完」（只有 `_reveal_start` 顶掉旧游标那一次例外）。**全文已知的上屏只有一个入口**：`_present_paragraph`（`split_full_text` 切显示段落 → 首段起游标、其余入队、首段定稿时朗读），固定文本段、插入段与回放步进都走它；真流式因为文本是逐块到达的，走 `_update_stream_units` 那条 |
| **点击三态机** | `_try_advance_paragraph`：① 已上屏不足 `_REVEAL_MIN_CHARS = 5` 字（≈0.17 秒）→ 吞掉点击，游标与队列都不动；② 未补满 → `_reveal_snap` 补满到 100% 并停住，**不切段**；③ 已补满（自然播完或上次点击补满）→ 才揭示队列里的下一显示段落。这个顺序保证「狂点」最多推进一个单元，不会掀翻分句器队列（`check_reveal_cursor.py` 守此契约） |
| **说话人写法（方案二选一）** | 方案级字段 `speaker_notation`（`dungeon/speaker_notation.py`）二选一，选定后全方案强制、不许混用，与 `coupling_level`（玩家身份）、`text_component`（显示投影）三者正交：`tagged` 要求 AI 在对话句句首写 `@说话人@`（规则见 `TAGGED_SPEAKER_RULE` / `SPEAKER_STABILITY_RULE`），系统提示另有全段生效的写法声明；`literary` 用自由文学写法，运行时在定稿（`engine._normalize_ai_text`）与流式 chunk 入口用 `strip_speaker_markers` 兜底剥掉误生成的标记。**写法不丢结构化 speaker**：`tagged` 下分句器把标记解析进 `DisplayUnit.speaker` → `story_history` 的 `speaker` 键，UI 渲染名牌、语音导演朗读对话句；`literary` 下通道保留、等结构化响应接上即可复用。`validate.py` 静态扫描作者正文里越界的 `@说话人@` 报错，回放 meta 另存记法版本。落盘正文（回放 / 报告 / 概要）经 `strip_speaker_markers` 剥离标记；回放额外存一份 `display_text`（只有原文真带显示层标记时才写，回放靠它把说话人与高亮还原）。音色与开关见 [对话语音](designs/dungeon/voice.md) |
| **高亮标记** | 正文里的成对 `==`（`splitter.HIGHLIGHT_MARK`）是高亮语法，**以显示段落为渲染单位**：分句器把标记从正文里摘掉、算出逐字符高亮掩码，某个显示段落只要被高亮区盖住就整段用 `highlight_color` 渲染。语法对三处文本一视同仁：固定文本章节的脚本段落、插入触发器的段落、以及 AI 生成的句子（提示词规则 `coupling.HIGHLIGHT_MARKER_RULE`）。未闭合的开标记作用到逻辑段落末尾；落盘（回放 / 概要 / 对话历史）用 `strip_display_markers` 剥净。旧版插入触发器的 `highlight: true` 仍然按整段高亮复现，编辑器保存时迁成语法 |
| **文本显示所有权** | 文本主组件由方案配置 `text_component` 字段**三选一**（`dungeon.schema.TEXT_COMPONENT_IDS`）：`text` **底部渐变式**、`text_card` **底部卡片式**、`text_nvl` **全屏 NVL**（可选衬线字体、可滚轮回看）；`components` 列表只放其余组件，主组件先建、z 序在底。行首标签只显示说话人（类型前缀是内部属性不上屏，过程日志面板可见），继续点击用闪烁 ▼ 提示。接管期间（`owns_text_display = True`）`_update_text_display` 跳过内置 `text_container` 管线、转调组件刷新链；`text`/`text_card` 屏幕只呈现当下几句，完整历史由回放/报告承接。三种组件的版式与参数见 [显示组件](designs/dungeon/components.md) |
| **覆盖层服务面** | 窗口向文本主组件提供受控调用：`ctx.toggle_overlay("log")` 调出**对话记录**（全量 `story_history` 快照、可滚动）、`ctx.toggle_overlay("settings")` / `ctx.toggle_settings()` 调出**副本设置**、`ctx.component(cid)` 只读访问兄弟组件实例；写操作与组件生命周期仍由窗口集中管理，主组件只拿到调度权而非所有权。覆盖层打开时为阅读模态：点击只关闭覆盖层（`ui.py::_on_mouse_click`，点在设置卡片内不算外部），空格/回车推进在 `_on_next_step` 入口挂起 |
| **组件服务面（C13）** | 组件访问窗口的唯一入口集中在 `components.py::ComponentHandler`：几何 `component_viewport()`、帧时钟 `schedule / schedule_every / cancel_task`（**不碰 `self._frame`**）、状态查询 `session_waiting_for_input()`（继续指示用：生成中 / 游标未走完 / 分句队列还有货 / 选项 / 结局都不算等待）/ `component_autoplay_on()`、字体 `text_font_tag() / bold_font_tag()`、顶部让位 `component_top_inset()`（聚合各组件的 `top_inset(ctx)` 可选钩子，与构建顺序无关）。契约的可执行版本是 `check_component_pack.py` 的替身 ctx——它**只**实现服务面，组件越界（读私有）在冒烟与 AST 扫描里都会失败 |
| **组件代管区（slot）** | 文本主组件在 `layout` 阶段生成 `dungeon.window.layout.Slot`：几何 + `SlotStyle` + 可接纳的角色 / 形状 / 容量。`ComponentHandler` 的布局分两遍：先排文本主组件并收集代管区，按子组件声明的 `roles` / `shapes` 机械匹配并发布 `component_rect(cid)` / `component_slot(cid)`，再排其余组件。官方组件的代管区（`card_footer` / `scrim_band` / `nvl_header` / `card_side` 等）、`dock_side` 停靠侧与毛玻璃卡片的机制说明见 [显示组件](designs/dungeon/components.md) §3；停靠哪一侧是**窗口视觉设置** `dock_side`（`dungeon_settings.json`，副本设置面板里由玩家实时改、改完立即重排组件），不是文本组件的方案参数，组件经服务面 `ctx.component_dock_side()` 读取 |
| **细节探究（窗口侧接线）** | 本章第一段写完后 `_start_detail_query` 后台问一次（每章一次，结果整章有效），此后每段生成前按「正文是否提到线索对象」触发注入；提问内容、方面白名单与注入闸门的机制见 [副本提示词](designs/dungeon/prompts.md) §6，领域出口在 `dungeon/details.py`（dungeon_engine.md §4） |
| **预演化（预生成）** | 步进收尾后若下一次点击必然触发生成（无选项/插入/结局排队），立即后台预生成下一段，缓存 `(turn, 生成前历史, 原始响应, 段落类型)`；玩家点击时 `_take_pregen_for_next` 直接采用（在途则等待收养，不重复发请求），首句仿流式揭示。选项选择后、插入段消费后各补射一次；`build_turn` 是纯构建，预生成失败自动回退实时路径且无需还原会话状态。调用次数不变，只是提前发出 |
| **章节 / 触发器 / 结束章节** | 会话开始先 `_enter_start_chapter()` 进入起始章节再 `check_triggers()`；触发器判定顺序、同位置派发、结束章节冻结与超限兜底的语义见 [副本引擎架构与术语](dungeon_engine.md) §5，字段见 [副本剧本](designs/dungeon/script.md) |
| **剧情压缩（窗口侧接线）** | `StorySummarizer` 按块（默认 20 段）与换章时机压缩；`build_turn` 注入「全部压缩概要 + 关键事实 + 关键事件」，近期原文由对话历史逐字携带、不再注入。**按块压缩走异步**：主线程 `detach_chunk` 切块、后台线程 `compress_chunk` 调 AI、写回按序号保序；换章 / 结局前的 `flush_chapter` 仍同步并先等在途块落地。机制与参数见 [副本提示词](designs/dungeon/prompts.md) §4 |
| **回放模式** | 不建 AI 客户端；`_init_replay` 用 `dungeon.replay.parse_all` 把记录解析成 Record（坏记录丢弃，旧格式的 `goto` 平级环境键展开成章节记录），紧接着 `_resolve_replay_scenario` **认回放所属的方案**——章节背景 / 音乐 / 结局图标都是相对方案目录的路径，少了 `scenario_id` 这些素材一律解析失败。判定链：调用方显式给的 `scenario_id` > 身份记录 `kind:"meta"` 的 `scenario.id`（且方案还在）> user 回放文件名前缀 > 素材路径在全部方案目录里命中计数最多者（最后一级只照顾不认识 `meta` 的旧文件）；`meta.assets` 的字节数与现盘对不上时只记一行过程日志。`_replay_next_step` 逐条分派（ChapterRecord / TriggerRecord / EndingRecord / 步进记录），记录的语法与容错见 [副本剧本 §9.3](designs/dungeon/script.md)。**播放节奏与实时同构**：正文走 `_present_paragraph` 的限速游标与分句队列，点击走同一条三态机（含 0.4 秒防抖），一次点击必有反应；自动播放对回放一样有效。**朗读走同一条管线**：`_configure_voice` 在 `_init_replay` 里照方案装配，记录的 `display_text` 交给 `_present_paragraph`，说话人随之还原。**步数也随记录还原**：`_replay_step` 把 `record.step` 写回 `dungeon_state.total_steps`。`TriggerRecord` 的 `option` / `mini_game` 动作回放不弹窗，改在故事区补一行「【选择】…」/「【小游戏】…」并占一次点击（只活在显示层，不进记录）。刚进入回放的那一次调用带 `auto_close=False`：整份记录只有环境、没有正文时不自动关窗 |
| **过程日志（proc_log 组件）** | 右上角日志面板是官方组件包里的 `proc_log` 组件：方案在 `components` 里声明才构建（`_default` 已声明），默认收起，**F12** 切换展开 / 收起。数据源是 `dungeon/process_log.py`：组件 build 时订阅并取走缓冲积压（构造 / 会话初始化阶段的报错也会补显），此后任意线程的 `log()` 经订阅回调 → `ctx._frame.call()` 进主线程追加（上限 300 行，自动滚底）；组件 destroy 时退订。方案未配置该组件时按 F12 弹通知「日志查看已禁用」 |
| **文本组件功能工具条** | 三种文本组件各自挂一条悬浮工具条（播放 A / 截图 F2 / 过程日志 F12 / 副本设置 O，与快捷键等效）。自动播放由帧时钟任务采样（`toggle_autoplay` 挂 `every(0.2)`），真正的推进节奏**事件驱动**：上屏游标自然走完时登记 `_advance_due = now + 0.5s + 0.012 × 句长`，`_autoplay_tick` 三重检查（会话可推进 → 游标已收尾 → 停留期已过）后才推进，长句多停一点。**分句队列不是阻塞项**：只剩「生成中 / 结局 / 选项」三类硬阻塞（`_session_can_advance`）——队列里还有没上屏的显示段落时自动播放要接着播完。点击补满与整句直出的行（回放的选择 / 小游戏行、小游戏结算行）同样登记 `_advance_due`。截图经 `RunnerParams.callbacks.after_swap` 的 `on_capture` 钩子（`glReadPixels` 抓整帧）交给 `PixelWorker` 存到 `data/user/screenshots/`（通知延后弹出）。窗口 `_on_mouse_click` 用 `toolbar_hovered()` 区分点按钮与点屏幕推进剧情 |
| **轻通知窗** | 主窗口顶部居中的通知条（`ui.py::_notify`），窗口级常驻、**不受组件配置影响**；显示约 3 秒自动隐藏（`after` 同 key 任务互斥，连续通知覆盖前一条并重置计时）。副本内需要「提示但不必确认」的场景都可用它 |

## 4. 线程与帧时钟

**只有主线程（帧循环所在线程）允许直接调用 imgui API。** 后台线程一律通过
`self._frame.call(fn, *args)` 投递；队列由帧回调每帧 `before_imgui_render` 里
`tick()` 时 `drain()` 清空。
会话收尾 `_finish_session()` 会 `_frame.stop()`，此后 `call()` 返回 `False` 而不是抛异常，
后台线程不必再轮询 `_closing`。

**输入只在帧循环线程上落地**：立即模式没有"回调线程"——`ui._handle_input` 每帧读
`imgui.is_key_pressed` / `is_mouse_clicked`，鼠标与键盘天然在帧线程执行，上面的
单线程约定不需要任何"收拢"就成立。自动驾驶 `native-input` 场景用
「SendMessage 直投 WM_KEYDOWN 触发真原生按键」锁住这条性质。

帧时钟 API（`dungeon/window/frame.py::FrameScheduler`，窗口实例成员 `self._frame`）：

| 方法 | 用途 |
|---|---|
| `every(interval, fn, key=...)` | 周期性任务；同 key 天然互斥，掉帧不补跑 |
| `after(delay, fn, key=...)` | 一次性延时任务 |
| `cancel(key)` | 按 key 取消（替代 `threading.Timer.cancel`） |
| `call(fn, *args)` | 后台线程投递：下一帧 drain 时在主线程执行 |
| `tick(now=None)` | 帧循环每帧调一次；先跑到期任务，再 drain |
| `stop()` | 会话收尾：清空任务与队列，之后 `call` 一律丢弃 |

任务类型分工：

| 类别 | 成员 | 为什么还留在线程里 |
|---|---|---|
| **帧任务**（不开线程） | 入口背景轮播、结局图标轮播、resize 防抖、Ken Burns、仿流式出字 | 纯计时，退出不需要 join |
| **AI 类**（后台线程） | AI 流式生成、细节提问、选项文字生成、结局生成 | 真正吃 IO/CPU，会阻塞数秒；结果经 `_frame.call()` 回主线程 |
| **像素类**（单工作者） | `PixelWorker`（背景重采样与淡入淡出的像素混合） | `Image.resize` / `Image.blend` 是 CPU 密集；**节拍仍由帧任务决定**，工作者只干脏活 |

规则：窗口关闭的判定只在主线程；后台线程永远不要直接调 imgui（含 `app_shall_exit`），
要关窗就 `_frame.call(self._close_loop)`。`join(timeout=...)` 只允许带超时，且不要在渲染回调内 join
（会阻塞帧处理，最长约 1s 的假死）。

## 5. 约束清单

| 编号 | 约束 | 原因 / 出处 | 验证 |
|---|---|---|---|
| **C1** | 任何「程序主动关闭副本窗口」都必须走 `base._request_close()`，业务代码不直接退（不写 `app_shall_exit`、不调库的退出函数）；`runner.request_exit()` 只置位，由 `before_imgui_render` 帧边界统一落实 `app_shall_exit` | 在回调执行途中直接退会让 `hello_imgui` 的 `confirm_exit` 路径在帧中途拆掉上下文。迁移前 DPG 直接 `stop_dearpygui()` 同样收尾不干净，当时的补救是把停止挪回帧边界——本约束即那条纪律的 imgui 版 | `python tests/check_dungeon_window_contract.py`（`hello_imgui.run` / `app_shall_exit` 只许出现在 `runner.py`）；`python scripts/dungeon_autopilot.py --scene session-close --isolate`（含 `--repeat 2`）；真应用手测「进入副本 → 返回 → 再进入副本」 |
| **C2** | 窗口的 GL 后端 / ImGui 上下文 / 视口生命周期**全权交给 `hello_imgui.run()`**：进程内不手动建 / 毁上下文，`run()` 返回即全部释放，不需要保活视口；收尾（恢复主窗口、弹框）在 `_finish_session` 里、`run()` 返回之后做，与子进程的 GL 栈生命周期无关 | 迁移前 DPG 的进程单例上下文 + GLFW 终止会让 Tk 根窗口失去窗口级命令（`destroy()` / `withdraw()` 硬崩 0xC0000005），才需要「保活视口」把进程留在健康状态。imgui 的 runner 把上述全收进库内部、会话又跑在独立子进程里，那条补救链整体退场 | `tests/smoke_switch.py` 第 2/5 轮（真跑两局副本 + 三次切换，断言父进程始终没在本进程启动副本窗口）；`scripts/dungeon_autopilot.py` |
| **C3** | `__init__` 的每个构造参数都必须存到 `self` 上 | `_init_session()` 在入口阶段**迟到执行**（点「开始副本」时才跑），此时局部变量早已不可见；曾因漏存 `merged_quips` 导致「开始副本」必然 AttributeError | 构造后读属性 / `entry-start` 场景 |
| **C4** | 跨线程 UI 更新走 `self._frame.call()`；禁止后台线程直接调 imgui | 帧时钟是窗口实例成员（随会话创建与停止），不是模块级单例；`stop()` 后 `call()` 返回 `False` 不抛异常 | `dungeon_autopilot.py` |
| **C5** | 计时类逻辑不开线程，用 `every` / `after` 帧任务 | 旧实现各自靠 `_closing` 标志轮询退出、收尾时逐个 join；现在退出不需要 join | `python tests/check_dungeon_window_contract.py`（禁 `threading.Timer`）；场景结束时断言 `threading.enumerate()` 无非 daemon 残留 |
| **C6** | 后端迁移的已知差异与已退役的 DPG 怪癖见 §5.1 | 实测结论 | 手测 + 自动驾驶 |
| **C7** | 入口阶段与会话页共用 `bg_texture` / `bg_image_item` | 进入会话时 `_freeze_background` 把冻结帧设为 `_bg_pil_full`，后续 relayout 沿用冻结画面 | 手测入口 → 会话 |
| **C8** | window 层不许 import `tkinter` / `customtkinter` / `ui`；宿主能力一律经 `HostPort`，见 §5.2 端口表 | 换 UI 框架只需换适配器；自检不再需要打桩 `ui.ctk.dialogs` | `tests/check_dungeon_layering.py` |
| **C9** | 构造 / 复制 `DungeonState` 只用关键字参数 | 字段顺序会随迭代变化；`clone()` 曾按位置传参导致伤亡数组被填成步长浮点数，于是**每一步** `_finish_step` 都抛 `'float' object is not iterable`——故事看着还在出字，但总计数不增长、触发器与结局永不触发 | 断言「回放记录是否增长」 |
| **C10** | 写盘一律用原子写（`persistence/json_store.py`） | 半截文件不可恢复，`.bak` 是唯一回退；回放 / 报告按时间戳命名、本来不会被覆盖，调用时传 `backup=False` | `tests/check_dungeon_finalize.py` |
| **C11** | 术语不混用：`scenario_*` = 方案（定义），`run_*` = 一局（执行），`session_*` = 窗口会话 / 呈现；`dungeon_*` 是产品 / 历史命名，不是精确的 Run 后缀 | 见 [副本引擎架构与术语](dungeon_engine.md) §2 与 `dungeon/terms.py` | `tests/check_scenario_naming.py` |
| **C12** | 任何 Tk 交互前必须调用 `self._discard_pending_quit()` | 用户通过视口原生关闭键（X）退出时，GLFW 销毁原生窗口会导致 Windows 在本线程队列中留下一条 `WM_QUIT`；它不会被 Tk 消费，却会让 Windows 停止合成 `WM_TIMER`，造成随后的收尾提示模态对话框以及主窗口所有 `after` 计时器彻底收不到事件而表现为**弹出提示对话框后主窗口卡死**；收尾时在 `show_window()` / 弹框前由端口抛弃该残留消息 | `python scripts/dungeon_autopilot.py --scene native-close --isolate` |
| **C13** | 组件只经**组件服务面**访问窗口（`ctx.component_viewport / schedule / schedule_every / cancel_task / session_waiting_for_input / component_autoplay_on / text_font_tag / bold_font_tag / component_top_inset / component`），不得读窗口私有属性（`_dpi_scale` / `_layout_w` / `_frame` / `_autoplay`…） | 组件 ctx 就是窗口实例，摸私有零成本，一旦窗口侧改名即静默 AttributeError；契约的可执行版本是守卫里的**替身 ctx**（只实现服务面）与 AST 越界扫描 | `tests/check_component_pack.py` |
| **C14** | 会话收尾不许留下本代窗口：`hello_imgui.run()` 返回后，本进程不应再有标题以 `副本模式` / `回放模式` 开头的顶层原生窗口 | 迁移前 DPG 的 `destroy_context()` **不销毁**视口对应的 GLFW 原生窗口（`IsWindow/IsWindowVisible` 在 destroy 之后仍为真）。典型 DPG 程序感知不到，但本程序收尾后仍跑 Tk 主循环，那个不再响应的副本窗口就**留在屏幕上**——用户报的「启动界面点返回后卡死」，且每局累加一个。imgui 的 runner 自己销毁窗口，本条改为**回归断言**：无论后端怎么实现，收尾都不许留下这一代窗口 | `python scripts/dungeon_autopilot.py --scene entry-cancel` / `--scene session-close`（断言「返回/关闭后不再新增副本视口原生窗口」） |
| **C15** | `hello_imgui.TextureGpu` 等 GL 资源句柄**只在 GL 存活时释放**：统一走 `dungeon/window/gpu_textures.py` 的 `release()`（`before_exit`，`ui._release_gpu_textures`）；`hello_imgui.run()` 返回后的 `_finish_session` 只许 `retire()` 兜底保住引用。六处句柄容器（背景 / 窗口工具条 / 结局图标 / 视效覆盖层 / 组件工具条 / 小游戏贴图）一律经 `ui._drain_gpu_textures()` 收走，`_retire_gpu_textures()` 必须排在 `_destroy_components` / `_destroy_overlays` / `_window_fx.shutdown` 之前 | `TextureGpu` 是 RAII：丢最后一个引用即释放底层 GL 纹理。`run()` 返回后 GL 后端与 ImGui 上下文已随库释放，此时再丢引用会去解引用失效后端，在驱动层**直接段错误**——2026-10 在 Linux 上实测**每局副本收尾必崩**（软/硬 GL 都复现），成因是组件基类的 `destroy` 在 `_finish_session` 里清了工具条图标纹理。看着人畜无害的「清空容器」正是丢引用 | `python tests/check_gpu_texture_lifetime.py`（六处容器清单 + `release`/`retire` 口径 + `_finish_session` 次序与 `_on_before_exit` 释放的 AST 断言）；`scripts/dungeon_autopilot.py`（真窗口收尾后退役仓库必须为 0） |

### 5.1 C6：后端差异与已退役的 DPG 怪癖

现行后端是 imgui-bundle（`hello_imgui` + GLFW/OpenGL）。立即模式与 DPG 的保留模式
有几处必须记住的差异：

| 项 | 现状（imgui 立即模式） |
|---|---|
| 画面构建 | 没有常驻控件树：`_build_ui` 只备参数与建 `WindowRunner`，`_draw_frame` 每帧重建全部浮层；「改属性找控件」一律变成「改状态、下帧重画」 |
| 浮层顺序 | 根窗口铺满客户区，入口方案面板 / 工具条 / 通知 / 小游戏舞台必须是根窗口 `end()` 之后的**顶层窗口**，且用 `_panel_flags`（不带 `no_bring_to_front_on_focus`），否则被根窗口整个盖住 |
| 字体 | `hello_imgui.load_font` 只能在 `load_additional_fonts` 回调里调（放 `post_init` 会 access violation）；`push_font(font, base)` 传**基础字号**（库按 dpi_factor 放大） |
| 建窗尺寸 | `window_geometry.size` 是 96-PPI 逻辑点 = 宿主客户区物理像素 ÷ `_dpi_scale`（R7 定标，见 `ui._window_create_size`） |
| 背景 / 视效纹理 | `hello_imgui.TextureGpu` 句柄持有即持有 GPU 资源：换图**先建新句柄再丢旧句柄**，避免中间帧采样到已释放纹理 |
| 截图 / 反色 / 色差抓帧 | 走 `RunnerParams.callbacks.after_swap` 的 `on_capture`（`before_imgui_render` 阶段读后备缓冲是全黑，R13） |
| 静默期出帧 | `fps_idling.enable_idling = False`（否则帧时钟停摆）；`fps_max` 只是高刷屏封顶，节拍由 vsync 定 |
| 关窗 | 点 X 与程序侧关窗共用一条路径（库关窗 → `before_exit`）；`confirm_exit` 显式置 None，不弹库自带确认框 |

DPG 时代的怪癖（`dpg.add_child_window(no_scrollbar=)` 创建时不生效、viewport drawlist
不渲染、动态纹理同 tag 重建复用旧 GL 存储导致花屏、`set_exit_callback` 是「最后一帧」
语义、控件回调默认派发到工作线程需要收拢、`destroy_context()` 不销毁视口原生窗口、
保活视口……）**已随迁移整体退场**。

与后端无关的一条旧坑仍在：入口背景图收集 `collect_dungeon_images` 按规范化路径
去重（同一图会经副本仓库相对根与自由副本绝对根各采一次）；只有一张图时轮播禁止
`random.randint(1, n-1)`（low>high 会抛异常杀死线程）。

### 5.2 C8：宿主端口方法表

`dungeon/window/host.py::HostPort`（缺省实现 = 无宿主），Tk 实现 `ui/hosting/tk_host.py::TkHost`，
子进程实现 `ui/hosting/dungeon_child_host.py::ChildHost`（弹框/文件框走协议请父进程代答，见
§6）。

| 端口方法 | 用途 | Tk 实现 |
|---|---|---|
| `viewport_metrics()` | `(视口宽, 视口高, dpi_scale, 宿主客户区宽, 高)` | `winfo_toplevel/winfo_id/winfo_fpixels` + `GetAncestor`/`GetDpiForWindow`/`GetClientRect`（子进程：父进程 spawn 前量好随载荷传入） |
| `hide_window()` / `show_window()` | 副本视口显示时藏起宿主、关闭后恢复 | `withdraw` / `deiconify` + `lift` |
| `pump_events()` | 帧循环里处理一次宿主事件（宿主不冻结） | `widget.update()` |
| `discard_pending_quit()` | 丢弃视口原生关闭（X）留下的退出残留消息（见 §5-C12） | Win32 下 `PeekMessageW(..., WM_QUIT, WM_QUIT, PM_REMOVE)` |
| `dialog(kind, title, message)` | 收尾提示 / 询问（`info`/`warning`/`error`/`ask`） | `ui.ctk.dialogs.*` |
| `open_replay_file()` | 入口页加载回放；返回记录列表或 `(记录, 文件路径)`（路径供文件名认方案），缺省实现返回 `None`（等价于用户取消） | `filedialog` + JSON 校验（解析在适配器侧） |
| `register_active_window()` / `unregister_active_window()` | 让宿主整体退出时能找到活动副本窗口 | 沿 `master/parent` 链找持有 `_active_dungeon_window` 的主窗口 |
| `default_font()` | 段落字体缺省家族 | `ui.ctk.fonts.dungeon_font_default()` |

用法：

```python
DungeonSessionWindow(..., host=TkHost(self)).run()   # 探索模式 exp_frame / 挑战模式 challenge
DungeonSessionWindow(...).run()                      # 不传 = HostPort()，无宿主（自检）
```

注意：`dungeon/window/ui.py::_update_dpi_scale` 里仍有一处 Windows 平台代码
（`FindWindowW` + `GetDpiForWindow`，运行期发现 DPI 变化后重算 `_dpi_scale`），
属于 Win32 细节而非宿主端口范畴，是后续可选的清理项。

## 6. 宿主边界与进程隔离

一句话：window 层不认识任何 UI 框架，宿主能力全部经端口索取；副本窗口是独立顶层窗口——
**换宿主可以做，嵌入宿主布局做不到**。

### 6.1 宿主端口：唯一的接触面

| 项 | 现状 |
|---|---|
| 端口定义 | `dungeon/window/host.py::HostPort`（含无宿主的缺省实现） |
| Tk 实现 | `ui/hosting/tk_host.py::TkHost`（自检/自动驾驶用；产品路径已改走子进程宿主） |
| 子进程实现 | `ui/hosting/dungeon_child_host.py::ChildHost`——子进程内的宿主端口，宿主能力走协议请父进程代劳（§6.5） |
| 端口方法表 | 本文 §5.2 |
| 注入方式 | 父进程：`launch_dungeon_subprocess(...)`（`ui/hosting/dungeon_spawner.py`）；子进程内构造等价于 `DungeonSessionWindow(host=ChildHost(...), **deserialize_launch(payload))`；不传 host = `HostPort()`（无宿主，自检走这条路径） |
| 守卫 | `tests/check_dungeon_layering.py`：`dungeon/window/*.py` 里出现 `tkinter` / `customtkinter` / `ui` 即失败 |

换宿主要做的事只剩一件：**写一个新适配器**（尺寸/DPI、显隐、事件泵、弹框、活动窗口登记、字体、回放文件选择）。正因为 window 层不认 tkinter，`open_replay_file()` 里的 `json` 解析与 `filedialog` 必须住在适配器侧（`ui/hosting/tk_host.py`）。

### 6.2 驱动方式：宿主循环里的同步窗口

副本窗口**不**把宿主主循环交给库，而是由窗口自己的运行器
`dungeon/window/runner.py::WindowRunner` 调 `hello_imgui.run(RunnerParams)`——它内部建
GL 后端 / ImGui 上下文 / 视口并驱动帧循环，返回即全部释放。每帧顺序与关闭判定见 §2.2。

由此得到的三条性质（都是现状）：

| 性质 | 说明 |
|---|---|
| 宿主不冻结 | 帧回调每帧经端口 `pump_events()` 泵一次宿主事件（`on_frame_start`） |
| 关闭不依赖平台 | 程序化关闭经 `_request_close()` → `runner.request_exit()` 置位，`before_imgui_render` 帧边界统一写 `app_shall_exit`（C1） |
| 时间源唯一 | `FrameScheduler`（`self._frame`）是 window 层唯一的时间源；计时类逻辑用帧任务，不开线程 |

产品路径里会话跑在独立子进程（§6.5），子进程内没有 Tk，窗口的宿主是 `ChildHost`——
上述性质在子进程内同样成立（帧回调仍每帧泵一次「宿主事件」，只是那里是空操作）。

### 6.3 换宿主：能；嵌入：不能

| 说法 | 含义 | 结论 |
|---|---|---|
| **换宿主** | 换成 Qt / 其它框架 / 无框架脚本来「驱动」副本窗口：谁给主循环节拍、谁给尺寸与 DPI、谁弹对话框和文件选择框 | **能** |
| **嵌入** | 把副本画面当控件塞进宿主布局（Qt 的 QWidget、Tk 的 Frame） | **不能** |

驱动侧只依赖宿主「能处理一次挂起事件」这一个能力（经端口 `pump_events()`；无宿主就不泵）。
帧节拍由窗口的运行器（`hello_imgui.run`）提供，宿主不必自带定时器——无宿主的 `HostPort()`
就是把 `pump_events()` 做成空操作即可跑。因此任何能处理一次挂起事件的框架都能当宿主：

| 宿主 | 需要实现的端口 |
|---|---|
| Tk（现状） | 宿主窗口显隐（控件本身若没有窗口级命令，退回 `winfo_toplevel()`——`CTkFrame` 的 `withdraw`/`deiconify` 是 `Wm` 的方法，直接拿控件显隐会**静默失效**）+ `winfo_*` + ctypes DPI + `ui.ctk.dialogs` |
| Qt | `QWidget.hide/show` + `devicePixelRatioF()` + `QMessageBox` / `QFileDialog`（帧回调里调 `processEvents()` 泵宿主） |
| 无框架脚本 / CI | 屏幕尺寸 + no-op + print（`HostPort()` 缺省实现即此） |
| Web / 其它进程 | 做不到（渲染后端必须在本进程有 GLFW 窗口） |

> 注意：副本 `run()` 是**同步阻塞**的。宿主的节拍是在调度回调里被**消费**的
> （每次 `on_frame_start` 里 `pump_events()`）。`QTimer` 这类事件循环回调式节拍没法直接
> 驱动它——要么继续用「循环内轮询」式（`processEvents()`），要么把会话挪到自己的线程 /
> 子进程里跑（产品路径选的是后者，§6.5）。

因此「迁移到 Qt」的真正工作量从来不在副本窗口（只需换 host 适配器），而在 `ui/` 那一整套面板。

**嵌入为什么做不到**：imgui-bundle（`hello_imgui`）的窗口是**独立的 GLFW 顶层窗口**，
公开 API 里没有把画面渲染进宿主某个控件句柄的入口。强行 `SetParent` 会被 GLFW 把父级
改回去，最多做到「位置跟着宿主移动」的伪嵌入，不是控件级嵌入，跨平台更无从谈起。
结论：**换框架时副本窗口仍然是一个浮在旁边的独立窗口**，这一点不会改变。

### 6.4 明确不做的事

| 不要 | 原因 |
|---|---|
| 同一进程里并发两个副本窗口 | 副本的 GL 上下文与视口都是进程级单例语义；`DungeonWindowBase._session_running` 是守门人（产品路径里会话本就在独立子进程，父进程不涉及） |
| 在帧循环里 `join` 线程 | 会卡帧 |
| 业务代码直接退出副本窗口 | 一律走 `_request_close()` → `runner.request_exit()`（只置位，帧边界落实，C1） |
| 为「修挂死」堆看门狗 | Python 层定时器在渲染期间拿不到 GIL，超时兜底只能放父进程；真正卡住时 `os._exit` 与 `Stop-Process -Force` 都无效 |
| 指望把副本窗口嵌入宿主布局 | 只能是独立顶层窗口（§6.3） |
| 动 `dungeon/` 领域层 | 分层守卫守着；本层只在 `dungeon/window/` 与调用方之间动刀 |
| 在父进程（Tk 主程序）里 import 副本窗口栈（`imgui_bundle`） | 父进程从不创建渲染后端上下文，副本窗口栈只该活在子进程里。父进程侧一切副本交互都经 `ui/hosting/dungeon_spawner.py` |

### 6.5 进程隔离：会话子进程（现状）

副本会话（`DungeonSessionWindow.run()` 的整个生命周期，即 Session）运行在**独立子进程**里。
当初不做它的依据是「它唯一能治愈的症状（退出挂死）不存在」；但此后发现的同进程共存问题
（C2 的 Tk 崩溃面、C12 的 `WM_QUIT` 残留、C14 的视口僵尸窗口、热切换兜底修复）让它的收益面
被大幅低估——保活视口、残留清理、僵尸窗口销毁这一整套机器，全部只在描述「Tk 与副本渲染栈
同进程」。拆进程后这些机制要么随子进程消失，要么退化为子进程内部的无害收尾。

| 件 | 位置 | 职责 |
|---|---|---|
| 父进程侧 | `ui/hosting/dungeon_spawner.py` | 序列化构造参数（`dungeon/window/launch_payload.py`）→ `multiprocessing.Process` 拉起子进程 → 泵循环（`host_window.update()`）→ 代答协议请求 → 还原 `SessionResult`；会话期把句柄登记到 `app._active_dungeon_window`（老代码的「副本进行中」守卫与 `request_close()` 因此零改动） |
| 子进程侧 | `ui/hosting/dungeon_child_host.py` | `ChildHost(HostPort)`：尺寸/弹框/回放文件框走协议请父进程代劳；管道断开（父进程死亡）即 `os._exit`，孤儿副本不会继续写 `data/` |
| 线格式 | `dungeon/window/launch_payload.py` | 构造参数 dict ↔ 纯数据 dict 的往返（dataclass 落 `asdict`、宿主侧参数剔除）；`SessionResult` 的往返同文件。守卫：`tests/check_dungeon_launch_payload.py` |

载荷里唯一与文件系统有关的是 `asset_root`：挑战包把方案素材解在方案目录之外
（系统临时目录），子进程构造仓库时由 `_AssetBackedRepo` 包一层，让
`asset_dir()` 指向该目录，其余转发真仓库（口径见 `docs/architecture.md` §2.9）。
它只是路径字符串，不破坏「载荷全是纯数据」这条线格式约定。

协议（`multiprocessing.Pipe` 双向，JSON 安全 dict）：子 → 父发
`show_window` / `dialog` / `open_replay_file`（带请求 id）/ 最终 `result`；
父 → 子发 `{"reply": id, "answer": ...}`（`open_replay_file` 的应答额外带
`path`，供窗口从文件名认出方案）与 `{"req": "close"}`（父进程整体退出前请
子进程走帧边界收尾）。子进程的弹框请求在父进程泵循环里用调用方自己的弹框实现
代答（专业版 `ui.ctk.dialogs`、挂件版 `MiniDialogs`）——子进程内因此没有任何
Tk 代码，`tests/check_mini_layering.py` 白名单放行 `dungeon_spawner` 的依据正是它
模块级零 CTk 依赖。

**DPI 感知**是进程级的、不随 multiprocessing 继承：子进程的感知档位镜像父进程
（载荷 `dpi_aware` → 子进程 `_ensure_dpi_awareness`，档位与 CTk 相同的
`shcore.SetProcessDpiAwareness(2)`）。父感知而子不感知，Windows 会把视口的
96-DPI 逻辑坐标按系统缩放再放大一次（窗口与字体巨大）；父（挂件版）刻意无感知
而子感知，视口会比主窗口小一圈。诊断：`scripts/child_dpi_probe.py`（拉两个子进程
打印各自的 `GetDpiForSystem()` 与注册表 `AppliedDPI`，人工对照）。

代价（真实存在，已接受）：构造参数必须跨进程序列化（线格式见上表）；角色在子进程里
的改动（扣 AP、结局索引）由子进程直接写盘、父进程在会话结束后重载；每次开局有
一次子进程解释器/导入的启动延迟。

### 6.6 进程退出挂死（结论）

跑完会话后进程可能在**退出阶段挂死**。已查明：这是**长时会话累积出的 OS/驱动级环境现象**，
与本项目代码、与渲染后端、与驱动方式都无关（纯 Tk、不 import 副本窗口栈的进程同样复现，
重启即消失；同一进程内连做 10 轮 create/destroy 也能干净退出，说明不累积在进程内）。

因此：自检按「读输出判定 + 父进程超时兜底」（§7.3），默认**不**把退出码当失败信号；
真遇到症状**先重启系统**再复现，不要改代码。复测退出路径时用
`dungeon_autopilot.py --require-clean-exit`（重启后应全绿；它把「未自行干净退出」也判为
失败）。父进程的等待是**硬超时**（读输出在独立线程里做，主线程按 deadline 轮询），
子进程的结论行打印后立即 flush——「已通过但退出挂死」与「超时未出结论」因此可以
分开汇报。

## 7. 调试自动化

**调试副本窗口能不能不靠人手点电脑？能，而且大部分已经做到。**
已落地 `scripts/dungeon_autopilot.py`（GUI 冒烟：无人手点击、不联网、不碰真实 `data/`）。

### 7.1 场景表

基线实测（本机 Windows / imgui-bundle 1.92.900 / Python 3.13）：

| 场景 | 覆盖 | 断言 |
|---|---|---|
| `chapter-bgm` | 章节背景音乐接线：起始章节起播 → 跳到无音乐章节停播 → 收尾收工（替身后端，自检不出声；真实后端由 `check_audio_chain.py` 探） | 7 项 |
| `chapter-voice-fx` | 章节对话语音**物理**效果接线（她 / 其他人两档）：她那一档开分拍回声 → 其他人那一档只缓抖 → 叙述句不念也不进合成队列 → 跳到没配效果的章节清空 → 回放记录带 `voice_fx` → 收尾线程与临时音频收干净（假合成器不联网 + 替身后端不出声；假音频必然解不开，顺带验证「解不开也不拖垮朗读」） | 11 项 |
| `dialogue-voice` | 带结构化说话人的对话语音接线：她 / 主角 / 配角分嗓子、叙述句与 `literary` 方案不念、语音总线拧到 0 一声不吭（连合成都省）、收尾收工与临时音频清理（假合成器不联网 + 替身后端不出声） | 9 项 |
| `entry-cancel` | 探索模式入口页 → 中途读一次 `ui_snapshot()` 断言入口页状态 → 点「返回」 | 9 项 |
| `entry-replay` | 入口页「加载回放」→ 取消一次 → 再选文件 → **同一窗口内**切回放（「取消那一刻仍停在入口页」也由快照断定） | 12 项 |
| `entry-start` | 探索模式入口页 → 点「开始副本」→ 步进 → 关闭 | 8 项 |
| `mini-game-escape` | `escape_giantess` 真覆盖层舞台：离屏画布 GL 纹理上传 + 每帧绘制指令 + ESC 中止 | 1 项 |
| `mini-game-py` | 小游戏覆盖层舞台：打开 / 结算记返回值 / ESC 中止 | 1 项 |
| `mini-game-repeat` | 可再次触发的小游戏：结算后回副本主页面（不原地重启）、后续步进可再进 | 1 项 |
| `native-close` | 视口通过原生关闭键（X / `WM_CLOSE`）关闭：队列不得残留 `WM_QUIT`、收尾提示与宿主计时器不卡死 | 7 项 |
| `native-input` | 真原生按键（`SendMessage` 直投 `WM_KEYDOWN`）落到窗口**自己的输入接线**上并在帧循环线程执行 | 6 项 |
| `session-close` | 挑战模式直进会话 → 步进 → 中途读一次 `ui_snapshot()` → 关闭（含帧时钟 / 像素工作者收工、结果对象字段） | 20 项 |
| `text-components` | 文本组件家族（`text_card` / `text_nvl`）接管显示的会话中途可见状态 + `text_component` 字段三选一与旧写法提升 + 覆盖层服务面（调出/阅读模态挂起/关闭恢复/兄弟组件只读访问）；`("check", fn)` 脚本动作在帧循环线程上断言 | 10 项 |
| `tk-host` | 宿主换成真 Tk 根窗口（`TkHost` 适配器）：会话期间宿主心跳照跑 | 7 项 |

**14 个场景共 109 项断言**（7 + 11 + 9 + 9 + 12 + 8 + 1 + 1 + 1 + 7 + 6 + 20 + 10 + 7），
全部子进程**自行干净退出**（rc=0）。每个场景结束还会断言 **会话内无残留非 daemon 线程**
（`threading.enumerate()` 为空）——这是帧时钟 + `PixelWorker` 的验收条件。
单场景耗时数秒到二十几秒不等，全套（`--scene all`）几分钟量级。

窗口状态一律经窗口自己的 **`ui.ui_snapshot()` 值快照**读取：立即模式没有 retained
控件树，DPG 时代的内省探针已随迁移删除（它们在没有 DPG 上下文的进程里是 access
violation，不是异常）。

注意：官方组件包是窗口层常驻 Python 包 `dungeon/window/component_pack/`，随 registry
正常导入，与 data_dir 重定向无关——autopilot **不需要**任何组件包注入。组件包本身由
无 GUI 守卫 `check_component_pack.py` 覆盖；本脚本的 `text-components` 场景只负责真窗口
里的接管可见状态。

注入点：宿主能力（尺寸/DPI、显隐、事件泵、收尾弹框、回放文件选择）全部经
`dungeon.window.host.HostPort` 注入，**不用打桩 `ui.ctk.dialogs`**——
`ScriptedHost`（无宿主）与 `RecordingTkHost`（真 Tk 度量 + 记录弹框）就够了。

### 7.2 覆盖范围与分层

| 能自动化的 | 不能 / 不做 |
|---|---|
| 真窗口生命周期：构造 → `run()` → 步进 → 关闭 → 落盘 | **进程退出码**不能当验收条件（退出阶段可能挂死，是环境现象，§6.6） |
| 收尾路径（`_finalize` 两条分支）、结果对象字段 | **视觉观感**（背景、字体 DPI、留白） |
| 宿主心跳（会话期间宿主不被冻结） | **真机手感**（F11、拖 resize、高 DPI 首图时机） |
| 回放切换（取消 / 选中两条分支） | **真实 AI 的输出质量** |
| 会话结束后无残留非 daemon 线程 | 真实鼠标输入与拖 resize（键盘一侧已由 `native-input` 覆盖）、视觉回归（可选，优先级低） |

| 层 | 覆盖什么 | 状态 |
|---|---|---|
| **L0 纯逻辑** | 收尾路径、原子写、schema、命名、分层 | 已有：`tests/check_*.py`，无 GUI，进 CI 门禁 |
| **L1 无宿主自动驾驶** | 构造 → 运行 → 步进 → 关闭 → 落盘的完整生命周期 | 已落地：`scripts/dungeon_autopilot.py`，`parent=None` 直起运行器（无宿主 `HostPort`） |
| **L2 Tk 宿主 + 自动驾驶** | 宿主在会话期间不被冻结 | 场景已落地（`tk-host`）；「进程是否退出」这一项**不能断言**（§6.6） |
| **L3 真实输入事件** | 真实按键（`SendMessage(WM_KEYDOWN)` → GLFW → imgui 输入队列）、F11、resize | 部分落地：`native-input` 场景已覆盖键盘直投；鼠标/重排仍靠 `--check` 钩子与快照 |
| **L4 视觉回归** | 布局 / 背景 / 字体 | 可选、优先级低（没有 headless 渲染，只能截屏比对或断言几何量） |

L1 与 L0 的分工：L0 保证逻辑对，L1 保证「真窗口跑起来也是对的」——只有真窗口才会走的
运行器起停（`hello_imgui.run()` 的 GL 上下文/窗口生命周期）、调度队列、后台线程与关闭路径的交互。

### 7.3 命令与判定方式

```bash
python scripts/dungeon_autopilot.py                              # 全部场景（每场景一个子进程）
python scripts/dungeon_autopilot.py --scene tk-host --isolate    # 单场景，子进程隔离
python scripts/dungeon_autopilot.py --scene session-close --repeat 2 --isolate  # 同进程连开两轮
python scripts/dungeon_autopilot.py --in-process                 # 当前进程内依次跑（快，但崩溃带走全部）
```

判定规则（默认**不要**把退出码当验收条件）：

1. 控制台出现 `[dungeon_autopilot] PASSED n/n` 即通过；脚本自身会用 `report:` 行给出明细报告路径。
2. 判定成败**看子进程打印的结论行，不看退出码**。结论行在子进程里打印后立即 flush（管道 stdout 是
   块缓冲，默认 flush 排在解释器退出收尾的最后——退出挂死时结论行会困在缓冲里，父进程就会把
   「已通过但退出挂死」误判成「超时未出结论」）。
3. 每个场景开**子进程**（单场景用 `--isolate`）。读输出在父进程的独立线程里做，主线程按 deadline
   轮询，所以超时是**硬超时**——子进程停止出字（如渲染占住 GIL）也吊不住父进程。读到结论行
   后等 `EXIT_GRACE`（5s）宽限，仍不退出才 `kill()`（正常子进程在结论行后约 0.1s 就退出，这是加
   宽限的原因）。
4. 断言、退出码、退出方式（自行退出 / 超时未出结论 / 结论已出但退出挂死）**分开汇报**，默认只有
   断言影响成败；`--require-clean-exit` 把「未自行干净退出」也判为失败（退出路径的环境复测用，
   见 §6.6）。
5. CI：GUI 冒烟层单独一个 job（需要显示器），不要并进无 GUI 的门禁。已落地为
   `.github/workflows/gui-smoke.yml`（每晚 + 手动：`xvfb-run` + 软件 GL 跑
   `dungeon_autopilot --scene all --isolate`、`smoke_mini`、`smoke_switch`，并带一个
   Linux 打包自检 job）。

### 7.4 长压测标准姿势：`--isolate` + 外层 watchdog

反复开关窗口（`hello_imgui.run()` 每次拆建 GLFW 窗口 + GL 上下文）会暴露 imgui/GLFW 的低概率
**原生**段错误（`SIGSEGV @ ImGui_ImplGlfw_WindowFocusCallback`，Python 层 `try/except` 捕不到）。
这类问题只能靠「一轮一个子进程 + 外层统计退出码」抓：单轮跑在父进程里，一次崩溃就把整轮统计
带走，永远得不到"20 轮里崩了几轮"。

标准做法是**逐轮起子进程、按退出码分类**，别把 `--in-process` 用于压测：

```bash
# 现成脚本（developer_tools/，本地探针目录，不入库）：
python developer_tools/_probe_stress.py smoke_switch 20                    # 默认：XInitThreads 生效
GIANTESS_X11=0 python developer_tools/_probe_stress.py smoke_switch 20     # 对照组
python developer_tools/_probe_stress.py autopilot 5 -- --scene all --isolate
```

它每轮打印 `rc` 与耗时，末尾汇总 `PASS / 非零退出 / 原生崩溃`——**负的 rc 就是信号**
（`-11` = SIGSEGV）。等价的手工版本：

```bash
for i in $(seq 1 20); do
  .venv/bin/python tests/smoke_switch.py >/dev/null 2>&1
  echo "round=$i rc=$?"        # 139 = 128+11 段错误
done
```

Linux 侧配合 `GIANTESS_X11=0` 做 XInitThreads 有效/无效对比（X11 boot 的机制见
`docs/platforms.md` §2.2）。判定只看「跑完且没崩」，不看单轮断言——断言已由单轮标准跑覆盖。

### 7.5 注入点清单（照抄即可）

| 目的 | 做法 | 依据 |
|---|---|---|
| 不要 Tk 主窗口 | `DungeonSessionWindow(parent=None, ...)` | `base.py` 里 `self.parent` 的用法全部有 None / hasattr 守卫 |
| 真 Tk 宿主 | `parent=tk.Tk()`（屏幕外 + 全透明） | `_pump_host_events` 只要求宿主有 `update()` |
| 假 AI（不联网） | 打桩 `dungeon.window.base.create_client`，实现 `generate_stream` / `generate` | `base.py::_init_session` 用它建 `self.ai_client` |
| 数据隔离 | 把 `paths.data_dir` 重定向到临时目录 | **必须在 import `dungeon.window.*` 之前**——那些模块用 `from paths import data_dir` 在导入时绑定函数对象 |
| 屏蔽对话框 | **注入宿主端口**：`DungeonSessionWindow(..., host=ScriptedHost())` | window 层只经 `HostPort` 弹框；真模态窗需要 Tk 根窗口，自检里点了会挂住 |
| 主线程操作 | 一律 `_frame.call(fn)`，后台线程绝不直接碰窗口/GL 状态 | 立即模式下窗口状态只在帧循环线程上变，§4 |
| 关闭窗口 | `_close_loop()` → `_request_close()` → 帧边界落实（运行器收帧） | 业务代码不要自己停帧循环；`_request_close` 只置位 |
| 脚本化动作 | `click / enter / cancel / replay / check / close / native-close / native-key / sleep`，见 `AutopilotWindow._run_script` | 本文配套脚本 |
| 读窗口状态 | `win.ui_snapshot()`（值快照）或 `("check", fn)` 动作 | 立即模式没有 retained 控件树可内省 |

```python
import paths; paths.data_dir = lambda: tmp_data        # 先重定向，再导入窗口模块
import dungeon.window.base as wbase
wbase.create_client = lambda *a, **k: ScriptedAI()      # 脚本化 AI
from dungeon.window.host import HostPort                # 宿主端口：弹框收进 calls

class ScriptedHost(HostPort):
    def dialog(self, kind, title, message):
        self.calls.append((kind, title, message))

class Auto(DungeonSessionWindow):
    def _build_ui(self):
        super()._build_ui()
        threading.Thread(target=self._run_script, daemon=True).start()

Auto(..., host=ScriptedHost()).run()
```

### 7.6 坑清单

| 坑 | 现象 | 应对 |
|---|---|---|
| **退出阶段挂死（与渲染后端无关）** | 断言全部打印完毕、无残留非 daemon 线程，`sys.exit` 与 `os._exit` 都试过仍不退出（约 190MB 常驻）；卡点在 Python 之下，卡住后 `Stop-Process -Force` 也杀不掉 | 按 §7.3 的输出判定 + 父进程硬超时兜底；**不要**看退出码（复测退出路径用 `--require-clean-exit`）。根因见 §6.6——长时会话累积的环境现象，先重启系统 |
| **Python 层看门狗无效** | 渲染循环期间 `threading.Timer` 可能拿不到 GIL，实测 40s 定时器根本没触发 | 超时只能由父进程兜底 |
| **会话收尾别对旧宿主窗口动手** | DPG 时代 `destroy_context()` 之后对现场 Tk 根做窗口级命令（`destroy()` / `withdraw()`）会硬崩；imgui 侧 `run()` 之后销毁 Tk 根安全 | 自检里 `scene_tk_host` 仍**不销毁**它创建的根窗口（留在 `_KEEP_ALIVE_ROOTS` 里）——销毁与不销毁都安全，保留现状以免影响覆盖面 |
| **自检里不要用真模态弹框** | `scene_tk_host` 用真 `TkHost`，收尾提示会弹真 CTk 模态框，没人点就一直等（实测 40s/90s 均超时） | 用 `RecordingTkHost(TkHost)`：尺寸/DPI/显隐/事件泵走真适配器，只把 `dialog()` 换成记录器 |
| **需要显示器** | 没有 headless 渲染，窗口会真的出现 | 这是它属于 GUI 冒烟层、不进无 GUI CI 门禁的原因 |
| **时序** | 固定 sleep 不稳 | 用轮询 / 条件等待；两次点击间隔 ≥ 0.4s（`_on_next_step` 节流）；窗口存活期间读状态要在 enqueue 的回调里读，构造返回后可以随便读 |
| **假 AI 必须遵守解析契约** | 否则只测到「生成异常」那条路径 | 遵守 `dungeon/response.py` 的 `{"text", "direction", "custom_directions"}` |
| **打桩的 `personality` 要补齐字段** | 缺 `sensitivity` / `normalized_strength` / `strategy_value` 时每一步 `_finish_step` 都抛异常，而故事**看上去还在正常出字** | 靠断言「回放记录是否增长」发现 |

### 7.7 仍然需要人工的部分

- **视觉观感**：背景裁切 / 淡入淡出、字体与 DPI 缩放、文本区留白、Ken Burns 运动幅度。
- **真机交互手感**：F11 全屏、拖 resize 的重排效果、高 DPI 下的首图时机。
- **真实 AI 的输出质量**：自动化只能保证「跑得通、状态推进正确、收尾正确」，不能保证「故事好看」。

## 8. 自检命令

| 改动范围 | 先跑 |
|---|---|
| 关闭路径、收尾、入口阶段、生命周期、帧时钟、回调线程、章节背景音乐、章节对话语音物理效果、对话语音 | `python scripts/dungeon_autopilot.py`（14 场景，含 `text-components` 组件冒烟）；单场景 `--scene <名字> --isolate`，连开关窗 `--scene session-close --repeat 2 --isolate` |
| 启动载荷序列化 / 结果往返（进程隔离线格式） | `python tests/check_dungeon_launch_payload.py`（无 GUI，73 项断言） |
| 会话子进程端到端（spawn、协议代答、登记/注销、限帧钩子） | `python tests/smoke_mini.py`（副本链路实测一节；`GIANTESS_DUNGEON_TEST_FRAMES` 限帧子进程） |
| `_finalize` / `json_store` / `scenario_repo` | `python tests/check_dungeon_finalize.py`（无 GUI，32 项断言） |
| 显示组件包 / 文本组件 / 组件参数 | `python tests/check_component_pack.py`（无 GUI，93 项断言：加载链、契约与服务面（替身 ctx + AST 越界扫描）、元数据与参数夹取、外部包覆盖、build/layout/refresh/destroy 冒烟与帧任务成对清理） |
| 分句器 / 说话人标记 | `python tests/check_splitter.py` |
| 新增 import / 分层 | `python tests/check_dungeon_layering.py`（窗口层含 `component_pack/` 子包） |
| 新增后端生命周期 / 线程调用（`hello_imgui.run`、`app_shall_exit`、Timer、join、dearpygui 回归） | `python tests/check_dungeon_window_contract.py`（C1 / C4 / C5 的机械可查部分） |
| 收尾释放纹理 / 新增 `TextureGpu` 持有处 | `python tests/check_gpu_texture_lifetime.py`（C15 的机械可查部分，13 项断言）；真窗口收尾看 `scripts/dungeon_autopilot.py` 后退役仓库是否仍为 0 |
| schema / 校验器 | `python tests/check_scenario_schema.py`；批量校验 `python scripts/scenario_validate.py --errors-only` |

无 GUI 守卫（见 [副本引擎架构与术语](dungeon_engine.md) §9 的脚本索引）+
真窗口冒烟（`dungeon_autopilot.py`）才算绿。判定方式见 §7.3：**按子进程输出判定，
不看退出码**（退出阶段可能挂死，已查明是环境现象而非代码缺陷，§6.6）。

其它提示：

- 涉及关闭路径的改动**必须**在真实应用中手测（最小 imgui 脚本复现不了 Tk 宿主 + 完整线程栈的组合行为）。
- 回放结束、入口返回、会话 X 关闭是三条独立路径，改 `_request_close` / `_on_close` / `_handle_exit` 时逐一回归。
- 控制台出现 `流式任务执行异常: '...xxx' object has no attribute ...` 通常是 `_init_session` 没跑完（某属性缺失），先看完整 traceback 的第一个异常点。
