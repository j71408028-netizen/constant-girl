# 显示组件

> **这一篇回答什么问题**：副本窗口的显示组件怎么写（钩子契约）、参数怎么声明与
> 夹取、怎么登记与加载、官方组件有哪些、文本主组件怎么用「slot 代管区」给其余
> 组件留位；以及与之相邻但**不属于组件包**的窗口级浮层（overlay）。方案侧的组件
> 管理页见 [../scenario_editor.md](../scenario_editor.md) §5。

## 1. 组件契约

运行时代码全在 `dungeon/window/`：基类与注册表在 `component_registry.py`，官方
组件包在 `component_pack/`，加载与布局在 `components.py`（`ComponentHandler`，
`DungeonSessionWindow` 的 mixin）。引擎层只有 `dungeon/schema.py` 声明方案字段。

基类 `component_registry.py::DungeonComponent`（全部钩子给默认空实现），类属性
即元数据，子类覆盖：

| 属性 | 说明 |
|---|---|
| `id` | 组件唯一 id，同时是 `components_params` 的键 |
| `label` / `description` | 编辑器展示名 / 说明；留空时编辑器回退为 id |
| `param_specs` | 参数声明列表（§2） |
| `roles` / `shapes` | 代管区匹配用的角色与形状；留空表示不参与分配（§5）。`roles` 可以是动态 property（`proc_log` 展开时才返回 `("log",)`） |
| `owns_text_display` | True 表示接管窗口正文显示（文本家族三组件） |
| `TAG_PREFIX` | imgui 子窗口 tag 前缀，互相不冲突且不在保留集 |

| 钩子 | 调用时机 |
|---|---|
| `build(ctx)` | 进入会话、实例化后一次 |
| `layout(ctx)` | 每轮重排；只算几何 / 缓存，不碰绘制 |
| `draw(ctx)` | 每帧，在根窗口 draw list 内立即绘制 |
| `refresh(ctx)` | 基类默认转调 `layout`；状态更新后经帧时钟调用 |
| `destroy(ctx)` | 会话收尾（GL 已释放，只兜底清状态） |
| `slots(ctx)` | 可选；返回 `layout.Slot` 列表，只有文本主组件实现（§5） |
| `top_inset(ctx)` | 可选；自报在窗口顶部占用的高度（目前只有 `attr_bar`） |
| `toggle(ctx)` | 可选；面板类展开 / 收起（目前只有 `proc_log`，F12 触发） |
| `toolbar_hovered()` | 可选；光标是否悬停在组件自己的工具条上 |

组件访问窗口的唯一入口是 `ctx`（实现散布在 `ComponentHandler`）：只读状态
（`story_history / dungeon_state / evolution_attrs`）、几何
（`component_viewport / component_rect / component_slot / component_dock_side /
component_backdrop_blur`）、帧时钟（`schedule / schedule_every / cancel_task`）、
字体 tag 与覆盖层 / 截图等服务调用。组件不许直接碰窗口私有成员——守卫用 AST
检查（`tests/check_component_pack.py`）：不许 `print`（走 `dungeon/process_log`）、
不许读 `ctx._*`、所有定义了 `id` 的组件类必须登记进 `REGISTRY`，并用替身 ctx 跑
`build → layout → refresh → destroy` 冒烟。

## 2. param_specs 与参数夹取

每项声明是一个 dict：

| 键 | 说明 |
|---|---|
| `key` / `label` / `type` / `default` | 必填；`type` ∈ `int / float / bool / color / text`；color 必须是 `(r,g,b,a)` 四通道 0–255 整数 |
| `min` / `max` | 可选，仅对数值类型生效，声明了就要被夹取 |
| `note` | 可选，编辑器提示文案 |

运行时夹取（`component_registry.py`）：`merge_params(component_cls, overrides)`
以 `default_params_for` 打底，覆盖值存在且非 None 才写入，数值按 min/max 夹取，
**未知键忽略**；方案侧取 `resolve_configured_params`——读
`config["components_params"][组件id]`（不是 dict 时整体回退默认）。编辑器
`ui/scenario/component_mgr.py::collect_params` 保存前用同一规则夹取。

## 3. REGISTRY 与加载链

- **注册表**：`component_pack/__init__.py::REGISTRY`（普通 dict
  `{组件id: 组件类}`，官方包唯一出口）。文本三件套的 id 必须与
  `dungeon/schema.py::TEXT_COMPONENT_IDS = ("text", "text_card", "text_nvl")`
  同源。
- **加载**（`component_registry.py::ComponentRegistry._load`）：外部包目录优先
  （入口文件名固定 `components.py`，取其 `REGISTRY` 属性），缺失 / 失败回退内置
  包（函数内 import，防 PyInstaller / Nuitka 打包版静默缺包）。进程级单例
  `get_registry()`，一个进程只加载一次。没加载到任何组件时记日志并退回内置
  文本容器；缺文本家族则「会话将无文本栏」。
- **id 解析** `resolve_ids(ids)`：未知 id 记日志跳过、去重保序；结果里没有文本
  家族成员时按 `TEXT_COMPONENT_IDS` 顺序补一个插到首位（文本主组件必须三选一）。
- **实例化** `instantiate(ctx, cid, config)`：每 `(ctx, cid)` 单例；构造异常记
  日志并缓存 `None`（不重试）；实例化后注入
  `comp.params = resolve_configured_params(...)`。
- **方案声明 → id 列表**（`components.py::ComponentHandler._configured_component_ids`）：
  `text_component` 经 `normalize_text_component` 归一（不在三选一集合回退
  `text`）；`components` 列表里的文本家族成员按旧写法处理——缺 `text_component`
  字段时提升为主组件，否则忽略。主组件先建、z 序在底。

**挂接顺序**：构建（`_build_components`：resolve + instantiate + 逐个 `build`）→
两遍式重排（§5）→ 每帧 `draw`（`ui.py::_draw_frame`，文本接管判定
`_text_owned_by_component` 决定是否跳过内置正文绘制）→ 收尾
（`base.py::_finish_session`：`destroy` 逐组件 + `registry.discard` 丢实例缓存）。
窗口尺寸变化、F12 展开收起、dock 侧切换都触发重排。**单个组件钩子抛异常只在
`process_log` 记一条，不拖垮窗口**（draw 失败下一帧还会重试）。

## 4. 官方组件清单

共享常量在 `component_pack/base.py`：文本家族公共基类 `_TextDisplayBase`
（悬浮工具条五按钮：自动播放 / 截图 / 过程日志 / 人物档案 / 副本设置；可读宽度
上限 `_MAX_TEXT_WIDTH=1280`；GPU 工具条纹理须在 GL 存活时经 `drain_gpu_textures`
移交）。

| id | 类 | 版式 | 职责 |
|---|---|---|---|
| `text` | `text_gradient.py::TextComponent` | 底部渐变 | 视口底部向上淡出的深色渐变衬底显示最近几句（ADV 风格） |
| `text_card` | `text_card.py::CardTextComponent` | 底部卡片 | 居中圆角毛玻璃卡片（背景模糊副本 + 染色 + 玻璃边） |
| `text_nvl` | `text_nvl.py::NvlTextComponent` | 全屏 NVL | 全屏半透明覆盖层堆叠全部历史段落，滚轮回看 |
| `attr_bar` | `attr_bar.py::AttrBarComponent` | 状态栏 | 单行实时显示演化属性（`show` 状态才显示），数值颜色按 0.5–4.5 值域绿→黄→红 |
| `proc_log` | `proc_log.py::ProcLogComponent` | 过程日志 | 订阅 `dungeon/process_log.py` 补显积压消息，默认收起（`toggle` / F12），展开时 `roles` 才生效 |

文本三件套的公共参数：`label_color / highlight_color / show_indicator`
（继续指示「▼」）；各自的版式参数：

| id | 专属参数（default / min-max） |
|---|---|
| `text` | `height_percent`（45 / 15-80）、`max_lines`（1 / 1-5）、`gradient_color` |
| `text_card` | `width_percent`（70 / 30-95）、`max_lines`（1 / 1-5）、`bg_color / border_color`、`glass`（True） |
| `text_nvl` | `margin_percent`（0 / 0-30）、`bg_color`、`use_serif`（True） |
| `attr_bar` | `name_color / text_color`、`panel_width`（480 / 200-1600）、`draw_own_surface`（False） |
| `proc_log` | `panel_width`（460 / 240-960）、`scroll_height`（300 / 60-800）、`max_lines`（300 / 50-2000）、`draw_own_surface`（False） |

`draw_own_surface=True` 时组件否决宿主代管区的缺省底纹、自绘面板。

## 5. slot 代管区

**代管区（slot）**：文本主组件在 `layout` 阶段生成的一块「我替你留好、代管其
呈现」的区域，窗口做机械匹配分给声明的子组件，子组件不再自己发明坐标。纯数据
与几何都在 `dungeon/window/layout.py`（不导入绘制库）。

- **形状**：`SHAPE_BAND` 横带 / `SHAPE_RAIL` 竖栏 / `SHAPE_TILE` 块；侧向语义
  `SIDE_LEFT / SIDE_RIGHT`（入场来向 / 对齐侧，空串无侧向）。
- **底纹契约** `SlotStyle.surface`：`host` 文本组件画底纹 / 边框 / 分隔线，子组件
  只画内容（默认）；`bare` 无底纹；`own` 子组件自绘面板。`SlotStyle` 还携带
  颜色（bg / border / separator / 文本三色）、`radius / padding / side / 
  enter_from / enter_fade / enter_seconds`，尺寸为已按 DPI 放大的物理像素。
- **占格算法**（`layout.py::Slot`）：`accepts(roles, shapes)` 形状必须命中、slot
  的 roles 为空表示不限制否则求交集；`take()` 占一格——capacity==1 整块，rail
  竖排均分（从上往下），band / tile 横排均分，满了返回 None。
- **匹配与分配**：`select_slot(slots, roles, shapes)` 按声明顺序找第一个未满且
  匹配的 slot；分配结果记在
  `components.py::ComponentHandler._assign_component_slots`。重排是**两遍式**：
  先让文本主组件（owners）layout 并分配 slot，再让其余组件 layout——此时它们
  能从 `ctx.component_rect(cid)` 拿到分配结果。`Slot.offset_x` 是宿主让位位移，
  不参与几何分配。
- **入场动画**：`layout.py` 的六个纯数学函数（`ease_out_cubic / enter_direction /
  enter_offset / enter_rise / enter_alpha / enter_transform`）给出
  `(dx, dy, alpha)`，消费方是 `proc_log` 与文本组件的 slot 底纹绘制。
- **停靠侧不是方案参数**：`dock_side`（`dungeon/settings.json` 的 `dock_side`，
  副本设置面板里实时改）决定 rail 在左在右，经
  `dungeon/settings.py::normalize_dock_side` 归一，改完触发重排。

各文本组件实际声明的 slot（`base.py::_TextDisplayBase.slots` 返回 layout 阶段
算好的 `self._slots`）：`text` 有 `scrim_band`（status，bare）与 `scrim_side`
（log，own，从下方升起 + 淡入）；`text_card` 有 `card_footer`（status，host）、
`card_side` / `card_side_low`（log，own）；`text_nvl` 有 `nvl_header`（status，
host）与 `nvl_side`（log，host 但不画底纹，与正文列共底纹融合）。放不下时组件
返回 None，消费方回退独立浮动面板（`attr_bar` 左上角、`proc_log` 右上角）。

## 6. 窗口级浮层（overlay）

`dungeon/window/overlay.py::OverlayHandler` 是**窗口级模态浮层**，与组件包是
两套机制——组件不注册为浮层。浮层只有三种：`log` 对话记录（半透明遮罩 + 滚动
面板）、`settings` 副本设置（音量总线滑条 / 帧率上限 20–240 / 组件代管区靠左靠右，
连续改动标脏、关面板时落盘）、`characters` 人物档案（在场 / 最近离开分组，
`key` 角色临时称呼可手动合并）；小游戏舞台打开时优先级最高。

- 服务面：`toggle_overlay(name)`（同名关、异名先关再开，未知名弹通知）、
  `close_overlay`、`toggle_settings / toggle_characters`（入口阶段 / 收尾中 /
  小游戏 / 有待选项时拒绝）；组件可经 ctx 调用。
- 键位（`ui.py::_handle_input`）：F12 过程日志、F2 截图、H 对话记录、A 自动播放、
  O 设置、C 人物档案、ESC 关浮层、F11 全屏。
- **阅读模态**：浮层打开期间键盘推进挂起，点击只关浮层；光标悬停在组件工具条上
  时点击不推进剧情（`_component_toolbar_hovered` 汇总）。
- **双层绘制**：根窗口内画 log 整块与 settings / characters 的全屏遮罩；根窗口
  结束后再画 settings / characters 卡片本体（防被根窗口盖住）；小游戏舞台最后
  绘制、压一切。

## 7. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 组件基类、钩子契约、ctx 服务面清单 | `dungeon/window/component_registry.py::DungeonComponent`；服务面实现 `dungeon/window/components.py::ComponentHandler` |
| 参数默认值 / 夹取 / 合并 | `component_registry.py::default_params_for / _clamp / merge_params / resolve_configured_params` |
| 注册表加载（外部包优先 / 内置回退） | `component_registry.py::ComponentRegistry._load / _load_pack_directory / _load_builtin_package / get_registry` |
| id 解析 / 实例化 / 构建门面 | `component_registry.py::resolve_ids / instantiate / build_components / available_component_descriptions` |
| 官方包 REGISTRY（唯一出口） | `dungeon/window/component_pack/__init__.py::REGISTRY` |
| 文本家族基类 / 工具条 / GPU 移交 | `dungeon/window/component_pack/base.py::_TextDisplayBase / _TOOLBAR_ACTIONS / drain_gpu_textures` |
| 五个官方组件 | `component_pack/text_gradient.py::TextComponent`、`text_card.py::CardTextComponent`、`text_nvl.py::NvlTextComponent`、`attr_bar.py::AttrBarComponent`、`proc_log.py::ProcLogComponent` |
| 方案声明 → id 列表 / 构建 / 重排 | `dungeon/window/components.py::ComponentHandler._configured_component_ids / _build_components / _relayout_components / _assign_component_slots` |
| Slot / 样式 / 匹配 / 入场动画 | `dungeon/window/layout.py::Slot / SlotStyle / SlotAssignment / select_slot / enter_transform`（形状与底纹常量在模块顶部） |
| dock 侧归一 | `dungeon/settings.py::normalize_dock_side` |
| 浮层服务面 / 双层绘制 / 落盘 | `dungeon/window/overlay.py::OverlayHandler`（`toggle_overlay / _draw_overlay_root / _draw_overlay_top / _flush_settings_overlay`） |
| 每帧 z 序 / 键鼠接线 / 文本接管 | `dungeon/window/ui.py::DungeonWindowUI._draw_frame / _handle_input / _text_owned_by_component` |
| 生命周期挂接 | `dungeon/window/base.py::DungeonWindowBase._start_session / _finish_session`、`dungeon/window/launcher.py::DungeonLaunchStages._enter_dungeon_phase` |
| 进程日志（组件订阅源） | `dungeon/process_log.py::subscribe / unsubscribe` |
| 落盘迁移（文本家族提升） | `persistence/scenario_repo.py::ScenarioRepo._migrate` |
| 编辑器组件页 | `ui/scenario/component_mgr.py::ComponentManager` |
| 无 GUI 守卫 | `tests/check_component_pack.py` |
