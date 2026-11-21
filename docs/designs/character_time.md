# 角色的长期行为

> **这一篇回答什么问题**：你关掉程序的那段时间里她做了什么（下次载入时一次性结清：行动点、坐标、伤亡）、她的作息节律怎么形成、近况新闻什么时候弹，以及两种导出各自能带走什么。
> - **普通玩家**：顺着 **§1 → §3** 看就能搞懂「关掉游戏的日子里她做了什么」；想分享或搬运角色看 **§4 → §5**；顺手看看 **§7** 里的隐藏玩法。
> - **想折腾机制或改代码的开发者**：重点看 **§1～§2** 的规则与 **§6** 的实现说明。
>
> 相关页面：演化公式总览 [character_evolution.md](character_evolution.md) · 空间档案与区域 [report_selection.md](report_selection.md) · 新闻数据源 [resources.md](resources.md) · 身材剪影 [body_preview.md](body_preview.md)。

> **名词对照说明**：游戏里关掉再回来重新算账的过程，在代码里叫 `offline`（离线），正文里通常说「恢复结算」或「离开这段时间」；界面上你看到的第一句话依然是「离线 {时长}」。

## 1. 恢复结算：载入那一刻结一次账

**什么时候算账**：只有当你**点开/载入这个角色**的那一刻才会算一次——不管从哪个界面进都一样，先算完这段时间发生的事，再处理后续变化和保存。没载入的角色不会提前算账，哪怕放好几天也等载入时再一起算。

重新载入时，会一次性结清三件事：

1. **行动点回血**：按你离开的分钟数慢慢涨回来，最高补到 **100**（自然回复的上限）。
2. **坐标往回走**：她的介入度 / 破坏性会向自己的**性格初始倾向**（`init_intrusion` / `init_destruction`）靠拢，而不是停在正中间。离开越久靠得越多，但每次按比例走、不会冲过头，最后限制在 **0.5～4.5** 之间（细则见 [character_evolution.md](character_evolution.md) §3 的闲置回落）。如果没有设定性格，坐标就不会自己回落。
3. **步进与伤亡变化**：你不在的时候她也不是完全静止，结算时会按离开的时间长短分两段算：
   - **最近 72 小时：每 2 小时记一小段**（在界面的离线明细里能看到每一段的记录）。每一小段有多活跃，取决于她的个性强度、作息规律（§2），再加上刚关游戏那阵子还没完全安静下来的「余温」（随时间很快退去），最后乘上她从空间档案里积累的环境影响（范围在 `0.1～1.5`，见 [report_selection.md](report_selection.md)）。伤亡则会结合她的身材和步进一起算。
   - **超过 72 小时的更早时间：按天打包算一大段**（没有逐 2 小时的明细），作息按当天的平均水平来算。

算完账之后，界面的离线明细会换成**这一次**的数据，累计伤亡会加上新产生的部分；只要有变化，就会记一条恢复记录。界面首段「离线 {时长}」在离开满 90 分钟后会按小时显示，依次列出时长、恢复的行动点、步进和新增伤亡。

> **在线时是另一套节奏**：只要角色开着，角色面板每 60 秒会自动回一点行动点，每分钟坐标也会小幅回落一点（详见 [character_evolution.md](character_evolution.md) §3 的闲置回落、§5 的行动点）。刚载入算完离线账后，还会紧接着判定负向演化（行动点在 50 及以上时会跳过，见 §3 的负向演化）。

<details>
<summary>参数默认值与计算公式（想微调手感或排查数值异常时展开）</summary>

这些参数来自角色创建时带上的「出身烙印」（`core/models.py::ModelTuning`），伴随角色终身，切换世界包不会改动已有角色；生效优先级为：**单次指定 > 角色烙印 > 系统默认**。

| 参数 | 默认值 | 作用说明 |
|---|---|---|
| `step_per_hour` | 0.01 | 基础步进率（步/小时） |
| `exit_amp` / `exit_tau` | 0.05 / 0.9h | 退出后残留活跃度的初始幅度与衰减时间常数 |
| `recovery_points_per_minute` | 0.5 | 行动点恢复速度（点/分钟） |
| `recovery_decay_per_minute` | 0.01 | 坐标回落速度（深度/分钟） |
| `noise_scale` | 0.1 | 环境随机波动系数 |
| `old_step_divisor` | π | 超过 72 小时汇总段的步进除数 |
| `rhythm_swing` | 1.0 | 作息波动放大倍数（限制在 `0～3`） |

- **最近 72 小时（每 2 小时一格，按偶数整点对齐）**：瞬时步进率 ≈ 活动基线 × `step_per_hour` × 作息系数 + 退出残留。其中活动基线由个性强度归一化（默认 0.5）；作息系数为 `1.0 + swing × (rhythm.factor_at(时段中点) - 1.0)`；退出残留为 `基线 × exit_amp × exp(-离开小时数 / exit_tau)`。每段伤亡按 `0.01 × 身高² × 步进 × 破坏性 × 环境因子 × log10(身高)` 计算（`core/logic/simulation.py::compute_casualty`），环境因子则结合空间档案与随机波动生成（`services/character/spatial.py::EnvironmentProfile`）。
- **超过 72 小时的部分**：按天汇总，步进约为 `基线 × step_per_hour × 24 / π × 当天作息均值 × 天数`，伤亡使用同一套计算公式。

</details>

## 2. 作息节律：从平时的经历里慢慢学出来

她的作息不是提前写死的配置，而是**从她平时的演化记录里现学出来的**：只要某条演化记录步进大于 0 且时间有效，就会算作一次活动样本，按「星期几 × 一天 12 个 2 小时时段」整理成一张 `7×12` 的作息表（同样按偶数整点对齐）。这套作息表不会单独存成新文件，每次用到时直接从演化记录里现场统计（`services/character/rhythm.py`）。

- **样本少的时候会往稳妥处靠**：某个时段记录还很少时，会向整体平均值收缩（权重为 `6 / (6 + 样本数)`），再乘上**昼夜基础曲线**（白天偏高、傍晚回落、凌晨保底 `0.6`），最后卡在 `0.15～2.5` 之间——既不会变成完全不动，也不会爆出离谱数值；完全没有记录时，就直接使用昼夜基础曲线。
- **你在游戏里会在三个地方感受到**：
  1. 载入时的恢复结算（§1），决定不同时段有多活跃；
  2. 角色档案简介里的「作息观察」段落（样本不到 24 条时，语气会更保守）；
  3. 聊天时的实时状态提示（样本不到 6 条时不提示；活跃度高时提示偏活跃，低时提示在歇息）。
  *注：作息只影响表现和活跃度，不会卡任何准入条件。*
- 程序里已经写好了未来 72 小时的作息预测能力（按星期循环推算，没有衰减），目前主界面主要用的是当前时刻的查表和作息网格。

## 3. 近况新闻：载入后可能弹出的早报

新闻内容来自取材表组里的 `news.csv`（列定义与回落顺序见 [resources.md](resources.md) §7；读取时会去掉空文本行）。

**什么时候会弹**（载入角色后检查；专业版会弹「早报」窗口，挂件版不会弹）：
- 早上 **9 点之前**不弹；
- **今天已经弹过**就不弹；
- 如果距离上次看新闻已经过了 **7 天或更久**，会改成弹「杂物新闻」（时间算作本次载入前她的更新时间）；
- 其余情况按你的设置概率 `info_update_rate` 掷骰子（可选 `0.25 / 0.5 / 0.75 / 1.0`，默认 `0.5`），没抽中也会走杂物新闻。

**挑哪一条来弹**（每次最多 1 条）：先按她当前的身高档位筛，再考虑生日 / 节日和介入度 / 破坏性档位；尽量避开跟上次一模一样的正文，实在筛不出来就用杂物新闻兜底。选中后会替换名字 / 昵称，并从 `substitute` 列随机挑词补进模板。

<details>
<summary>新闻条目的完整筛选与替换规则（想查某条为什么没弹或调 news.csv 时展开）</summary>

- `size_category` 必须**严格匹配**她当前的身高档位（`core/logic/sizing.py::get_size_category`）；
- `memorial` 会在生日或特定节日（元旦、愚人节、儿童节、万圣节）生效，对不上就跳过这个限制；
- `intrusion` 和 `destruction` 会在 `0～4` 的档位里找最贴近当前数值的条目；
- 挑候选时尽量避开跟上次一模一样的正文，实在筛不出来就用杂物新闻（`size_category` 为空的条目）兜底；
- 拿到正文后，把 `{name}` / `{nick}` 替换成她的名字或昵称，再从 `substitute` 列的选项里随机挑词补进 `{a}` / `{b}`（详见 [resources.md](resources.md) §7）。

</details>

## 4. 档案导出：把她的 wiki 档案页带走

档案导出会把角色整理成**单个独立的 HTML 网页**（`services/character/archive_export.py::export_character_mhtml`）：图片、样式和脚本全都打包进同一个文件里，用浏览器直接双击就能看——发给朋友或放到任何静态网页空间都不会丢图。内容主要从 `data/archives/<角色id>/` 读取，包括 `avatar/`（形象图集，按修改时间从新到旧）、`报告/*.txt` 和 `回放/*.replay.json`。

| 档案板块 | 包含内容 |
|---|---|
| 顶部信息卡（Infobox） | 昵称、身高、生日、创建与更新时间、标签、最新形象图 |
| 灾害分析 | 介入度 / 破坏性进度条（满格 `4.5`，绿→黄→红；趋势变化达到 `±0.25` 会标出增强或收敛）+ 分档说明 + 演化统计图 + 应对建议 |
| 人物简介 | 可见简介与隐藏折叠卡、性格名称与描述、**作息与活动范围观察**（作息文字描述 + 空间档案）、已达成事件、形象图集 |
| 物理信息 | 尺寸对照表（对应当前生效的部位参数），已解锁情报的部位鼠标悬停可看详情 |
| 测量报告 | 左右双栏阅读器（左边按时间选报告，右边看正文），分类规则与游戏内报告面板一致；关闭 `show_casualties` 时会隐藏「本报告总计」行 |
| 事件记录 | 逐条展示副本回放：触发器 / 章节 / 结局卡片，加上步进类型标记（背景、分支、对话、互动、行动） |

- **演化统计图**：只看**最近 72 小时**，左轴是累计伤亡，右轴是每段步进。
- **应对指南**：按身高和档位估算安全疏散范围与无秩序影响范围。
- **地标悬浮提示**：报告正文里的地标名可以悬停查看当前状态，改地址不会清零耐久。

<details>
<summary>演化图、应对指南与地标状态的完整口径（核对导出数值或排查显示异常时展开）</summary>

- **演化统计图**（网页内矢量图）：分成 36 个 2 小时时段（和离线明细对齐）；恢复结算会优先按 `state.offline_details` 的时间段填进去，旧存档没有明细时按白天时段均摊。累计伤亡只增不减，不会出现「伤亡倒退」。
- **应对指南**：安全疏散范围按 `身高 × 档位系数` 估算（小于 `0.5m` 乘 `2`、小于 `1.5m` 乘 `5`、小于 `2.5m` 乘 `10`、小于 `3.5m` 乘 `18`，其余乘 `30`），无秩序影响范围约为 `疏散范围 × 介入度 / 10`；如果定位单元边长超过 `身高 × 100`，还会额外提示「定位可能不精确」。
- **地标悬浮提示**：地标耐久（`landmark_durability`）和地址记录（`landmark_addresses`）按地标声明身份（`landmarks:<风格id>/<显示名>`）记账；导出网页时会还原显示名、合并同名多地址，并把报告正文里的地标名变成可悬停查看状态的链接（`≤0` 已损毁 / `<0.5` 残破 / `<1.0` 受损 / 否则完好）。

</details>

## 5. 角色卡导出：搬运创建数据

角色卡是用来**跨存档/跨设备重建角色**的纯数据文件（JSON 格式，`version: "2.0"`，`services/exploration/export.py`）。它**只带创建设定，不包含任何时间经历**（没有演化记录、当前坐标、伤亡、离线明细、报告或回放）：

| 字段 | 对应内容 |
|---|---|
| `name / nick / original_height / birthday / tags` | 名字、昵称、原始身高、生日、标签 |
| `intro_hidden / intro_visible` | 隐藏简介与公开简介 |
| `personality_data / preset_data` | 完整性格数据与身材预设比例（由当前 `body_parts` 和 `height` 反算生成，默认预设名为「名字的身材」） |
| `image_b64` | 头像图片编码 |
| `origin_world / world_history` | 出身世界；世界履历仅在导出开关打开且有内容时写入（平时履历仍正常记录，开关只控制导出时带不带走） |

导出已载入的角色时，如果缺少性格或身材参数无法反算，会直接报错拒绝导出（`build_export_card_from_state` 抛出 `ValueError`）。文件保存为 UTF-8 编码的 JSON，挂件版会强制使用 `.chara.json` 后缀。档案导出和角色卡导出用的是同一个保存弹窗，按后缀名自动区分：选 `.html` 导出档案页，选 `.json` 导出角色卡。

## 6. 内部实现

- **72 小时 / 2 小时是全局统一约定**（`services/character/offline.py::_OFFLINE_WINDOW_HOURS` 与 `_OFFLINE_BIN_HOURS`）：离线明细、档案演化图和演化表界面都按这两个常量对齐，改其中一个时需同步检查三处。
- **载入流程与「算账 / 落盘」分离**：两个界面的载入都会走 `services/exploration/context.py::load_character_state`，先调 `OfflineService.recover_offline`，再依次执行负向演化、头像兜底和保存。其中 `build_recover_plan` 是只读纯函数，返回 `OfflineRecoveryPlan`（行为包可通过 `offline.recover_plan` 钩子替换整套计划），实际写回状态和记演化表由 `apply_recover_plan` 完成，文案则走 `offline.report_text` 钩子。
- **存档位置**：结算结果和离线明细会随角色基础信息一起保存在 `data/archives/<角色id>/info.json`（`persistence/character_repo.py::CharacterRepo`）。
- **缓存**：新闻表按服务实例缓存，切换取材表组时刷新（§3）；档案模板（`assets/templates/archive_template.{html,css,js}`）在进程内缓存并替换占位符。

## 7. 拓展用法

这里记录一些界面上没明说、但实际能用的玩法：

- **角色卡可以直接用文本编辑器改**：角色卡本质上是普通 JSON，除了在界面里导入导出，你也可以按 §5 的字段手动改完再「导入角色卡」。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](dungeon/README.md)（全景）·
  [script](dungeon/script.md)（章节与触发器字段）·
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
[剧本编辑器](scenario_editor.md) · [界面双模式与外观](ui_modes.md) ·
[角色的长期行为](character_time.md)（本页） · [身材剪影](body_preview.md) ·
[更新检查](update_check.md)

</details>
