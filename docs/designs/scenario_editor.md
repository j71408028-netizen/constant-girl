# 剧本编辑器

> **这一篇回答什么问题**：编辑器分哪些页与标签、字段声明和校验从哪来、剧情页两张
> 编排图怎么读、顶栏校验条怎么分组与跳转、组件 / 固定文本 / 素材怎么进出方案目录。
> 方案字段的数据模型与逐字段校验规则在 [dungeon/script.md](dungeon/script.md)；
> 运行时组件契约在 [dungeon/components.md](dungeon/components.md)。

## 1. 页面结构：四页签 + 剧情页三标签

入口在主窗口导航栏「剧本编辑」（`app/window_manager.py::WindowManager.create_scenario_tab`）。
世界包清单声明拥有 `scenarios` 时整页锁定为提示条（`app/window_manager.py::_locked_pages`）。

顶栏（`ui/scenario/sc_frame.py::ScenarioEditor._build_ui`）自上而下两层：

1. **方案胶囊**：显示名下拉 + `＋ / ✎ / 🗑`（新建 / 重命名 / 删除）。新建走
   `ResourceNameDialog`（id 自动派生，规则见 [resources.md](resources.md) §1）；
   重命名只写信封 `title`；默认方案（`dungeon/terms.py::DEFAULT_SCENARIO_ID`）不可删。
2. **页签轨**：`通用 / 角色 / 剧情 / 组件` 四个互斥页签（常量在
   `ui/scenario/diagnostics.py::TABS`），第二层右侧是常驻校验条（§4）。

| 页签 | 内容 | 编辑方式 |
|---|---|---|
| 通用 | 耦合等级、说话人写法、进入准入（入口地址 / 距离上限 / 身高区间）、进入消耗、初始坐标、初始提示、五类段落分类提示与步进、转移矩阵 | 显式「保存此页面」 |
| 角色 | 她的卡片、主角称呼与身份背景、人物表（重要角色 / 群像）、方案级对话语音、演化量视图 | 防抖自动保存 |
| 剧情 | 章节与触发器列表 + 两张只读编排图（§3） | 对话框编辑、列表保存 |
| 组件 | 文本主组件三选一 + 组件卡片（§5） | 防抖自动保存 |

剧情页用分段切换三个标签，三者互斥替代同一块内容区
（`sc_frame.py::STORY_VIEWS`，`_on_story_view_switch` → `_show_story_view`）：

- **章节与触发器**：合并列表（`chapter_trigger_mgr.py::ChapterTriggerManager`），
  章节行加粗着色、其下缩进行是本章触发器；增删改序都在这里，逐项细节见
  `docs/designs/dungeon/script.md` §8；
- **章节编排** / **触发器依赖**：两张只读画布（§3），共用
  `graph_view.py::ScenarioGraphPanel`，靠 `set_data(view=...)` 决定画哪张。

## 2. 字段声明与表单

**`dungeon/schema.py` 是字段声明的单一真相源**：`FieldSpec(key, kind, label, default,
required, choices, note)` 声明九种 kind（`str / int / float / bool / dict / list /
enum / color / text`），按层分组为 `SCENARIO_FIELDS`（顶层 24 项）、`CHAPTER_FIELDS`、
`TRIGGER_FIELDS`、`VOICE_FIELDS` / `BGM_FIELDS` / `BACKGROUND_FIELDS` /
`VOICE_FX_SLOT_FIELDS` / `SENSITIVITY_FIELDS` / `FIXED_TEXT_FIELDS`。当前消费方：

- 校验器 `dungeon/validate.py`（按声明报未知键 / 废弃键 / 取值非法）；
- 空方案模板 `schema.empty_scenario_config()`（`ScenarioRepo._empty_config` 用）；
- 守卫 `tests/check_scenario_schema.py`（比对 schema 与 normalize 归一化结果一致）。

编辑器各页表单**目前是手写的**（按页签组织控件，字段清单见上文各页），尚未从
schema 通用渲染；`FieldSpec` 的 docstring 把「编辑器表单按字段声明渲染」列为后续项。

**保存路径**：各页把改动合并写回 `config.json` 的对应键（通用页 `_save_prompts` 写
准入 / 提示 / 转移矩阵等；剧情页 `_save_evolution_triggers` 只写 `evolution_attrs /
chapters / triggers`；角色页与组件页防抖写各自字段），统一落
`persistence/scenario_repo.py::ScenarioRepo.save_config`——每次保存先跑
`validate_scenario_config`，诊断记入 `repo.last_diagnostics`（**不阻断写入**），
再原子写盘（覆盖前留 `.bak`）。

## 3. 编排画布（只读）

两张图共用一套自绘 `tkinter.Canvas`（`ui/scenario/graph_view.py::GraphCanvas`），
**只读**：不编辑、不写盘、不承担校验展示；节点数据来自
`dungeon/scenario_graph.py::build_graph(config)`（宽容缺字段的唯一建图入口），
节点 / 边 / 泳道的数据模型与图分析算法（可达性、强连通分量、可触发判定）见
`docs/Dungeon/scenario_graph.md` §2。

**触发器依赖（泳道图）**：一条泳道一个章节（按配置顺序），悬空引用的章节有
「（章节不存在）」占位泳道，末尾是「任意章节 / 无章节」汇流泳道。泳道内按依赖
分层（列 = 依赖深度，行 = 同层逐个）：章节抬头第 0 列，无前置的触发器第 1 列，
下游依次向右；深度用迭代到不动点求解，死锁环顶到上限后统一落第 1 列、连线同列
绕行。归属边不画箭头——排在本章节泳道里即表达；goto 与 overflow 不画跨泳道箭头，
只在节点右上角画 ↗ 角标（章节跳转实线、超限跳转虚线），跨章节箭头只保留
触发器 → 触发器的前置引用。

**章节编排（流程图）**：把 goto 边折算成「触发器所在泳道头 → 目标章节」的章节层
投影（`ScenarioGraph.chapter_view_edges`），从根 BFS 分列，Band 标签为
「起点 / 第 N 跳 / 不可达（从起始章节走不到）」。

交互（`ui/scenario/graph_view.py`）：拖拽平移、滚轮缩放（0.45–2.6，保持视口中心）、
点选节点高亮入出边并在左侧详情面板列出直接依赖、同位置竞争组员（含「恒真且配置
顺序靠后、永远轮不到」的成员）与节点诊断；图层开关可关 `前置 / 章节跳转 / 超限 / 
条件引用` 四类边（进入边恒画）；「只看有问题的」只留带诊断的节点与其间边（同位
竞争不是诊断，不受开关影响）；顶部一行结构概况（章节数 / 触发器数 / 图校验条数 /
同位竞争组数）；「帮助」对话框含图例与画图示意，「导出报告」写 txt（泳道清单、
关系边、诊断、同位竞争）。

配色 token 在 `assets/theme/{Slate,Classic}.json` 的 `vars`（前缀组
`GRAPH_EDGE_* / GRAPH_NODE_* / GRAPH_LANE_* / GRAPH_CANVAS_* / ACTION_FILL_* /
DEPENDENCY_*`）；章节节点用章节自身 `color`，深色模式经
`dungeon/audio/chapters.py::shade_for_mode` 提亮 35%。

诊断点击定位：画布 `focus_path(path)` 用 `triggers[i]` / `chapters[i]` 形式的字段
路径映射到节点并滚动定位（§4 的跳转终点）。

## 4. 诊断与顶栏校验条

诊断由 `validate_scenario_config`（字段级，规则表见
`docs/designs/dungeon/script.md` §9.1）加 `lint_graph(build_graph(config))`
（结构级五条图规则）产出，统一为 `Diagnostic(level, path, message)` 三级。

**分组口径**（`ui/scenario/diagnostics.py`，纯函数、无界面依赖）：只按 `path` 的
**根键**归类——`root_key(path)` 在第一个 `[` `.` `@` 处截断（图校验的虚路径
`chapters@…` 也归 `chapters`），再查 `_ROOT_TABS`：准入 / 提示 / 转移矩阵等根键
归「通用」，`protagonist_* / cast / voice / evolution_attrs` 归「角色」，
`components* / text_component` 归「组件」，`chapters / triggers` 归「剧情」，
**未知根键回落「通用」**。`summarize(diagnostics)` 给出排序后的清单（error 在前）、
分级计数、页签 × 级别计数与 `headline()`（最严重一条）。

**校验条**（`sc_frame.py::ScenarioEditor._build_diag_bar`）：28px 常驻条——左侧
「● N 错误」「▲ N 警告」两枚可点 pill，中间一行摘要（无错无警时显示
「未发现问题。」或 N 条提示），右侧各页签 chip（仅该页签有 error / warning 时
显示计数，error 红色）；点击展开 190px 抽屉逐条列出（级别 · 路径：消息），行尾
「{页签} ▸」链接。

| 点击 | 行为 |
|---|---|
| pill / 摘要 / ▾ | 展开 / 收起抽屉 |
| 页签 chip | 只切页签 |
| 诊断行 / 链接 | 切到归属页签并定位：`chapters / triggers` 根键切到对应编排图并 `focus_path()`；`components*` 根键刷新组件列表；定位不了只切页不打断 |

**刷新时机**：加载方案、通用页 / 剧情页保存、角色页与组件页防抖落盘、挑战包导入
之后——数据源统一是 `repo.last_diagnostics`。另有启动门：进入副本前
`dungeon/window/base.py::_load_session_config` 再校验一次，error 级阻止进入。

## 5. 组件管理页

`ui/scenario/component_mgr.py::ComponentManager` 管理方案配置的三个键：
`text_component`（文本主组件三选一 `text / text_card / text_nvl`）、
`components`（其余组件 id 列表）、`components_params`（`{组件id: {参数: 值}}`）。
加载时把 `components` 里的文本家族成员过滤掉（旧写法残留，落盘迁移见
`persistence/scenario_repo.py::ScenarioRepo._migrate`）。

- 顶部「文本组件（三选一）」分段按钮，选中项的参数表单常驻无开关；
- 下方每个可用组件一张卡：启用开关 + 展示名 + 说明；启用才展开参数表单，
  禁用只收起、参数不丢。元数据来自
  `dungeon/window/component_registry.py::available_component_descriptions()`
  （label / description / param_specs 的单一真相源是组件类本身）；
- 参数行按 `param_specs` 的 type 分派控件：`color`（取色器 + hex 输入，6 位输入
  沿用组件默认 alpha）、`bool`（Switch）、`int`（Entry，保存前按 spec 的 min/max
  夹取）、`text`（Entry）；
- **700ms 防抖自动保存**（`_SAVE_DEBOUNCE_MS`），无保存按钮；保存时按描述顺序
  归一化 `components`、已禁用组件的参数保留。外部重新加载用快照比对决定是否
  重建卡片，避免打断挂起的防抖。

组件在运行时的契约（钩子 / 参数夹取 / 加载链 / slot 代管区）见
[dungeon/components.md](dungeon/components.md)。

## 6. 固定文本编辑器

章节字段 `fixed_text`（`schema.FIXED_TEXT_FIELDS`，仅 `path`）指向方案目录下的
`.txt` / `.md`：该章不走 AI 生成，按逻辑段落逐段推进，正文**不进 config.json**。
段落格式（空行分段、段落首行指令 `[段落类型 方向]`、`==高亮==`）与解析
（`dungeon/script_text.py::parse_script`）见 `docs/designs/dungeon/script.md` §2.5。

编辑入口链在章节编辑对话框（`chapter_dlg.py::ChapterEditDialog`）：
「选择…」导入（`asset_import.import_script_text` 拷入 `<方案>/texts/`，非 txt 后缀
补 `.txt`）→「编辑」打开 `text_editor_dlg.py::ScriptTextDialog`——正文多行编辑 +
实时解析预览（共 N 个逻辑段落、前 12 段的指令描述、前 6 条警告）；无路径时先给
不冲突默认名 `texts/<章节名>.txt`（`asset_import.suggest_script_path`）。读文件
按 utf-8 → gbk 容错，与运行时 `load_script_file` 同口径；存盘前确认 fixed_text
可读，否则当场拦。对话框上方实时显示段落 / 演化段数 / 首条警告。

## 7. 素材导入

统一模式「选文件 →（裁剪）→ 存入方案目录 → 返回相对路径（正斜杠）」
（`ui/scenario/asset_import.py`），调用方是章节编辑对话框：

| 素材 | 目标目录 | 处理 |
|---|---|---|
| 背景图 | `<方案>/images/` | `(.png .jpg .jpeg .gif .bmp .webp)`，弹 16:9 裁剪对话框，按扩展名转格式保存 |
| 背景音乐 | `<方案>/audio/` | `(.mp3 .wav .ogg .flac .m4a .wma)`，直拷不裁剪 |
| 结局图标 | `<方案>/endings/` | 仅 PNG，文件名 `{时间戳}_{净化名≤40字符}.png` |
| 固定文本 | `<方案>/texts/` | `(.txt .md)`，直拷 |

同名覆盖一律先确认。相对路径的解析基准是 `ScenarioRepo.asset_dir()`（§8，
挑战包解包时由宿主顶替）。触发器的效果覆盖只选滤镜枚举、不新增素材。

包外分发时素材随包走：挑战包打包只收 `("texts", "images", "audio", "endings")`
白名单内、方案目录内的相对路径（绝对路径与 `..` 越界一律不收），zip 内前缀
`assets/`，解包时做越界过滤（`services/challenges/pack.py::collect_asset_paths /
pack_assets / extract_pack_assets`）。挑战包整体流程见 [challenges.md](challenges.md)。

## 8. 方案读写（`persistence/scenario_repo.py`）

- **布局**：`data/packs/scenarios/<方案id>/config.json` + 素材子目录
  `images/ audio/ texts/ endings/`（容器与命名规则见 [resources.md](resources.md)）。
- **双根**：世界包声明拥有 `scenarios` 时 `read_root` 指向包目录（只读），否则与
  写根相同；写根恒为自由根 `data/packs/scenarios`——`list_all / scenario_dir` 同时
  看两根，`create / save_config / delete` 只写写根。世界包机制见
  [world_packs.md](world_packs.md)。
- **读**：`load_config` 主文件损坏回退 `.bak`，再过 `_migrate` 补齐 / 归一化字段并
  迁移旧键（`custom_attrs → evolution_attrs`、触发器 `id → name`、
  `precondition_ids → precondition_names`、`action → action_type`、文本组件从
  `components` 家族提升、`speaker_notation` 按旧耦合等级补默认）。
- **写**：`save_config` 先校验（诊断不阻断）再原子写 + `.bak`；显示名改名只写
  信封 `title`（`set_title`），不动目录与 id。
- **挑战包导入**：编辑器顶栏可从 `.chal` 解密取方案——已存在则覆盖写、否则新建
  （`sc_frame.py::ScenarioEditor._on_scenario_challenge_pack_select`）。
- **离线批量校验**：`scripts/scenario_validate.py` 对全部方案跑校验，error 退出码 1。

## 9. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 编辑器主体（顶栏 / 页签轨 / 通用页 / 校验条） | `ui/scenario/sc_frame.py::ScenarioEditor` |
| 页签与剧情页标签常量 | `ui/scenario/diagnostics.py::TABS`、`ui/scenario/sc_frame.py::STORY_VIEWS`、`ui/scenario/graph_view.py::VIEW_CHAPTERS / VIEW_TRIGGERS` |
| 新建 / 重命名 / 删除 / 切换方案 | `sc_frame.py::ScenarioEditor._new_scenario / _rename_scenario / _delete_scenario / _on_scenario_select` |
| 章节与触发器列表 | `ui/scenario/chapter_trigger_mgr.py::ChapterTriggerManager` |
| 章节 / 触发器编辑对话框 | `ui/scenario/chapter_dlg.py::ChapterEditDialog`、`ui/scenario/trigger_dlg.py::TriggerEditDialog` |
| 角色页（主角 / 人物表 / 语音 / 演化量） | `ui/scenario/character_page.py::CharacterPage`、`ui/scenario/evolution_attributes.py::EvolutionAtrrManager` |
| 字段声明（单一真相源） | `dungeon/schema.py::FieldSpec / SCENARIO_FIELDS / CHAPTER_FIELDS / TRIGGER_FIELDS / empty_scenario_config` |
| 编排图面板与画布 | `ui/scenario/graph_view.py::ScenarioGraphPanel / GraphCanvas`（`_lane_layout / _flow_layout / focus_path / _show_detail / _export_report`） |
| 图模型与建图入口 | `dungeon/scenario_graph.py::build_graph / ScenarioGraph`（`lanes / chapter_view_edges / same_position_groups`） |
| 图校验五规则 | `dungeon/graph_lint.py::lint_graph`（规则表见 [dungeon/script.md](dungeon/script.md) §9.1） |
| 诊断 → 页签分组 | `ui/scenario/diagnostics.py::root_key / tab_of / _ROOT_TABS / summarize` |
| 校验条渲染 / 抽屉 / 跳转 | `sc_frame.py::ScenarioEditor._build_diag_bar / _render_diag_bar / _fill_diag_panel / _jump_to_diagnostic / _locate_path / _notify_validation` |
| 字段级校验器 | `dungeon/validate.py::validate_scenario_config / Diagnostic / has_errors` |
| 组件管理页 | `ui/scenario/component_mgr.py::ComponentManager`（`collect_params / _build_param_rows / _flush_save / refresh_list`） |
| 组件元数据出口 | `dungeon/window/component_registry.py::available_component_descriptions` |
| 固定文本编辑对话框 / 解析 | `ui/scenario/text_editor_dlg.py::ScriptTextDialog`、`dungeon/script_text.py::parse_script / load_script_file` |
| 素材导入 | `ui/scenario/asset_import.py::import_background_image / import_bgm_audio / import_ending_icon / import_script_text / suggest_script_path` |
| 挑战包素材收集 | `services/challenges/pack.py::collect_asset_paths / pack_assets / extract_pack_assets` |
| 方案仓库（双根 / 迁移 / 原子写） | `persistence/scenario_repo.py::ScenarioRepo`（`read_root / write_root / load_config / save_config / _migrate / set_title / delete`） |
| 启动门（error 阻止进入） | `dungeon/window/base.py::_load_session_config` |
| 入口 / 页面锁定 | `app/window_manager.py::WindowManager.create_scenario_tab / _locked_pages` |
| 离线批量校验 | `scripts/scenario_validate.py` |
| 守卫 | `tests/check_scenario_schema.py / check_scenario_graph.py / check_scenario_editor_diagnostics.py` |
