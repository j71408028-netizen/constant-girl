# 界面双模式与外观

> **这一篇回答什么问题**：专业 / 挂件（ME模式）双界面怎么定义、怎么热切换，
> 挂件版的低像素与调查掷局机制，主题配色与外观广播，中文字体解析，启动屏与
> 更新检查。副本窗口的运行时机制在 `docs/designs/dungeon/`（入口
> [dungeon/README.md](dungeon/README.md)）。

## 1. 专业 / 挂件双模式与热切换

模式常量与设置键（`services/ui_mode.py`）：`MODE_PRO="pro"`（customtkinter 根
窗口）、`MODE_MINI="mini"`（纯 tkinter 根窗口，界面文案叫「ME模式」）。两个键都
落在 `data/user/settings.json`（`persistence/settings_repo.py::SettingsRepo`）：
`ui_mode` 记**实际所在**模式（每次切换落盘），`ui_startup` 记**启动偏好**——
`pro / mini / exit`（跟随上次退出时所在界面，缺省），
`resolve_startup_mode()` 解析。

**切换 = 销毁旧根窗口、重建另一套**（`app/shell.py::switch_to`），不复用控件、
不重启进程：

1. `save()` 保存设置 → `save_mode(mode)` 落盘 → `request_switch(mode)` 登记请求；
2. 摘掉 `WM_DELETE_WINDOW` 协议（两套界面的关闭都以 `os._exit(0)` 收尾，销毁
   窗口会误触发）；
3. `_detach_ctk_window` 把根窗口从 customtkinter 的 DPI 跟踪登记里摘除；
4. `_quiesce_root` 清场：两轮「派发事件队列（单轮上限 2000）→ cancel 全部
   `after` 定时器」，再注入只过滤 `invalid command name*` 的 Tcl `bgerror`；
5. `root.destroy()`。调度循环 `run_app()` 读到请求后先
   `_release_global_state()`（清挂件主题重刷回调表与字体缓存——都绑在已销毁的
   解释器上），再进另一套界面的入口。

引导 `bootstrap(mode)`：加载设置 → 网络代理 → 世界包激活态。主循环前装
`_install_hang_watchdog()`（卡死转储）。两套入口（`main.py`）：

- `run_mini(boot)`：固定暗色 → `dpi.virtualized_dpi()` 内建 `tk.Tk()` → `MiniApp`
  → mainloop → 返回切换请求；
- `run_professional(boot)`：设 CTk 色主题与配色（必须在建任何控件前
  `apply_palette`）→ 子进程启动屏（§5）→ 回退加载窗 → 任务泵逐项构建
  （0.10 资源 → 1.00 完成）→ `root.after(120, _handoff_to_main)` 用主窗口**原位
  替换**加载窗（几何与状态从启动屏回报）。

专业窗口（`app/window_manager.py::MainWindowManager`）1280x720，左侧导航栏 +
右侧内容，6 个页面平面 lift 切换（无页面栈）：探索 / 挑战 / 资源中心 /
剧本编辑 / 地标管理 / 描述管理（`ui/navbar.py::NavigationBar._PAGE_GROUPS`）；
设置是模态对话框不是页面。世界包拥有 `scenarios` 时锁「剧本编辑」页。

| 触发点 | 链路 |
|---|---|
| 专业 → 挂件：导航栏「⇄ ME模式」 | `ui/navbar.py` → `MainWindowManager.prompt_switch_to_mini`（副本进行中拒绝）→ `switch_ui_mode(MODE_MINI)` → `switch_to` |
| 挂件 → 专业：挂件标题栏「⇄」 | `ui/mini/app.py::MiniApp.switch_to_professional`（副本进行中拒绝）→ 注入的 `_switch_ui` → `switch_to` |
| 下次启动偏好：设置对话框「启动界面模式」 | `ui/settings/__init__.py::_on_ui_mode_changed`——只写 `ui_startup`，**不重建窗口** |

副本会话进行中两套界面都拒绝热切换；`ui_mode` 只在切换时落盘（退出走
`os._exit`，没有退出钩子）。

## 2. 挂件版机制（`ui/mini/`）

窗口默认 `360x620`（最小 330x470），副本客户区基准 1280x720。

**低像素三条规则**（`ui/mini/pixel.py` 模块 docstring）：直角（无圆角、2px 硬
描边）、有限色（16 色调色板 `PALETTE`，每项 `(亮, 暗)` 二元组，`pick(name)` 按
`core/appearance.py::is_dark()` 取单色）、点阵字（位图字形字体 + **负数像素字号**
——正数是磅、会乘 DPI 漂移，落不到内嵌位图上；纯西文判定 `is_latin`，混排
`split_runs` 分段换字体）。控件全部原生 tkinter，由像素工厂提供：`Panel /
PixelButton / PixelEntry / PixelText / PixelScrollbar / ScrollFrame / CycleRow`，
主题重刷经 `appearance.subscribe(refresh_theme)`。图像处理
`pixelate(image, size, colors, scale)`：LANCZOS 缩小 →（可选）合成底色后
MEDIANCUT 量化 → 整数倍 NEAREST 放大。

**调查掷局**（`ui/mini/investigation.py::Investigator.investigate`）一次掷三样：

| 掷什么 | 规则 |
|---|---|
| 剧本（副本方案） | 全集里掷；有位置时先按 `dungeon/admission.py::check_entry_requirements` 过滤可达方案（同地址维度 / 距离上限 / 身高区间）；全都进不去则放宽为全集并注明「地址已放宽」 |
| 取材表 | 世界包锁定 `material_table` 时不掷；否则在可用组里随机掷一，掷中即应用（与资源中心同一路径 `context.update_material_table`） |
| 世界包线索 | 只掷未启用且清单无错的包、按当前位置的地址维度过滤；**只出线索不启用** |

启动后 80ms 首掷（`MiniApp._first_investigate`）；掷中剧本 / 取材表立即生效并
保存设置。

**覆盖式屏幕**（`ui/mini/screens.py`）：挂件版没有独立弹窗——全部用同一窗口内
整窗换屏：`Screen` 基类（◀ 返回键 + 标题 + body），`MiniApp.push_screen(key) /
pop_screen()` 管栈；屏幕有角色档案 / 设置 / AI 服务商 / 挑战列表 / 挑战确认 /
世界包 / 聊天（唯一无标题栏的屏）/ 整窗提示与确认。没有点击穿透，置顶窗口的
层级冲突因此不存在。

**窗口置顶**（`ui/mini/topmost.py::apply`）：先 `attributes("-topmost", …)`；
Windows / macOS 该属性可信，Linux 再走 EWMH
（`ui/hosting/x11.py::state_above` 组装 `XClientMessageEvent` 发给 root，
`is_above()` 回读确认，失败重发一次）；窗口未映射时不可信，`<Map>` 事件后重放
一次。能力探测 `available()`：Linux 看 root 的 `_NET_SUPPORTED` 是否含
`_NET_WM_STATE_ABOVE`；环境不支持时设置屏该项置灰，强设失败回退为关并提示。
Windows 侧另有 DWM 标题栏暗色（`MiniApp._apply_titlebar_theme`）。

**DPI**（`ui/mini/dpi.py::virtualized_dpi`）：CTk 建根窗口时已把进程设成
per-monitor DPI 感知，挂件按 96 DPI 写死像素会随缩放漂移；该上下文管理器在
挂件建窗前把**当前线程**切到 DPI 非感知（`SetThreadDpiAwarenessContext`，
Win10 1607+），退出时还原（否则重建的专业界面也会变非感知）。非 Windows 全为
空操作。专业模式的对应处理是 `ui/ctk/fonts.py::align_native_scaling(root)`。

## 3. 主题外观

**外观广播**（`core/appearance.py`）：模块级单值 `Light / Dark`（默认 Dark），
`set_mode()` 归一后遍历订阅者广播；`resolve(color_value)` 把 `(亮, 暗)` 二元组
按当前模式取单色。当前订阅者只有挂件的像素重刷；挂件恒暗色（`run_mini` 里
`set_mode(DARK)`）。

**配色文件**（`assets/theme/Slate.json` 暗色 / `Classic.json` 亮色，结构四层，
`ui/ctk/theme.py`）：

| 层 | 内容 | 引用形式 |
|---|---|---|
| `primitives` | 原子色阶（唯一允许裸 hex 处） | `$prim:"slate.700"` |
| `roles` | 语义角色，亮暗成对 `[light, dark]` | `$role:"border-*"` |
| `vars` | 页面常量（对外接口），常量名前缀即所属模块 | `$pair / $map` |
| `mode` | 可选声明 `light / dark`——声明后为「单观感配色」，成对 token 允许只写一侧 | — |

`apply_palette(name)` 运行时换配色：新值**就地写入**原对象（已建控件持有的同一
对象随之生效）；不可变单色 token 在 `sys.modules` 里按 `is` 判定替换各模块的
同名全局量；配色声明了 mode 时同步 `ctk.set_appearance_mode`。
`refresh_widgets()` 显式让全部 CTk 控件重走外观回调（明暗不变时官方不会触发）。

**设置键**：`theme_palette`（系统浅色用，默认 Classic）、`theme_dark_palette`
（系统深色用，空=跟随默认，默认 Slate）、`color_theme`（CTk 内置色主题）。
系统亮暗用 `darkdetect`（`system_mode()`），主窗口每 2s 轮询、生效配色变化时
全窗遮罩重刷（`MainWindowManager._poll_system_mode / apply_settings`）。CTk
运行时补丁（`ui/ctk/ctk_patch.py`，import 即生效）：外观切换时同步刷新控件的
tkinter Frame `bg`、修复带 `textvariable` 的 placeholder。

## 4. 中文字体解析（`ui/ctk/fonts.py`）

| 平台 | 首选 `cjk_family()` | 回退候选（按序） |
|---|---|---|
| Windows | Microsoft YaHei | → 微软雅黑 → SimHei → Arial |
| macOS | PingFang SC | → Hiragino Sans GB → STHeiti → Heiti SC → Arial Unicode MS → Microsoft YaHei → Helvetica |
| Linux | Noto Sans CJK SC | → Noto Sans SC → WenQuanYi Micro Hei → WenQuanYi Zen Hei → Droid Sans Fallback → DejaVu Sans |

- 用户可配置字体的跨平台映射 `font_family_for(name, default)`：非 Windows 上
  Windows 独有字体（宋体 / 仿宋 / 楷体 / 微软雅黑等）落到 `cjk_family()`，
  `Consolas` 落到对应平台等宽字体，其余原样。
- 三个场景的设置键与缺省：报告正文 `report_font`（Windows 缺省仿宋）、描述文本
  `desc_font`（等宽）、副本正文 `dungeon_font`（`dungeon_settings.json`，缺省
  cjk 首选）；设置对话框用 `tkfont.families()` 校验存在性。
- `align_native_scaling(root)` 把 Tk `tk scaling` 对齐 CTk 的 `widget_scaling`
  并跟随系统缩放（原生控件的磅→像素换算与 CTk 一致）。
- 挂件模式另有一套点阵字体候选（`ui/mini/pixel.py::_FONT_CANDIDATES /
  _LATIN_CANDIDATES`），与 professional 字体体系无关，见 §2。

## 5. 启动屏

启动屏跑在**独立子进程**（`ui/ctk/splash.py::splash_process`，自有 Tk 事件循环，
主进程同步构建界面不影响其流畅度）；必须在创建任何 Tk 窗口之前拉起。配色在
子进程内先于控件构建应用，保证与主界面同色。Pipe 协议：

| 方向 | 消息 | 含义 |
|---|---|---|
| 主 → 启动屏 | `("progress", value, detail)` | 更新进度条与详情 |
| 主 → 启动屏 | `("error", message)` | 初始化失败，转错误展示 |
| 主 → 启动屏 | `("request_geometry",)` / `None` | 请求几何 / 关闭 |
| 启动屏 → 主 | `("geometry", state, geometry_str)` / `("close_requested",)` | 回报几何 / 用户点了关闭 |

主进程任务泵逐项构建并 50ms 轮询取消；构建完成走 `_handoff_to_main`：按启动屏
回报的几何 + 状态（最大化 / 最小化）让主窗口**原位替换**，再关启动屏。子进程
拉不起来时回退进程内 `LoadingWindow`。`LoadingPage`（标题 + 进度条 + 详情）
另复用为主题切换的全窗遮罩。

## 6. 更新检查

**只在用户显式触发时发起网络请求**——不做启动自动检查、不做后台轮询、无设置键
（`services/update_check.py` 模块 docstring）。入口是维护子命令
`python main.py check-update`（`app/maintenance.py::dispatch`，命中维护子命令
则主程序不启动）：

- 取数 `fetch_latest_release()`：GitHub Releases latest API，UA
  `constant-girl/<APP_VERSION>`，超时 10s；
- 版本解析 `parse_version()`：支持 `v` 前缀与预发布后缀，预发布序
  alpha < beta < rc < 正式；`compare_versions()` 给出落后 / 相同 / 领先；
- 结论用极简纯 tk 窗口展示（无控制台依赖，打包版 pythonw 可用），附
  「打开发布页」；`apply-update` 是占位提示（请到发布页下载覆盖）。

## 7. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 模式常量 / 两键 / 启动偏好解析 | `services/ui_mode.py::MODE_PRO / MODE_MINI / UI_MODE_KEY / STARTUP_MODE_KEY / resolve_startup_mode` |
| 调度循环 / 引导 / 看门狗 | `app/shell.py::run_app / bootstrap / _install_hang_watchdog` |
| 热切换（销毁重建 / 清场 / 跨根清理） | `app/shell.py::switch_to / _detach_ctk_window / _quiesce_root / _release_global_state` |
| 挂件入口（DPI 虚拟化） | `main.py::run_mini`、`ui/mini/dpi.py::virtualized_dpi` |
| 专业入口（任务泵 / 原位替换） | `main.py::run_professional / _handoff_to_main` |
| 专业窗口结构 / 页面锁定 / 系统亮暗轮询 | `app/window_manager.py::MainWindowManager`（`show_page / _locked_pages / _poll_system_mode / apply_settings`） |
| 挂件主窗口 / 换屏栈 / 调查 UI / 置顶接线 | `ui/mini/app.py::MiniApp`（`push_screen / investigate / set_topmost / switch_to_professional`） |
| 16 色调色板 / 像素控件工厂 / 图像像素化 | `ui/mini/pixel.py::PALETTE / pick / Panel / PixelButton / ScrollFrame / CycleRow / pixelate` |
| 点阵字体 / 负像素字号 / 混排分段 | `ui/mini/pixel.py::_FONT_CANDIDATES / is_latin / split_runs / font` |
| 调查掷局 | `ui/mini/investigation.py::Investigator.investigate / _roll_scenario / _roll_material / _roll_world / apply_material` |
| 覆盖式屏幕 | `ui/mini/screens.py::Screen` 与各屏类 |
| 置顶落地 / EWMH / 顶层窗口上溯 | `ui/mini/topmost.py::apply / available`、`ui/hosting/x11.py::state_above / is_above / top_level_window` |
| 外观广播 | `core/appearance.py::set_mode / subscribe / resolve / is_dark` |
| 配色加载 / 就地换配色 / 重绘 | `ui/ctk/theme.py::_load_palette / apply_palette / refresh_widgets / resolve_system_palette / DEFAULT_PALETTE` |
| CTk 运行时补丁 | `ui/ctk/ctk_patch.py::_install_appearance_bg` |
| 字体回退链 / 跨平台映射 / 磅像素对齐 | `ui/ctk/fonts.py::_PLATFORM_FONTS / cjk_family / font_family_for / align_native_scaling` |
| 字体缺省（报告 / 描述 / 副本） | `ui/ctk/fonts.py::report_font_default / desc_font_default / dungeon_font_default` |
| 设置对话框外观卡 | `ui/settings/__init__.py::SettingsDialog._build_display_block` |
| 启动屏子进程 / 加载页 / 回退窗 | `ui/ctk/splash.py::splash_process`、`ui/ctk/loading.py::LoadingPage / LoadingWindow` |
| 更新检查服务 / 子命令入口 | `services/update_check.py::fetch_latest_release / parse_version / compare_versions`、`app/maintenance.py::dispatch / _run_check_update` |
| 版本与仓库常量 | `paths.py::APP_VERSION / APP_NAME / APP_SLUG / APP_REPO_URL` |
