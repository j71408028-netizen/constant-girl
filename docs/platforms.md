# 平台支持（Linux / macOS）

> 本文讲 Windows 之外两个平台的**差异与兼容处理**。玩家侧的安装步骤在根
> `README.md`「快速开始」，此处不重复；自检与打包命令的全集见
> `docs/architecture.md` §5.2；反复开关窗口的长压测标准姿势的家在
> `docs/dungeon_window.md` §7，本文只留一句。

## 1. 支持范围总览

| 平台 | 状态 | 说明 |
|---|---|---|
| Windows | ✅ 主力开发与发布平台 | x64 |
| Linux · X11（Xorg / XWayland 下的 `DISPLAY`） | ✅ 受支持 | 全部功能可用；GitHub CI 的 Linux job 也跑在同一形态下 |
| Linux · Wayland + XWayland | ✅ 可用 | 图形界面与副本窗口经 XWayland 显示；窗口置顶取决于窗口管理器（GNOME Shell 实测可用，KWin 待实测） |
| Linux · 纯 Wayland（无 XWayland） | ❌ 不支持 | 副本窗口基于 GLFW/X11，纯 Wayland 后端创建不出窗口 |
| macOS 12+ · Apple Silicon | ✅ 支持 | 发行包为 `ConstantGirl.app` |
| macOS · Intel | ❌ 不支持 | 副本窗口渲染依赖 `imgui-bundle==1.92.900`，该版本只发布 macOS **arm64** wheel，Intel 无从安装 |

Linux 前提：能提供 Tk 图形组件（`python3-tk`）与一个可用的 X display。无显示器
环境可用 `xvfb-run` 跑 GUI 冒烟（软件渲染 llvmpipe 可行但慢）。

macOS 的 Intel 限制来自第三方依赖，不是本项目可为 Intel 单独打补丁绕过的；
在 Intel Mac 上 `pip install -r requirements.txt` 就会失败。

## 2. Linux

### 2.1 依赖与安装差异

- **必须整份安装 `requirements.txt`**：`openai`（AI 功能）在其中；只装部分依赖
  曾出现难查的报错，整份装最省事。`numpy` 也在其中——副本窗口背景合成、小游戏
  画布、挑战数值计算都直接 import 它。
- **不需要 `networkx` / `graphviz`，也不需要系统级 `dot`**：编辑器「章节编排」/
  「触发器依赖」已改为自绘画布，不再出 PNG（见 `docs/designs/dungeon/scenario_graph.md`）。
- 可选依赖的降级表现与 `requirements.txt` 内注释一致：

  | 可选依赖 | 缺失时的表现 |
  |---|---|
  | `edge-tts` | 对话语音不出声（联网合成），副本照常能玩 |
  | `miniaudio` / `soundfile` | 章节语音的「物理效果」退回零依赖的播放侧近似（回声 / 缓抖），方案校验会给出提示；装上即消除 |

- 中文字体（两条链路，都靠系统装中文字体，建议 `sudo apt install fonts-noto-cjk`）：
  - 主界面（Tk / CustomTkinter）走 `ui/ctk/fonts.py` 的家族候选链
    （Noto Sans CJK SC / 文泉驿微米黑），由 Tk 自己按家族名向 fontconfig 取字体；
  - 副本窗口（imgui-bundle）**只认字体文件**，走 `dungeon/window/fonts.py`：Linux 上先问
    `fc-match`（只接受声明覆盖 `zh-cn` 的结果，避免不存在的家族名被替换成拉丁字体），
    查不到再按发行版常见路径回退（Noto CJK / 思源黑体 / 文泉驿 / Droid Sans Fallback）。
    系统里一个中文字体都没有时才会退到 DejaVu Sans——那没有中文字形，中文会是方框；
    窗口开起来后可在过程日志（F12）里看到实际选中的字体文件。
  - 已知取舍：副本窗口按文件建字体，不做集合字体（`.ttc`）内的 face 序号选择，
    Noto CJK 只会取到第 0 个 face（JP）——码位覆盖完整、不会缺字，个别字的写法是
    日文变体；小游戏离屏画布用 PIL 渲染，能按 fontconfig 给的序号取到简体 face
    （详见 `dungeon/window/fonts.py` 模块说明）。

### 2.2 XInitThreads：为什么要每个入口调一次

Tk（专业模式 / ME模式）与副本窗口的 GL 栈（GLFW）在同一个进程里
**各开一条 X display 连接**（产品路径里两者分别在父子进程，只有自检/自动驾驶会同进程
共存），libX11 默认按「单连接单线程」编译——两套工具包各带线程碰同一个 X
server 是 `BadWindow` 与 `ImGui_ImplGlfw_WindowFocusCallback` 段错误的经典成因。

因此每个会建窗口的入口文件在**最顶部**（任何 `tkinter` / 副本窗口 GL 栈之前）都要：

```python
from ui.hosting.x11_boot import boot_x11

boot_x11()          # 调 XInitThreads()，全进程一次性生效
```

已接入的入口：

| 入口 | 位置 |
|---|---|
| `main.py`（专业模式 / ME模式） | 第 5 行，`import tkinter` 之前 |
| `tests/smoke_switch.py` | `ensure_cwd()` 之后（该脚本的 tkinter 都是函数内延迟 import） |
| `tests/smoke_mini.py` | 路径注入之后、`tkinter` 延迟到 `boot_x11()` 之后再 import |
| `scripts/dungeon_autopilot.py` | 路径注入之后 |
| `ui/hosting/tk_host.py` | `TkHost.__init__` 兜底（幂等，覆盖直接 new 宿主的脚本） |

`XInitThreads()` 必须早于**第一条** X 连接；晚调不会报错但没有意义，`boot_x11()` 会在
已经调用过时直接返回上次结果。这一切都有开关：`GIANTESS_X11=0` 可整体关掉 Linux 原生
X11 支持（做有效/无效对比压测用，不是功能开关）。

#### 子进程要在建立 X 连接之前 fork

Linux 的 `multiprocessing` 默认 `fork`：父进程已有的 Tcl/Tk 与 Xlib/notifier 状态会被
整套复制给子进程。父进程**已经建立 X 连接**之后再 fork，子进程里的第二个 Tk 就可能踩到
这条连接的状态。这类故障的日志形态就是下面这三行——Xlib 的 IO 错误由它自己 `exit`，
Python 层拦不到，没有栈可看：

```
XIO:  fatal IO error 22 (Invalid argument) on X server ":99"
      after 34 requests (34 known processed) with 2 events remaining.
```

因此启动屏子进程（`main.py::_launch_splash`）由 `run_professional` 在 `ctk.CTk()`
**之前**拉起，fork 那一刻父进程还没有任何 X 连接。副本会话子进程
（`ui/hosting/dungeon_spawner.py`）只能在主窗口活着时拉起，它自己开的是 GL/GLFW 连接；
这一段若再出现同类现象，第一选择是改用 `multiprocessing.get_context("spawn")`
（Windows / macOS 默认就是 spawn，子进程从干净的解释器起步）。

### 2.3 窗口置顶（`_NET_WM_STATE_ABOVE`）

Tk 的 `-topmost` 在 GNOME Shell / XWayland 下静默失效：既不写
`_NET_WM_STATE_ABOVE`，`attributes("-topmost")` 也一直回报 0。

现在的实现（`ui/mini/topmost.py` + `ui/hosting/x11.py`，纯 stdlib ctypes，不引入
`python-xlib` / `pywinctl`）：

1. 先照常调 Tk 的 `-topmost`（对 KWin 这类 WM 有效）；
2. 再向 root 窗口发 EWMH `ClientMessage`（`_NET_WM_STATE` / `_NET_WM_STATE_ABOVE`，
   `source_indication=1`），只对**窗口管理器认的顶层窗口**发——Tk 的 `winfo_id()`
   在 GNOME 下是客户区子窗口，`wm_frame` 是它的父窗口，`ui.hosting.x11.top_level_window()`
   负责上溯；
3. 回读 `_NET_WM_STATE` 确认（WM 是异步的，最多重试两次）；
4. 窗口尚未映射时无法回读，`<Map>` 事件后会自动再落一次。

**降级**：窗口管理器若没有在 `_NET_SUPPORTED` 里声明 `_NET_WM_STATE_ABOVE`，ME模式
设置页的「窗口置顶」开关会**置灰并标注「本桌面环境不支持」**，而不是留一个点了没反应
的开关；用户在不可用环境里尝试打开时也会收到一次明确提示。

支持矩阵（实测 / 待补）：

| 桌面环境 | X11 置顶 | 备注 |
|---|---|---|
| GNOME Shell（XWayland，mutter） | ✅ 可用 | EWMH 写入后 `xprop` 可读到 `_NET_WM_STATE_ABOVE`（2026-10-06 实测） |
| KWin | 待实测 | `_NET_WM_STATE_ABOVE` 在声明列表里，理论上可用 |
| 其它 WM | 待实测 | 以 `_NET_SUPPORTED` 声明为准，声明即尝试 |

### 2.4 X11 错误兼容处理器

`ui/hosting/x11.install_x11_error_guard()`（仅 Linux）会安装一个 ctypes 的
Xlib 同步错误处理器，用于对付「Tk 事件泵处理到其它已销毁顶层窗口的旧事件」——
Xlib 默认处理器会直接 `exit(1)`，表现为冒烟里的 `X Error of failed request: BadWindow`。

策略（刻意收窄后的口径）：

- `BadWindow(3)` / `BadDrawable(9)`：预期内的陈旧窗口错误，忽略，并把前 3 次记入
  `dungeon.process_log`（副本窗口的过程日志面板能看到）；
- 其它错误码：**照样不退出进程，但每次都记录**（含错误码与 request code）。要把
  默认行为换成"让进程崩"，删掉该函数的调用点即可。

### 2.5 打包与发布

```bash
bash build/linux/build_linux.sh                # 只打包
bash build/linux/build_linux.sh --self-check   # 打包 + 打包自检（需要显示器）
PYTHON_BIN=python3.12 bash build/linux/build_linux.sh   # 指定解释器
```

- **形态**：PyInstaller **onedir**，产物 `dist/constant-girl/`（可执行文件与目录同名），
  另打 `dist/constant-girl-linux-<arch>.tar.gz` 目录包。AppImage / deb 与桌面集成
  （`.desktop`、PATH 安装）不在本期。
- **依赖收集**：与 Windows / macOS 脚本同一套 `--collect-all`（customtkinter / imgui_bundle /
  PIL / openai / numpy），**不带** `zai`（项目没有该依赖）。打包无外部可选依赖
  （关系图不再需要 Graphviz 的 `dot`）。官方显示组件包 `dungeon.window.component_pack`
  由 `component_registry` 以**字面量的函数内 `import`** 加载——不能改回
  `importlib.import_module(字符串)`，否则 PyInstaller / Nuitka 的静态分析看不到，
  打包版会缺整个组件包、静默退回内置文本容器。
- **构建环境**：脚本自建 `.venv-buildlinux` 并 `pip install -r requirements.txt pyinstaller`，
  不污染开发 venv。
- **数据目录**：打包版走 XDG —— `$XDG_DATA_HOME/constant-girl/data`
  （默认 `~/.local/share/constant-girl/data`），首启从包内 `data/packs`、`data/static`
  拷贝出可写副本；源码运行仍用仓库内 `data/`（见 `paths.py`）。
- **打包自检**（`--self-check`）：同一套依赖把 `scripts/dungeon_autopilot.py` 也打成一个包，
  然后
  1. 用临时 `XDG_DATA_HOME` 启动发布包（不碰真实用户数据），确认进程存活且
     `data/{packs,static,user,archives}` 引导成功（有 `xwininfo` 时顺带核对主窗口标题）；
     失败时区分「进程已退出 / 数据目录未就绪」并打印退出码与**完整**的 `app.log`；
  2. 在**打包态**里逐场景真开副本窗口（6 个）：`entry-start`（探索入口 → 进副本）、
     `session-close`（中途快照 + 收尾落盘）、`entry-replay`（入口回放）、
     `chapter-bgm`（章节背景音乐）、`mini-game-py`（小游戏覆盖层舞台）、
     `mini-game-repeat`（可再次触发的小游戏）。`text-components` 不在其中：
     它在 Linux/X11 上曾触发 GL 栈段错误，组件覆盖由 `smoke_switch` /
     `smoke_mini` 与离线 `check_component_pack` 兜底。

  退出码 0 才算通过——这是「打包后仍然能进副本、小游戏触发器还能跑」的可复现证据。
  现场日志统一落在 `dist/selfcheck-logs/`（`start.log` + 每场景一份），每晚 CI 作为
  `package-selfcheck-logs` 产物上传。

### 2.6 CI（GitHub Actions）

| 工作流 | 触发 | 内容 |
|---|---|---|
| [`checks.yml`](../.github/workflows/checks.yml) | 每 PR / 推 `main` | 离线门禁：Ubuntu（Python 3.12 与 3.14 各一轮）+ Windows（3.12）跑 `tests/run_checks.py`（全部离线守卫）、`scripts/scenario_validate.py`（默认方案 0 error）与 `scripts/escape_sim.py`（小游戏逻辑回归，无显示器） |
| [`gui-smoke.yml`](../.github/workflows/gui-smoke.yml) | 每晚 02:00（CST）+ 手动 | xvfb + 软件 GL（llvmpipe）：`dungeon_autopilot --scene all --isolate`、`smoke_mini`、`smoke_switch`；另一个 job 跑 `build/linux/build_linux.sh --self-check` 并上传目录包 |

GUI 用例对长会话与驱动状态敏感（§2.4 与 `docs/dungeon_window.md` §7）：
某条明显 flaky 时先在工作流里注释掉它，保留 autopilot 离线场景组。

压测口径：长压测（反复拆建窗口抓低概率原生段错误）的标准姿势是
`--isolate` + 外层 watchdog 逐轮起子进程、按退出码统计，含 `GIANTESS_X11=0`
的 XInitThreads 对照组——命令与判定见 `docs/dungeon_window.md` §7。平台不适用项
按设计 **SKIP**，不计失败：`native-input` / `native-close` 场景靠 Windows 投原生
按键 / 关闭消息，非 Windows 跳过。

### 2.7 已知限制

- **纯 Wayland 不支持**：副本窗口（GLFW/X11）创建不出来，请用 X11 会话或 XWayland。
- **窗口置顶依赖桌面环境**：GNOME Shell 走 EWMH 可用；不声明该属性的 WM 下开关会置灰。
- **GLFW 低概率原生段错误**：反复 `destroy → create → show` 后偶发
  `SIGSEGV @ ImGui_ImplGlfw_WindowFocusCallback`，Python 层捕不到。属第三方库风险，
  缓解手段是 XInitThreads + 错误处理器收窄 + `--isolate` 压测；长期跟随上游。
- **包形态**：目前只发 tar.gz 目录包，没有 AppImage / deb / 桌面项；运行方式为解包后直接
  执行 `constant-girl/constant-girl`。

## 3. macOS（Apple Silicon）

### 3.1 支持范围

仅 macOS 12+ · Apple Silicon（M1 及更新），Intel 不支持（§1 表；wheel 只发 arm64）。

### 3.2 首次打开（Gatekeeper）

从 [Releases](https://github.com/j71408028-netizen/constant-girl/releases) 下载 macOS 压缩包并解压：

- 直接双击 `ConstantGirl.app`。首次打开需**右键 →「打开」**（未签名/未公证的应用会被
  Gatekeeper 拦下，这是预期行为）。
- 包内同层还有 `.command` 维护入口；若 `.app` 不可用，它会退到裸目录可执行文件。

用户数据写在 `~/Library/Application Support/constant-girl/data`，首启从包内资源拷出可写副本。

### 3.3 字体与显示

中文字体走系统自带字体（苹方 / 冬青黑体 / 宋体），由 `fonts` 的平台分支解析；
找不到时退回默认字体，不会导致启动失败。副本窗口使用原生窗口服务，**不需要 X11/Xvfb**。

### 3.4 CI 两档

[`macos.yml`](../.github/workflows/macos.yml) 在 `macos-latest`（当前为 arm64）runner 上分两档验证：

- **每 PR / 推 main**：整份依赖安装、导入自检、全部离线守卫、默认方案校验、小游戏无头模拟；
- **推 main / 每晚 / 手动**：用官方 `build/macos/build_macos.sh` 打包后核对 `.app` 结构
  （`Contents/MacOS`、`Info.plist`、可执行入口与随包原生库清单）并上传产物。

**真窗口冒烟不在这套 CI 里**：GitHub 托管的 macOS runner 没有 Aqua 登录会话，GLFW 建不出窗口
（实测 22/26 场景超时），窗口/GL/字体验证由 Linux 上的
[`gui-smoke.yml`](../.github/workflows/gui-smoke.yml)（xvfb + llvmpipe）承担。

这些是**自动化证据**，不等于所有平台验收完成。以下项目 CI 无法覆盖，仍需真实用户环境补全：

- macOS 上副本窗口/GL/字体链路的实际运行；
- 下载后带 `com.apple.quarantine` 隔离属性时的「首次打开」体验与公证提示；
- 真实音频外放听感、字体渲染与动画的人眼观感；
- 真实旧版本数据目录的升级路径。

### 3.5 已知限制

- **Intel Mac 不可用**（§1）。
- **未签名 / 未公证**：首次打开需要右键绕过 Gatekeeper。
- 打包产物为 `.app`，暂无 `.dmg` 安装器与桌面集成。
