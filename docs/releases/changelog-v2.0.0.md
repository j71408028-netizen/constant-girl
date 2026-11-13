# v2.0.0 变更记录（v1.0.0 → 2026-11-09，alpha 全程 + beta 起点）

本文记录 `v1.0.0`（2026-10-09）之后到 `HEAD`（2026-11-09）之间的全部变更。

**本文不是一次发布的说明。** 这段区间**没有任何标签**（`git tag -l` 只有 `v1.0.0` 与
`v1.0.0-preview`），但**版本号是真实的**：`paths.APP_VERSION` 在 `a35fc89`（2026-10-05）
从 `1.0.0 preview` 改成 `2.0.0 alpha`，并在整段区间内一直保持 alpha，直到
2026-11-09 改成 `2.0.0 beta`（该次改动**尚未提交**）。

> **版本号与分界的一致性原则**：分界提交的选择必须与版本号改动**同向且不早于它**——
> alpha 只能标在改号之后的提交上，beta 同理。本文严格按此执行：
> 所有 alpha 段起点都 ≥ `a35fc89`，且 beta 目前只有一个起点，没有任何历史改动被算作 beta。

> **关于 1.x**：区间前段（`db559a6`~`a35fc89` 之前）一度按功能世代规划过 `v1.1.0`~`v1.4.0`，
> 那套划分已作废——alpha 后期把那些设计推翻重做。当前口径：`v1.0.0` 之后**直接进 2.0 线**，
> 中间不补任何号（见 [release.md §9](../ops/release.md)）。

| 项目 | 基线 | 当前 |
|---|---|---|
| 标签 | `v1.0.0`（附注标签） | 无（`v2.0.0` 未发布） |
| 定型提交 | `9785356` | `54cba4d` |
| 日期 | 2026-10-09 | 2026-11-09 |
| 版本号（`paths.APP_VERSION`） | `1.0.0` | `2.0.0 beta` |
| 提交差距 | — | 领先 **284 个提交**（无分叉） |
| 变更规模 | — | **425 个文件、+106331 / −13317 行**（含 `v1.0.0` 代码在同日内被改名 / 移动造成的重复计入，见附注） |

---

## 一、分段（提交为主，版本号为辅）

分两类段：**P 段**（版本号仍是 `1.0.0 preview`，事后曾规划过 1.x，现已作废）与
**A 段**（`APP_VERSION` 已是 `2.0.0 alpha`）。**分界提交是主标识，版本号是辅助标识**，
两者一致——alpha 段一律不早于 `a35fc89`。**区间内没有任何 beta 段**：beta 从本次未提交的
改号起才成立，其下尚无提交。

| 段 | 起点提交 | 版本号（该提交上） | 日期 | 主题 |
|---|---|---|---|---|
| **P1** | `db559a6` | `1.0.0 preview` | 09-04 | 地址系统与档案重写 |
| **P2** | `a22fb2d` | `1.0.0 preview` | 09-26 | 副本结构大改与组件化 |
| **P3** | `e3dc12f` | `1.0.0 preview` | 09-28 | ME 模式与热切换 |
| **P4** | `f924adc` | `1.0.0 preview` | 10-02 | 小游戏 + 音效 + 角色聊天 |
| **A1** | `a35fc89` | **`2.0.0 alpha`**（本提交改号） | 10-05 | 目录分层重构 |
| **A2** | `7015a4a` | `2.0.0 alpha` | 10-06 | Linux 支持 + 工程化 + 发布打包器 |
| **A3** | `93b0e59` | `2.0.0 alpha` | 10-09 | 聊天面板改版 + 文档分组 + 副本子进程化 |
| **A4** | `b5a1eab` | `2.0.0 alpha` | 10-12 | 音频总线单一真相源 + 触发器视效与条件组合 |
| **A5** | `7409330` | `2.0.0 alpha` | 10-14 | 上屏游标三态机 + 纯文稿章节 |
| **A6** | `5e8a59b`（merge） | `2.0.0 alpha` | 10-17 | imgui-bundle 迁移（P0–P8）+ 方案关系图 |
| **A7** | `233f6e8` | `2.0.0 alpha` | 10-30 | 资源信封 / `Ref` / 取材表合并 / 地址伴随 |
| **A8** | `3460656` | `2.0.0 alpha` | 11-09 | 角色深水区 + 术语统一 + 更名 ConstantGirl |
| **B1** | `HEAD`（本次改号，**未提交**） | **`2.0.0 beta`** | 11-09 | **beta 起点——尚无任何提交** |

> A6 是 merge 提交，其父链上的开发提交（`5cb1024` P0 → `6c0b706` P8）分布在
> 10-15 ~ 10-17，**晚于** A4 / A5 的日期。按提交拓扑，A6 的开发确实在 A4 / A5 之后，
> 只是合并时点被记成 10-17。A6 之后的一小段（`69dbd61`~`1beb661`，10-16 ~ 10-18，
> autopilot 适配与章节对话框改版）归入 A6。
>
> **B1 没有代码改动。** `paths.APP_VERSION` 改成 `2.0.0 beta` 是 2026-11-09 的工作区改动
> （尚未提交），它标记阶段而不是标记一次变更。因此**本文件的任何历史改动都不属于 beta 段**，
> beta 的内容要从下一个提交开始记。

**分代统计**（`git diff --shortstat`）：

```
db559a6..a22fb2d => 138 files, +20877 -6664   |  19 commits   # P1 地址 / 档案 / 演化
a22fb2d..e3dc12f =>  51 files,  +9030 -1090   |   2 commits   # P2 副本结构大改
e3dc12f..f924adc =>  46 files,  +8896   -58   |   2 commits   # P3 ME 模式
f924adc..a35fc89 => 129 files,  +6137 -1679   |   2 commits   # P4 小游戏 / 音效 / 聊天（含改号）
a35fc89..7015a4a =>  77 files,  +1865 -1263   |  26 commits   # A1 目录分层
7015a4a..93b0e59 =>  91 files,  +8801  -594   |  22 commits   # A2 Linux + 工程化 + 发布工程
93b0e59..b5a1eab => 150 files,  +7133 -2417   |  25 commits   # A3 聊天面板 / 文档分组 / 子进程化
b5a1eab..7409330 =>  66 files,  +6790 -1231   |  20 commits   # A4 音频总线 + 触发器视效
7409330..5e8a59b =>  93 files,  +8436 -3912   |  19 commits   # A5 上屏游标 + 纯文稿章节（含分支提交）
5e8a59b..233f6e8 => 221 files, +29269 -4937   |  84 commits   # A6+A7 imgui 之后 → 资源层重排
233f6e8..HEAD    => 221 files, +15554 -8675   |  61 commits   # A8 角色深水区 + 术语
```

> 每段都能对上表。A1 的 26 个提交含目录分层的全部中间检查点（`3c0737f` 等），
> 这一段是纯位移为主、增量集中在守卫与包门面。
>
> **A6 的提交数不能用 `rev-list` 读**：`5e8a59b` 是 merge，P0–P8 那 9 个分支提交
> 只在 `7409330..5e8a59b` 的 diff 里体现为一次合并结果，`rev-list --count` 只数到 19。
> 要按开发量读，用 `git log --oneline 5cb1024^..6c0b706`。

**合并视角**（不想读这么多段时）：

```
9785356..a35fc89  => P1–P4，版本号仍是 1.0.0 preview（1.x 规划已作废）
a35fc89..HEAD     => alpha 全程（10-05 → 11-09）
HEAD              => beta 起点，尚无提交
```

---

## 二、结构性不兼容（读这一节就够判断要不要迁移数据）

这一代是**破坏性**的：v1.0.0 的 `data/` 里大部分文件已不被读取，部分读取路径都换了。
迁移入口共用 `services/migration_v1_to_v2.py` 转换内核：发行包根目录的「迁移旧版数据」
启动器（`app/maintenance.py`），或源码运行 `python scripts/migrate_v1_to_v2.py`（幂等，
`--apply` 前先整目录备份到 `<data>.rollback-<时间戳>/`），改不动的内容会列成
「需要人工处理」清单而不是静默跳过。

### 2.1 目录与资源布局

| v1.0.0 | 当前 |
|---|---|
| `packs/dungeons/<名>/` | `packs/scenarios/<id>/`（`scenario` 取代 `dungeon` 作资源类型名） |
| `packs/landmarks/<名>.json`（JSON 数组） | `packs/landmarks/<id>.csv` + `<id>.addr.json` + `<id>.meta.json` |
| `packs/quips/<名>.json` | `packs/quips/<id>/quips.csv` + `config.json` + `<id>.meta.json` |
| `static/{names,news,presets,personalities}/<组>.csv` | `static/materials/<组>/{names,presets,personalities,news}.csv`（四表整组） |
| `static/behaviors/<名>/` | `static/behaviors/<id>/` + `<id>.meta.json`（新增：话题表、小游戏两类资源） |
| 根目录 `logic.py` / `models.py` / `ai.py` / `context.py` / `behavior_runtime.py` | `core/` 包（`core/logic/` 四子模块再导出全部公开名） |
| `ui/common/` | `ui/ctk/`（专业组件）与 `ui/hosting/`（进程与宿主），`ui/common` 名号退役 |

**资源 id 规则**：新 id 必须是小写英文 / 数字 / `.` / `_` / `-`。中文名或非法字符的名字
无法自动生成合规 id，迁移脚本会逐条登记。已带映射的内置资源：

```
landmarks:  ChineseMix → chinese_mix     Extension → extension
quips:      Events → events              PixelGame → pixel_game
scenarios:  _default → default           巨影临城 → juying_lincheng
```

### 2.2 设置键

- 四张取材表键（`name_table` / `news_table` / `preset_table` / `personality_table`）
  合并为整组切换的 **`material_table`**。四键指向不同组时取多数并交人工确认。
- 副本独占设置搬进 `data/user/dungeon_settings.json`；资源域设置搬进
  `data/user/resource_settings.json`。
- 已无消费者的键删除：`theme_mode`、`quip_rate_factor`、`voice_proxy`。
  配色改为单观感文件 + 系统亮暗解析，音量改为总线滑条。

### 2.3 副本方案字段与触发器动作

| v1.0.0 | 当前 |
|---|---|
| `view_mode`（`story` / `game`） | `coupling_level`（`velum` / `solea` / `bulla`）——**语义映射**，逐条人工确认 |
| `custom_attrs` | `evolution_attrs` |
| `dungeon_id`（档案、结局索引） | `scenario_id` |
| 触发器 id 作引用 | 触发器名称作引用 |
| 动作 `background` / `sensitivity` / `sensitive` | 由**章节**的 `background` / `sensitivity` 字段承担 |
| 动作 `ending` | 由「结束章节」（章节 `ending=true`）承担 |

### 2.4 角色档案与行为包

- 旧的演化三标量 + 三平行列表 → **`evolution` 表**（行集，每行一次演化）。
- 性格 `step_intrusion` / `step_destruction` → `depth_intrusion` / `depth_destruction`，
  并补 `gravity` 列（重力）。
- 耐久表键 `名称@地址` → **`Ref`** 文本（资源引用，取代字符串拼接）。
- 行为包钩子改名：`evolve_step_rates` / `decay_step_rates` / `nudge_step_rates` →
  `evolve_depths` / `decay_depths` / `nudge_depths`。旧包只体检不改写。
- 行为包 `select` 域改名 **`report`**；新增 `character` / `chat` / `profile` / `offline` 域。
- 回放文件（`.replay.json`）**不做改写**：旧回放只能在新版里当历史记录看，不能续播。

### 2.5 运行环境

- **Python 3.11+**（v1.0.0 是 3.10+）。`imgui-bundle==1.92.900` 只发 cp311+ wheel。
- 副本渲染后端 **Dear PyGui → imgui-bundle**（原 `dearpygui` 依赖移除）。
- 新增支持 **Linux（X11 / XWayland）**与 **macOS（arm64 只有 wheel）**。
- 新增依赖：`imgui-bundle`、`numpy`、`darkdetect`；可选 `edge-tts`（语音）、
  `miniaudio`（语音物理效果）、`pywebview`（内置小游戏窗口，Windows 走 WebView2）。
- 单文件名改号：`GiantessGenerator` → **`ConstantGirl`**，数据目录 `constant-girl`
  （`_LEGACY_SLUGS = ("GiantessGenerator",)` 承接旧目录）。

---

## 三、新功能

### 3.1 地址系统与地标

- `core/address_model.py`：**地址**是分层空间路径（区域 → 群组 → 个体），带 `relate()`
  判定两地址的关系（同级 / 上下级 / 无关）。地标按地址注册，探索时按地址距离与身高区间
  收窄候选池。
- `services/exploration/address_index.py` / `address_plan.py`：地址索引与规划；
  `services/worlds/address_registry.py`：世界侧的地址注册表。
- `data/packs/landmarks/chinese_mix.addr.json`：地标风格的**地址伴随文件**，与 `chinese_mix.csv` 同 id。
- 地标尺寸 12 档（`0~3米` … `300千米以上`），与观测等级、ME 尺度档三者并行不替换。

### 3.2 角色演化与报告引擎

- 演化状态从散落的标量与平行列表收为 **`EvolutionRecord` 行集**，快照按初始 / 可变字段分层
  （`dungeon` 与 `core/models` 两侧同口径）。
- 报告侧拆成**引擎**（产出结构化数据，`services/exploration/report.py`）与**呈现**
  （拼文本，`report_text.py`）两层。
- **选取仲裁器**（`services/exploration/arbiter.py`）：地标选取与描述选取配对，用车道 +
  联合分决定，硬闸与物理走查不开放给行为包。
- 环境一致性软权重、环境偏好学习、离线环境因子在线沉淀，聚合进**空间档案**
  （`services/character/spatial.py`）。
- **作息**派生层（`rhythm.py`）：从演化表即时推导作息与活动范围，不持久化。
- 档案文本化层（`profile_text.py`）四个入口是行为包 `profile` 域钩子。

### 3.3 副本世代重构

- **章节 / 触发器 / 结局**三层模型：章节带地点、取景、提示词、演化配置；
  触发器由「固定顺序位置 + 轮次防重发」判定（`ending` 触发器退场，改由章节承担）；
  条件支持**一层或 / 且嵌套组合**（`dungeon/rules.py`）。
- 触发器动作新增**窗口视效**（闪光 / 振动 / 反色 / 色差分离），短视效升级为**效果覆盖**。
- **组件包**（`dungeon/window/component_pack/`）：`text_card` / `text_nvl` / `text_gradient` /
  `attr_bar` / `proc_log`，各自带**代管区**（停靠侧由窗口视觉设置决定）。
- **分句器**与**显示段落队列**（`dungeon/splitter.py`）：上屏统一为限速游标，点击三态机，
  自动播放事件驱动；插入触发器段落也走同一条队列。
- **纯文稿无 AI 章节**（`dungeon/script_text.py`）：现成文本逐段推进 + 脚本指令解析。
- **结局**：图标（`ending_icon.py`）、结局回顾快照、回放账本还原、合并审计。
- **高亮**改为正文标记语法，AI 生成段落也能高亮。
- **方案关系图**（`dungeon/scenario_graph.py` + `graph_lint.py` + `ui/scenario/graph_view.py`）：
  自绘画布，退场 `networkx` / `graphviz` 依赖。
- **章节地点与取景**：独特地标内联进章节，常见地标按私有名过滤（`dungeon/scene.py`）。

### 3.4 ME 模式与挂件界面

- `services/ui_mode.py`：专业模式 ↔ ME（挂件）模式，**热切换**（销毁根窗口 + 登记请求 +
  落盘，不是重启）。
- `ui/mini/`：`app` `screens` `params_panel` `state_card` `report_view` `investigation`
  `pixel` `dialogs` `dpi` `topmost` —— 原生 tkinter，不依赖 CTk。
- 挂件版聊天屏与报告区同款面板，消息气泡化；离屏画布改**分块增量纹理上传**。
- 窗口置顶走 EWMH 正路（Linux/X11 不支持时置灰开关）。

### 3.5 音频总线与语音

- `dungeon/audio/`：`buses`（总线层单一真相源）/ `chapters`（章节音轨）/ `speech`（TTS）/
  `voice_fx`（语音物理效果）/ `preview`（预听）。
- 音量收敛为**总线层单一真相源**，设置页一条总线滑条（原作者侧 0–100 改为 5 档并自动迁移）。
- 效果响度改为**声明式设计量**，与总线电平按档位相乘。
- 语音合成支持网络代理，与 AI 文本生成共用 `core/netproxy.py`；失败原因说清不再静默。
- Solea / Bulla 对话可出合成语音（`edge-tts`，可选）。

### 3.6 小游戏

- `dungeon/minigame_pack.py` + `dungeon/window/minigame/{base,stage}.py`：
  小游戏作为**资源类型**打包（`data/packs/minigames/<id>/game.py` + `manifest.json`）。
- 内置两个：`escape_giantess`（逃脱）、`reaction`（反应）。
- 窗口托管：`ui/hosting/mini_game_host.py`（`pywebview`，Windows 走 WebView2，可选依赖）。

### 3.7 角色聊天

- `services/chat/`：`coordinates`（介入度 / 破坏性**三轴坐标**）/ `topic_kinds` +
  `topic_tables`（话题类型）/ `topic_lens`（按存档视角渲染）/ `persona`（人设）/
  `delivery`（投递）/ `events` + `experience_events`（事件）/ `effects`（**世界效果层**）。
- **多身份线程**：玩家身份仓库（`persistence/player_identity_repo.py`）与聊天线程枚举，
  按玩家身份切换线程、未读聚合（`services/chat` 的身份门面）。
- 聊天接入**关系认知与紧张度**、偏好历史结论与实时情境提示。
- 提示词与节奏可被行为包 `chat` 域覆盖。

### 3.8 资源层重排

- **资源信封**（`persistence/resources/envelope.py`）：每份资源配 `<id>.meta.json`，
  带内容哈希；`status` 扩预览 / 稳定，新增特色 `traits` 与 `language`。
- **资源类型清单单一声明**（`core/resource_spec.py`）：容器形状、主文件模板、字段清单、
  id 规则、存储根、设置键、显示名与选择粒度只写一处；派生出口
  `persistence/resources/registry.py`。
- **`Ref`**（`core/resource_ref.py`）：资源地址索引与耐久键统一为引用对象，取代拼接字符串。
- **取材表合并**（`persistence/material_tables.py`）：四张独立表 → 一个 `csv_bundle` 容器，
  整组切换；成员可缺席，缺谁落到内置 `default` 组同名文件。
- **资源中心**改为**在线 / 社区 / 本地三区**导航，世界包与挑战包为带图标方形卡片，
  自设置面板独立成页。
- 单文件 JSON 容器主文件去掉扩展名；地标 / 描述风格主文件改为 CSV（含容器目录）。

### 3.9 角色深水区

- **出身烙印**（`ModelTuning`）：角色创建期按世界规则派生初始模型参数，
  `CreationService.derive_model_tuning` 是唯一派生入口；离线与空间先验的消费端迁移至此。
- **世界履历**与**出身导出展示**；删 `recover_evolution` 清账（离线恢复改走计划钩子 + 执行层）。
- **人物档案面板**（运行期）：人物表按定位拆分字段，角色账本按初始 / 可变字段分层；
  卡片改增量刷新。
- **临时称呼**（`intro_as`）与**揭示合并**。
- 性格参数面板改用**潜质 / 深度**两段文案；性格形容的敏感值转交策略值展示。

### 3.10 工程化

- 目录分层强制：`infra → core → dungeon → persistence → services → dungeon_window → ui → app`，
  由 `tests/check_import_graph.py` 守卫，`KNOWN_EXCEPTIONS` 已清零。
- 根目录冻结为 `paths.py` + `main.py` 两个文件。
- `tests/run_checks.py`：按前缀自动发现、子进程运行、强制 UTF-8；离线门禁与冒烟分档。
- CI 两档工作流：`.github/workflows/checks.yml`（离线门禁）、`gui-smoke.yml`（每晚 GUI 冒烟）。
- `build/release/package.py`：跨平台发布打包器（干净 git worktree、按 tag 的 requirements 装依赖、
  `--backend pyinstaller|nuitka`、源码归档 / 校验和 / 发布说明）。
- Linux：`ui/hosting/x11_boot.py` 的 `boot_x11()` 必须在任何 tkinter / GL 栈 import 之前执行；
  `XInitThreads` 引导、X11 错误处理器收窄到 `BadWindow` / `BadDrawable`。

### 3.11 界面

- **配色**：单观感文件（`assets/theme/Classic.json` / `Slate.json`）+ 系统亮暗解析；
  设置页简化为默认与系统深色两档。
- **控件**：轻量化 `OptionButton`，下拉框支持逐项文字颜色。
- **副本窗口**：文本卡片毛玻璃、大屏自适应、NVL 覆盖层百分比边距、渐变栏侧边代管区。
- **章节 / 触发器对话框**：固定分栏 + 折叠卡片；章节配色预设精简为 6 个。
- **设置**：设置项分类修正，副本设置按「即时生效与否」重新分配入口；
  副本窗口内新增独占设置面板，落 `dungeon_settings.json`。

### 3.12 文档与开发者工具

- `docs/` 按读者分组重建：`dev/`（架构）/ `designs/`（机制）/ `users/`（玩家与平台）/
  `ops/`（发版）/ `Dungeon/`（副本子项目）/ `releases/`，并入文档链接守卫
  （`tests/check_docs_links.py`，大小写精确）。
- `docs/terminology.md`：界面术语表，玩家可见词的唯一真相。
- `developer_tools/` 重新入库：`archive_preview` / `behavior_hooks_report` /
  `chat_session_preview` / `evolution_dump` / `lens_preview` / `minigame_preview` / `quip_report`。
- `scripts/`：`dungeon_autopilot`（真窗口 15 场景回归，进 CI）、`escape_sim`（无头小游戏回归，进 CI）、
  `scenario_validate`、`migrate_v1_to_v2`（内核在 `services/migration_v1_to_v2.py`）；`dpg_probe/` 原生崩溃探针留档（DPG 专属 5 支已删）。

---

## 四、修复（仅限问题源自 v1.0.0 的）

**判定标准**：被修的代码路径在 `9785356`（v1.0.0）上**已经存在**，且缺陷在该版本上**可复现**。
v2 期间新写出来、又在新代码里修掉的问题，算新功能的迭代，不进本节——否则「加了多少 / 修了多少」
永远算不清。

### 4.1 实测结论：基本没有

逐条核对下来，**v1.0.0 遗留缺陷几乎没有一条是在 v2 里被「修复」的，它们是被重写消灭的**。
更要紧的是：`changelog-v1.0.0.md` §三列的五条「修复」里，有三条经复核**在 v1.0.0 上并不成立**
（该文件是 append-only 快照，不回改；此处只作勘误记录，供后续引用时避坑）：

| v1.0.0 changelog 的说法 | 复核结果 |
|---|---|
| 演化与 `step_info` 顺序错位，`*_before` 捕获到演化后状态 | **不成立**。`9785356:dungeon/window/engine.py` 先取 `before_state = self.dungeon_state`，再调 `evolve_attributes`，`step_info` 里的 `*_before` 直接读 `before_state` 字段，后续也无覆盖 |
| `context.py` 伤亡累计误缩进，仅在 `consume_points` 分支执行 | **不成立**。`9785356:context.py` 中 `state.total_casualties += ...` 与 `consume_points` 判断是同级语句，不在其分支内 |
| 延迟插入段无条件晋升 | **不成立**。`9785356:dungeon/window/triggers.py` 的 `_consume_pending_insertion` 以 `popleft()` 取队首后立即转交显示，不存在「生成失败仍晋升」的分支 |

> 因此本节**只列一条**，且它同样不是「v2 里修的」，而是 v1.0.0 内部返工：

- **世界包启用时静态表被连坐禁用**：v1.0.0 引入（`255642a`），同版本内返工修掉
  （`02731a0` revert → `652ddb0` 恢复 → `6459699` 修订）。**该问题的修复已在 v1.0.0 之内完成**，
  记录在 [changelog-v1.0.0](changelog-v1.0.0.md) §三；本文不重复计入。

### 4.2 路径存在、但缺陷随重写消失的（列出以备查，不计入修复数）

v1.0.0 上确实存在一个脆弱点，v2 把承载它的模块整段换掉，结构上不再可触发。
**没有可指向的 fix 提交**，不要为它虚构提交号：

| v1.0.0 的脆弱点 | 位置（`9785356`） | v2 怎么消失的 |
|---|---|---|
| 提示词历史直接索引 `step['type']` / `step['text']`，缺字段即 `KeyError` | `dungeon/prompts.py` | 提示词构建拆成构建 / 提交两步（`5e2963c`）并整段重写 |

> 其余曾被怀疑的条目（演化顺序、伤亡累计、延迟插入晋升、空状态标签堆积）经逐条读
> `9785356` 源码**均不成立**，故不列。写 changelog 时不要从旧文档转抄缺陷清单。

### 4.3 v2 期间的结构性改进（不算修复，供对照）

以下常被误记成「修复」，实际是重写带来的能力提升：

- **渲染后端迁移**（`5e8a59b`，P0–P8）：Dear PyGui → imgui-bundle。
- **副本会话子进程化**（`6db0e56`）：会话搬进独立子进程，启动载荷带线格式与往返守卫。
- **上屏统一为限速游标**（`408eeb7`）：点击三态机，自动播放改事件驱动。
- **音频音量收敛为总线层单一真相源**（`b5a1eab`）。
- **聊天气泡列表增量渲染**（`1ae47c7`）；**人物卡片增量刷新**（`dfc0ba0`）。

---

## 五、术语与命名（玩家可见）

| 旧称 | 新称 | 落地提交 |
|---|---|---|
| 敏感效果 / 持续敏感效果 / 敏感效果倍率 | 演化修正 / 持续演化修正 / 演化修正量 | `48e9e68` |
| 初始介入度 / 初始破坏性 | 介入潜质 / 破坏潜质 | `cd51f16` |
| 介入度步长 / 破坏性步长 | 介入深度 / 破坏深度 | `89849f9` |
| 性格二阶量 | 该属性的性格系数 | `89849f9` |
| 副本编辑（导航栏入口） | 剧本编辑（页面键 `scenario`） | `28541e1` |
| 副本方案（编辑器内部，**不变**） | 仍是「副本方案」 | `28541e1` |
| 体型分类 | 观测等级（Small / Medium / Large / Huge / Colossal） | `92eed59` |
| 视图模式 | 耦合等级（Velum / Solea / Bulla） | P2 |
| GiantessGenerator / 巨大娘生成器 | ConstantGirl | `c80630a` |

> 「步进」保留原名（曾短暂改为「推进量」，评估后回退）。全表见
> [术语表](../terminology.md)。

---

## 六、数据与内容

- **内置地标风格**：`chinese_mix`（中式混合）、`extension`。
- **内置描述风格**：`events`、`pixel_game`（各 `quips.csv` + `config.json`；原单文件 JSON 的
  五档结构改为 CSV 长表 + `[summary:…]` 拆列）。
- **内置小游戏**：`escape_giantess`、`reaction`。
- **内置行为包**：`imperial_units`（显示单位改英尺 / 英里，内部仍以米计）。
- **取材表**：`static/materials/default/` 四成员（`names` / `presets` / `personalities` / `news`）；
  性格表 `step_*` → `depth_*` 并补 `gravity`。
- **默认副本方案**：`default`（原 `_default`）；背景图路径改正斜杠。
- **头像与图标**：`assets/icons/{world_pack,challenge_pack}.png`、`assets/templates/`
  档案 HTML 模板三件（`.html` / `.css` / `.js`）入包。

---

## 七、已知缺口

- **区间内无任何版本号锚点**：alpha / beta 只是开发阶段的自称，从未打标，本文用提交哈希分界。
- **旧回放不可续播**：`.replay.json` 不做改写（迁移脚本明确跳过）。
- **中文资源名无法自动迁移**：需在资源中心改名为小写英文 / 数字 / `.` / `_` / `-`。
- **资源尚未齐备**：`APP_VERSION = 2.0.0 beta` 是为了让界面与挂件页脚显示当前阶段，
  不代表可以发版；`v2.0.0` 定稿前需把版本号收敛为纯 `2.0.0` 并补齐资源。

---

## 附：文件清单口径

完整的 425 个文件逐条列出没有溯源价值——大部分是分层重构的纯位移。
按用途查更可靠：

| 想知道 | 命令 |
|---|---|
| 某一段改了什么 | `git diff --stat <起点提交>..<下一段起点提交>`（起点见 §一） |
| 新增了哪些文件 | `git diff --name-status 9785356..HEAD --diff-filter=A` |
| 删除了哪些文件 | `git diff --name-status 9785356..HEAD --diff-filter=D` |
| 某文件何时长成现在这样 | `git log --follow --oneline -- <path>` |
| 旧数据怎么迁 | `python scripts/migrate_v1_to_v2.py --report plan.md` |

删除清单只有 27 条（含根目录 `logic.py` / `models.py` / `ai.py` / `context.py` /
`behavior_runtime.py`、`ui/common/`、`ui/scenario/{dependency_dlg,trigger_mgr}.py`、
`persistence/dungeon_repo.py`、`world_pack_behaviors.md`），是新旧结构差异最浓缩的一份索引。
