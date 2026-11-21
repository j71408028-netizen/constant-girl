# 剧本编辑器（面向作者）

> **这一篇回答什么问题**：编辑器分哪些页与标签、字段声明和校验从哪来、剧情页两张
> 编排图怎么读、顶栏校验条怎么分组与跳转、组件 / 固定文本 / 素材怎么进出方案目录。
> **副本方案作者**顺序读完即可；只想看懂编排机制的人从 §3 进；要接组件或诊断相关
> 功能的开发者从 §5 / §4 进。
> 直接相关页：方案字段数据模型与逐字段校验 [dungeon/script.md](dungeon/script.md) ·
> 组件运行时契约 [dungeon/components.md](dungeon/components.md) ·
> 方案目录容器与命名 [resources.md](resources.md)。

## 1. 页面结构：四页签 + 剧情页三标签

入口在主窗口导航栏「剧本编辑」。世界包清单声明拥有 `scenarios` 时，整页锁定为
提示条——此时方案随包只读。

顶栏（编辑器主体在 `ui/scenario/sc_frame.py::ScenarioEditor`）自上而下两层：

1. **方案胶囊**：显示名下拉 + `＋ / ✎ / 🗑`（新建 / 重命名 / 删除）。新建弹出
   `ResourceNameDialog`（id 自动派生，规则见 [resources.md](resources.md) §3）；
   重命名只写信封 `title`；默认方案不可删。
2. **页签轨**：`通用 / 角色 / 剧情 / 组件` 四个互斥页签，第二层右侧是常驻校验条
   （§4）。

| 页签 | 内容 | 编辑方式 |
|---|---|---|
| 通用 | 耦合等级、说话人写法、进入准入（入口地址 / 距离上限 / 身高区间）、进入消耗、初始坐标、初始提示、五类段落分类提示与步进、转移矩阵 | 显式「保存此页面」 |
| 角色 | 她的卡片、主角称呼与身份背景、人物表（重要角色 / 群像）、方案级对话语音、演化量视图 | 防抖自动保存 |
| 剧情 | 章节与触发器列表 + 两张只读编排图（§3） | 对话框编辑、列表保存 |
| 组件 | 文本主组件三选一 + 组件卡片（§5） | 防抖自动保存 |

> 「通用」页里的提示词字段各怎么进 AI，见 [dungeon/prompts.md](dungeon/prompts.md)：
> 初始提示进系统提示的最后一段；五类段落分类提示目前只保存、不参与生成（运行时的段落
> 写法取自耦合等级）。

剧情页用分段切换三个标签，三者互斥替代同一块内容区：

- **章节与触发器**：合并列表，章节行加粗着色、其下缩进行是本章触发器；增删改序都
  在这里，逐项字段细节见 [dungeon/script.md](dungeon/script.md) §2（章节）与 §4（触发器）；
- **章节编排** / **触发器依赖**：两张只读画布（§3），共用
  `ui/scenario/graph_view.py::ScenarioGraphPanel`，靠 `set_data(view=...)` 决定
  画哪张。

## 2. 字段声明与表单

**`dungeon/schema.py` 是字段声明的单一真相源**：`FieldSpec(key, kind, label,
default, required, choices, note)` 声明九种 kind（`str / int / float / bool / dict /
list / enum / color / text`），按层分组为顶层 24 项的 `SCENARIO_FIELDS` 与
`CHAPTER_FIELDS`、`TRIGGER_FIELDS`、`VOICE_FIELDS` / `BGM_FIELDS` /
`BACKGROUND_FIELDS` / `VOICE_FX_SLOT_FIELDS` / `SENSITIVITY_FIELDS` /
`FIXED_TEXT_FIELDS`。谁在消费它：

- 校验器按声明报未知键 / 废弃键 / 取值非法（§4 诊断的来源之一）；
- 空方案模板由声明直接生成；
- 守卫比对声明与归一化结果一致（§8）。

编辑器各页表单**目前是手写的**（按页签组织控件，字段清单见 §1 的表），尚未从
schema 通用渲染——「编辑器表单按字段声明渲染」是声明里挂着的后续项。

**保存路径**：各页把改动合并写回 `config.json` 的对应键（通用页写准入 / 提示 /
转移矩阵等；剧情页只写 `evolution_attrs / chapters / triggers`；角色页与组件页
防抖写各自字段），统一经方案仓库落盘（§8）——每次保存先校验，诊断记入
`repo.last_diagnostics` 但**不阻断写入**，随后原子写盘。

## 3. 编排画布（只读）

两张图共用一套自绘 tkinter 画布（`ui/scenario/graph_view.py::GraphCanvas`），
**只读**：不编辑、不写盘、不承担校验展示。节点数据来自唯一建图入口
`dungeon/scenario_graph.py::build_graph(config)`（宽容缺字段）；节点 / 边 / 泳道的
数据模型与图分析算法（可达性、强连通分量、可触发判定）见
`docs/Dungeon/scenario_graph.md` §2。

**触发器依赖（泳道图）**：一条泳道一个章节（按配置顺序），悬空引用的章节有
「（章节不存在）」占位泳道，末尾是「任意章节 / 无章节」汇流泳道。泳道内按依赖
分层（列 = 依赖深度，行 = 同层逐个）：章节抬头第 0 列，无前置的触发器第 1 列，
下游依次向右；深度用迭代到不动点求解，死锁环顶到上限后统一落第 1 列、连线同列
绕行。归属边不画箭头——排在本章节泳道里即表达；goto 与 overflow 不画跨泳道
箭头，只在节点右上角画 ↗ 角标（章节跳转实线、超限跳转虚线），跨章节箭头只保留
触发器 → 触发器的前置引用。

**章节编排（流程图）**：把 goto 边折算成「触发器所在泳道头 → 目标章节」的章节层
投影，从根按跳数分列，Band 标签为「起点 / 第 N 跳 / 不可达（从起始章节走不到）」。

> 配色随主题：token 在 `assets/theme/{Slate,Classic}.json` 的 `vars`（前缀组
> `GRAPH_EDGE_* / GRAPH_NODE_* / GRAPH_LANE_* / GRAPH_CANVAS_* / ACTION_FILL_* /
> DEPENDENCY_*`）；章节节点用章节自身 `color`，深色模式整体提亮 35%。

<details>
<summary>编排图交互与导出（看图排查时展开）</summary>

拖拽平移、滚轮缩放（0.45–2.6，保持视口中心）；点选节点高亮入出边，左侧详情面板
列出直接依赖、同位置竞争组员（含「恒真且配置顺序靠后、永远轮不到」的成员）与
节点诊断；图层开关可关 `前置 / 章节跳转 / 超限 / 条件引用` 四类边（进入边恒画）；
「只看有问题的」只留带诊断的节点与其间边（同位竞争不是诊断，不受开关影响）；
顶部一行结构概况（章节数 / 触发器数 / 图校验条数 / 同位竞争组数）；「帮助」对话框
含图例与画图示意；「导出报告」写 txt（泳道清单、关系边、诊断、同位竞争）。

</details>

诊断点击定位：画布 `focus_path(path)` 把 `triggers[i] / chapters[i]` 形式的字段
路径映射到节点并滚动定位——这是 §4 校验条跳转的终点。

## 4. 诊断与顶栏校验条

诊断有两个来源：字段级校验 `validate_scenario_config`（逐字段规则表见
[dungeon/script.md](dungeon/script.md) §9.1）与结构级图校验 `lint_graph`（五条图
规则，同前引），统一成 `Diagnostic(level, path, message)` 三级。

**校验条**是 28px 常驻条：左侧「● N 错误」「▲ N 警告」两枚可点 pill，中间一行
摘要（无错无警时显示「未发现问题。」或 N 条提示），右侧各页签 chip（仅该页签有
error / warning 时显示计数，error 红色）；点击展开 190px 抽屉逐条列出（级别 ·
路径：消息），行尾「{页签} ▸」链接。

| 点击 | 行为 |
|---|---|
| pill / 摘要 / ▾ | 展开 / 收起抽屉 |
| 页签 chip | 只切页签 |
| 诊断行 / 链接 | 切到归属页签并定位：`chapters / triggers` 根键切到对应编排图并定位到节点；`components*` 根键刷新组件列表；定位不了只切页不打断 |

**刷新时机**：加载方案、通用页 / 剧情页保存、角色页与组件页防抖落盘、挑战包导入
之后——数据源统一是方案仓库最近一次校验的诊断。进入副本前还有一道启动门：窗口
再校验一次，error 级阻止进入（§8）。

<details>
<summary>诊断按什么归到哪个页签（诊断归错页签或调分组口径时展开查）</summary>

只按 `path` 的**根键**归类：`ui/scenario/diagnostics.py::root_key` 在第一个 `[`
`.` `@` 处截断（图校验的虚路径 `chapters@…` 也归 `chapters`），再查 `_ROOT_TABS`：
准入 / 提示 / 转移矩阵等根键归「通用」，`protagonist_* / cast / voice /
evolution_attrs` 归「角色」，`components* / text_component` 归「组件」，
`chapters / triggers` 归「剧情」，**未知根键回落「通用」**。`summarize` 给出排序
后的清单（error 在前）、分级计数、页签 × 级别计数与门面摘要（最严重一条）。分组
是纯函数、无界面依赖，守卫直接盯这条口径。

</details>

## 5. 组件管理页

组件页管理方案配置的三个键：`text_component`（文本主组件三选一
`text / text_card / text_nvl`）、`components`（其余组件 id 列表）、
`components_params`（`{组件id: {参数: 值}}`）。加载时把 `components` 里的文本
家族成员过滤掉（旧写法残留，落盘迁移见 §8）。

- 顶部「文本组件（三选一）」分段按钮，选中项的参数表单常驻无开关；
- 下方每个可用组件一张卡：启用开关 + 展示名 + 说明；启用才展开参数表单，禁用只
  收起、参数不丢。展示名 / 说明 / 参数声明都以组件类本身为单一真相源，页面经
  `dungeon/window/component_registry.py::available_component_descriptions()` 读取；
- 参数行按声明的类型分派控件：`color`（取色器 + hex 输入，6 位输入沿用组件默认
  alpha）、`bool`（开关）、`int`（输入框，保存前按声明的 min/max 夹取）、`text`
  （输入框）；
- **700ms 防抖自动保存**，无保存按钮；保存时按描述顺序归一化 `components`、已
  禁用组件的参数保留。外部重新加载用快照比对决定是否重建卡片，避免打断挂起的
  防抖。

组件在运行时的契约（钩子 / 参数夹取 / 加载链 / slot 代管区）见
[dungeon/components.md](dungeon/components.md)。

## 6. 固定文本编辑器

章节字段 `fixed_text` 指向方案目录下的 `.txt` / `.md`：该章不走 AI 生成，按逻辑
段落逐段推进，正文**不进 `config.json`**。段落格式（空行分段、段落首行指令
`[段落类型 方向]`、`==高亮==`）与解析（`dungeon/script_text.py::parse_script`）见
[dungeon/script.md](dungeon/script.md) §2.5。

编辑入口链在章节编辑对话框：「选择…」导入（拷入 `<方案>/texts/`，非 txt 后缀补
`.txt`，无路径时先给不冲突的默认名）→「编辑」打开
`ui/scenario/text_editor_dlg.py::ScriptTextDialog`——正文多行编辑 + 实时解析预览
（共 N 个逻辑段落、前 12 段的指令描述、前 6 条警告）。读文件按 utf-8 → gbk 容错，
与运行时同一口径；存盘前确认 fixed_text 可读，否则当场拦。对话框上方实时显示
段落 / 演化段数 / 首条警告。

## 7. 素材导入

统一模式「选文件 →（裁剪）→ 存入方案目录 → 返回相对路径（正斜杠）」，调用方是
章节编辑对话框：

| 素材 | 目标目录 | 处理 |
|---|---|---|
| 背景图 | `<方案>/images/` | `(.png .jpg .jpeg .gif .bmp .webp)`，弹 16:9 裁剪对话框，按扩展名转格式保存 |
| 背景音乐 | `<方案>/audio/` | `(.mp3 .wav .ogg .flac .m4a .wma)`，直拷不裁剪 |
| 结局图标 | `<方案>/endings/` | 仅 PNG，文件名 `{时间戳}_{净化名≤40字符}.png` |
| 固定文本 | `<方案>/texts/` | `(.txt .md)`，直拷 |

同名覆盖一律先确认。相对路径的解析基准是方案目录（§8；挑战包解包时由宿主顶替）。
触发器的效果覆盖只选滤镜枚举、不新增素材。

包外分发时素材随包走：挑战包打包只收 `("texts", "images", "audio", "endings")`
白名单内、方案目录内的相对路径（绝对路径与 `..` 越界一律不收），zip 内前缀
`assets/`，解包时做越界过滤（`services/challenges/pack.py::collect_asset_paths /
pack_assets / extract_pack_assets`）。挑战包整体流程见 [challenges.md](challenges.md)。

## 8. 内部实现：方案读写与容错

- **布局**：`data/packs/scenarios/<方案id>/config.json` + 素材子目录
  `images/ audio/ texts/ endings/`（容器与命名规则见 [resources.md](resources.md)）。
- **双根**：世界包声明拥有 `scenarios` 时读根指向包目录（只读），否则与写根相同；
  写根恒为自由根 `data/packs/scenarios`。列方案同时看两根，新建 / 保存 / 删除只写
  写根。世界包机制见 [world_packs/author.md](world_packs/author.md)。
- **读**：主文件损坏回退 `.bak`，再过迁移补齐 / 归一化字段并迁走旧键
  （`custom_attrs → evolution_attrs`、触发器 `id → name`、
  `precondition_ids → precondition_names`、`action → action_type`、文本组件从
  `components` 家族提升、`speaker_notation` 按旧耦合等级补默认）。
- **写**：`persistence/scenario_repo.py::ScenarioRepo.save_config` 先校验（诊断不
  阻断）再原子写 + `.bak`；显示名改名只写信封 `title`，不动目录与 id。
- **挑战包导入**：编辑器顶栏可从 `.chal` 解密取方案——已存在则覆盖写、否则新建。
- **启动门**：进入副本前 `dungeon/window/base.py::_load_session_config` 再校验
  一次，error 级阻止进入。
- **离线批量校验**：`python scripts/scenario_validate.py` 对全部方案跑一遍校验，
  有 error 时退出码 1，适合提交前或打包前批量过一遍。

<details>
<summary>守卫怎么盯住编辑器这条链（改 schema 或诊断口径前展开看）</summary>

离线守卫（CI 门禁）：`python tests/check_scenario_schema.py` 比对字段声明与
normalize 归一化结果一致；`tests/check_scenario_graph.py` 无 GUI 覆盖建图、两类
可达性口径、强连通分量与图校验；`tests/check_scenario_editor_diagnostics.py`
守住诊断 → 页签分组、摘要门面与「只剩提示不报警」的口径。

</details>

## 9. 拓展用法

本节收录界面上没有说明、但程序实际支持的用法：

- **在编辑器外直接手改 `config.json`**：方案目录在用户数据区，下次打开照常读入
  （经迁移规则归一），写错的地方以校验条诊断呈现——编辑与保存不被诊断阻断，但
  error 级诊断会在进入副本时被启动门拦下（§8）。

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
- **chat/**：[README](chat/README.md)（话题与好感 / 紧张度）·
  [lens](chat/lens.md)（信息视角细节）
- **behaviors/**：[README](behaviors/README.md)（玩家向）·
  [dev-guide](behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](behaviors/hooks-logic.md) / [report](behaviors/hooks-report.md) /
  [character](behaviors/hooks-character.md) / [chat](behaviors/hooks-chat.md)）·
  [example-imperial](behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](world_packs/author.md)（制作与清单）

**单篇**

[地址系统](address_system.md) · [报告生成](report_selection.md) ·
[角色演化](character_evolution.md) · [资源与包体系](resources.md) ·
[挑战包](challenges.md) ·
[剧本编辑器](scenario_editor.md)（本页） · [界面双模式与外观](ui_modes.md) ·
[角色的长期行为](character_time.md) · [身材剪影](body_preview.md) ·
[更新检查](update_check.md)

</details>
